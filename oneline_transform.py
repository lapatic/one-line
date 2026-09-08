"""
oneline_transform.py — turns "normal" imperative/OOP Python into the
storage-dict / all-lambdas / expression-only style of formatted.py, so that
running compress.py on the result collapses it onto one line.

WHY this style exists
----------------------
Any Python statement that opens an indented suite (def, if/elif/else, while,
for, try/except, with, class) needs a NEWLINE + INDENT — the grammar has no
way to join it onto one physical line, even with semicolons. To get to a
single *line*, every such statement has to be rebuilt as a single
*expression* instead:

  * `def f(...): body`        -> `f = lambda ...: <one expression>`
  * `if/elif/else:`           -> a list of `(body if guard else None)` items
  * `while cond: body`        -> `list(iter(lambda: (body, cond)[-1], False))`
  * `for x in it: body`       -> `[body for x in it]` (a comprehension)
  * local variable assignment -> `storage.update(key=value)` (lambdas can't
    bind or rebind names, so every "local" lives in one shared global dict)
  * `class C: ...`            -> a factory lambda building a
    `types.SimpleNamespace` and attaching each method as a closure over it
  * `try/except`, `with`      -> Python has no expression form for these at
    all, so they're routed through two tiny real functions in `_rt.py`
    (`rt_try`, `rt_with`) that are NOT part of the one-lined program, only
    imported by it (see _rt.py's docstring)

Once everything is a plain `name = <expr>` or bare `<expr>` simple
statement, compress.py's tokenizer can safely glue every line together with
`;` and delete the newlines.

Usage
-----
    python3 oneline_transform.py input.py output.py [output_min.py]

This does the whole pipeline in one step: `output.py` gets the readable,
still-multi-line expression-only form (useful for debugging the
transform itself); `output_min.py` (default name if the third argument is
omitted: `output.py` with `_min` before the extension) gets that same code
run through compress.py's `minify_source()` and collapsed to one physical
line, ready to run as-is. If the input used try/except, with, or raise,
*both* generated files need `_rt.py` importable alongside them at runtime
(it's pulled in via `__import__("_rt")`, so it isn't literally copied into
the one-liner -- just needs to sit next to it, or be on PYTHONPATH).

Supported subset
-----------------
  - imports: `import x`, `import x as y` (inlined as `__import__("x")` at
    each use, and dropped as statements). `from ... import ...` is not
    handled.
  - assignment (incl. tuple/list unpacking, `obj.attr = v`, `obj[key] = v`
    for a string-literal key), augmented assignment (name or `obj["key"]`
    target), annotated assignment (annotation is dropped).
  - if/elif/else (arbitrary nesting), while (with break/continue), for
    (with continue only -- see limitations), try/except/else/finally,
    with-statements (incl. multiple context managers), return (incl. early
    return), raise (bare or with a value), function/method parameters with
    default values, nested function defs that close over outer locals,
    classes (single-level, no inheritance) with instance attributes and
    methods.
  - everything else (expressions, f-strings, comprehensions, calls, etc.)
    goes through `ast.unparse` after name-rewriting, so most expression-level
    Python "just works".

Known, deliberate limitations (documented rather than silently wrong)
-----------------------------------------------------------------------
  - a `for` loop with no `break` and no `else` compiles to a plain
    comprehension; one with either compiles instead to `_rt.rt_for(...)`,
    which runs a real Python `for` internally (so `break`/`else` behave
    exactly as they do in real Python -- this is what a for/else retry loop
    needs and gets).
  - a compiled class is a factory function building a fresh
    `types.SimpleNamespace` per instance, with each method attached as a
    closure over that instance (so `obj.method(args)` call sites don't need
    to change) -- there's no real class object and no inheritance, but
    `isinstance(x, SomeCompiledClass)` *is* supported: every instance is
    tagged with `self._rt_class = "ClassName"` at construction, and such an
    isinstance() call is rewritten to check that tag instead of failing with
    "isinstance() arg 2 must be a type" (which is what plain isinstance
    against a factory function would do).
  - "locals" live in one flat global `storage` dict, namespaced per
    function/method as `qualifiedname__varname` to avoid collisions between
    different functions/methods that happen to reuse a variable name. There
    is still no real call stack, so two *simultaneously in-flight* calls to
    the very same function/method (recursion, or re-entrant/interleaved
    calls on two instances) will stomp on each other's locals. Fine for
    straight-line / sequential-pipeline code (as this style always has
    been); not fine for anything recursive or concurrent.
  - a function/method's `return value` doesn't flow out via a normal Python
    return (a lambda built from a list-literal evaluates to that throwaway
    list, not "the value"). Instead `return` stores its value in
    `storage["qualifiedname__retval"]`, and every call to a "has a return
    somewhere" function/nested-function/`self.method()` is rewritten,
    wherever it appears in an expression *within the generated code*, to
    `(call(...), storage["qualifiedname__retval"])[-1]` so the value flows
    through correctly. A call to an *unrelated* object's method that
    happens to share a method name with one of our classes is not
    special-cased -- fine, since it's presumably a call to a real external
    object with real return semantics.
  - that rewriting only happens for calls made *inside* the generated file.
    Calling a compiled function/method from ordinary Python that imports the
    generated module (e.g. `import generated; generated.some_func(x)`) gets
    the same throwaway list back that the code above is rewritten to avoid --
    the real value has to be read from `generated.storage["some_func__retval"]`
    right after the call. Not an issue for a self-contained script (like
    normal.py) where every call is already inside the generated file and
    gets rewritten automatically; matters for a *library* of functions/
    classes (like world.py) meant to be called from other code.
  - a comprehension's own loop variable is matched by bare name, so if it
    happens to collide with a genuine assigned local elsewhere in the same
    function, the local's storage-rewrite would incorrectly apply inside
    the comprehension too. Rare; not something this transformer detects.
  - only simple `Name`/`Name[str-key]`/`Attribute`/tuple-of-those assignment
    targets are supported; starred targets (`a, *rest = ...`) aren't.
  - default parameter *expressions* are re-evaluated once per call (for a
    top-level function) or once per *instance construction* (for a method),
    rather than once at def-time -- harmless for pure/constant defaults
    (as used throughout normal.py/world.py-style code), but different from
    real Python's mutable-default-argument semantics.
"""

import ast
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compress import minify_source  # noqa: E402 -- needs sys.path set up first


class Unsupported(Exception):
    pass


# ---------------------------------------------------------------------------
# import-alias collection: `math.ceil(...)` -> `__import__("math").ceil(...)`,
# and `from io import BytesIO` -> `BytesIO` resolving to
# `__import__("io").BytesIO`. Collected tree-wide (not just top-level) since
# methods are free to `import os` locally -- those statements become no-ops
# once their alias is known globally.
# ---------------------------------------------------------------------------

class Imports:
    def __init__(self, modules, from_names):
        self.modules = modules          # alias -> real module name
        self.from_names = from_names    # alias -> (module, real name)


def collect_imports(tree):
    modules, from_names = {}, {}

    class V(ast.NodeVisitor):
        def visit_Import(self, node):
            for a in node.names:
                modules[a.asname or a.name] = a.name

        def visit_ImportFrom(self, node):
            if node.module is None:
                raise Unsupported("relative imports are not supported")
            for a in node.names:
                if a.name == "*":
                    raise Unsupported("`from x import *` is not supported")
                from_names[a.asname or a.name] = (node.module, a.name)

    V().visit(tree)
    return Imports(modules, from_names)


# ---------------------------------------------------------------------------
# Assignment-target helpers (shared by top-level analysis and codegen)
# ---------------------------------------------------------------------------

def _target_names(target, out, skip_names):
    """Collect the plain-Name identifiers a target would bind, for local-var
    detection. Subscript/Attribute targets don't create a new local (they
    mutate something that already exists), so they contribute nothing."""
    if isinstance(target, ast.Name):
        if target.id not in skip_names:
            out.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for e in target.elts:
            if isinstance(e, ast.Starred):
                raise Unsupported("starred assignment targets are not supported")
            _target_names(e, out, skip_names)
    elif isinstance(target, (ast.Subscript, ast.Attribute)):
        pass
    else:
        raise Unsupported(f"unsupported assignment target: {ast.dump(target)}")


def analyze_body(body, skip_names):
    """For one function/method body: collect (a) every name a plain
    assignment would create as a local, and (b) any *directly* nested
    FunctionDefs (their own internals are analyzed separately, recursively,
    when they themselves get compiled)."""
    names = set()
    funcs = []

    class V(ast.NodeVisitor):
        def visit_Assign(self, node):
            for t in node.targets:
                _target_names(t, names, skip_names)
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            _target_names(node.target, names, skip_names)
            self.generic_visit(node)

        def visit_AugAssign(self, node):
            if isinstance(node.target, ast.Name) and node.target.id not in skip_names:
                names.add(node.target.id)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            names.add(node.name)
            funcs.append(node)
            # deliberately don't descend -- compiled separately later

        def visit_ClassDef(self, node):
            raise Unsupported(f"classes nested inside a function are not supported: {node.name}")

        def visit_For(self, node):
            # a plain for-loop's target is comprehension-scoped (left as a
            # bare name, no storage needed); one that contains `break` gets
            # compiled via next()/callable-based iteration instead, where
            # the target needs a real, storage-backed binding.
            if contains_break(node.body):
                _target_names(node.target, names, skip_names)
            self.generic_visit(node)

    V().visit(ast.Module(body=body, type_ignores=[]))
    return names, funcs


def has_return_stmt(body):
    found = [False]

    class V(ast.NodeVisitor):
        def visit_Return(self, node):
            found[0] = True

        def visit_FunctionDef(self, node):
            pass  # a nested def's own `return` doesn't count for the outer one

    V().visit(ast.Module(body=body, type_ignores=[]))
    return found[0]


def is_docstring_stmt(stmt):
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def contains_break(stmts):
    found = [False]

    class V(ast.NodeVisitor):
        def visit_Break(self, node):
            found[0] = True

        def visit_For(self, node):
            pass  # a break in a nested for/while belongs to that loop

        def visit_While(self, node):
            pass

        def visit_FunctionDef(self, node):
            pass

    V().visit(ast.Module(body=stmts, type_ignores=[]))
    return found[0]


AUGOP_TEXT = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
    ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
    ast.LShift: "<<", ast.RShift: ">>",
}

RT = '__import__("_rt")'

# Names of classes this run of the transformer compiles, so `isinstance(x,
# SomeCompiledClass)` can be rewritten (see NameRewriter.visit_Call) --
# a compiled class is a factory *function*, not a real type, so plain
# isinstance() against it would just raise TypeError. Reset per transform_module()
# call; read by NameRewriter, which doesn't otherwise need per-instance state
# threaded through every constructor call site.
_CLASS_NAMES = set()


# ---------------------------------------------------------------------------
# AST rewriter: Name loads for local vars -> storage[...]; module.attr for
# imported modules -> __import__("module").attr; calls to "has a return"
# functions/methods -> wrapped so the call site still gets the return value.
# ---------------------------------------------------------------------------

class NameRewriter(ast.NodeTransformer):
    def __init__(self, funcname, local_vars, import_aliases, has_ret_by_name, current_class=None):
        self.funcname = funcname
        self.local_vars = local_vars
        self.import_aliases = import_aliases
        self.has_ret_by_name = has_ret_by_name
        self.current_class = current_class

    def storage_key(self, varname):
        return f"{self.funcname}__{varname}"

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            if node.id in self.local_vars:
                new = ast.Subscript(
                    value=ast.Name(id="storage", ctx=ast.Load()),
                    slice=ast.Constant(value=self.storage_key(node.id)),
                    ctx=ast.Load(),
                )
                return ast.copy_location(new, node)
            if node.id in self.import_aliases.from_names:
                module, real_name = self.import_aliases.from_names[node.id]
                new = ast.Attribute(
                    value=ast.Call(
                        func=ast.Name(id="__import__", ctx=ast.Load()),
                        args=[ast.Constant(value=module)],
                        keywords=[],
                    ),
                    attr=real_name,
                    ctx=ast.Load(),
                )
                ast.copy_location(new, node)
                ast.fix_missing_locations(new)
                return new
        return node

    def visit_Attribute(self, node):
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in self.import_aliases.modules
            and node.value.id not in self.local_vars
        ):
            real_module = self.import_aliases.modules[node.value.id]
            new_base = ast.Call(
                func=ast.Name(id="__import__", ctx=ast.Load()),
                args=[ast.Constant(value=real_module)],
                keywords=[],
            )
            new_node = ast.Attribute(value=new_base, attr=node.attr, ctx=node.ctx)
            ast.copy_location(new_node, node)
            ast.fix_missing_locations(new_node)
            return new_node
        self.generic_visit(node)
        return node

    def _rewrite_isinstance_types(self, type_arg):
        if isinstance(type_arg, ast.Name) and type_arg.id in _CLASS_NAMES:
            return True, ast.Constant(value=type_arg.id)
        if isinstance(type_arg, ast.Tuple):
            replaced = False
            elts = []
            for e in type_arg.elts:
                if isinstance(e, ast.Name) and e.id in _CLASS_NAMES:
                    elts.append(ast.Constant(value=e.id))
                    replaced = True
                else:
                    elts.append(e)
            if replaced:
                return True, ast.Tuple(elts=elts, ctx=ast.Load())
        return False, None

    def visit_Call(self, node):
        self.generic_visit(node)
        func = node.func

        if (
            isinstance(func, ast.Name)
            and func.id == "isinstance"
            and func.id not in self.local_vars
            and len(node.args) == 2
        ):
            replaced, checks_node = self._rewrite_isinstance_types(node.args[1])
            if replaced:
                new_call = ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(func=ast.Name(id="__import__", ctx=ast.Load()), args=[ast.Constant(value="_rt")], keywords=[]),
                        attr="rt_isinstance",
                        ctx=ast.Load(),
                    ),
                    args=[node.args[0], checks_node],
                    keywords=[],
                )
                ast.copy_location(new_call, node)
                ast.fix_missing_locations(new_call)
                return new_call

        retval_key = None
        if isinstance(func, ast.Name):
            if func.id in self.local_vars:
                qualified = self.storage_key(func.id)
                if self.has_ret_by_name.get(qualified):
                    retval_key = f"{qualified}__retval"
            elif self.has_ret_by_name.get(func.id):
                retval_key = f"{func.id}__retval"
        elif (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and self.current_class
        ):
            qualified = f"{self.current_class}__{func.attr}"
            if self.has_ret_by_name.get(qualified):
                retval_key = f"{qualified}__retval"
        if retval_key is None:
            return node
        tup = ast.Tuple(
            elts=[
                node,
                ast.Subscript(
                    value=ast.Name(id="storage", ctx=ast.Load()),
                    slice=ast.Constant(value=retval_key),
                    ctx=ast.Load(),
                ),
            ],
            ctx=ast.Load(),
        )
        sub = ast.Subscript(
            value=tup,
            slice=ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=1)),
            ctx=ast.Load(),
        )
        ast.copy_location(sub, node)
        ast.fix_missing_locations(sub)
        return sub


def render_expr(node, rewriter):
    """Deep-copy + rewrite + unparse a single expression node to source text."""
    new_node = rewriter.visit(copy.deepcopy(node))
    ast.fix_missing_locations(new_node)
    return ast.unparse(new_node)


# ---------------------------------------------------------------------------
# Per-function/method compile state
# ---------------------------------------------------------------------------

class FuncCtx:
    def __init__(self, name, params, local_vars, has_ret, current_class=None):
        self.name = name
        self.params = params
        self.local_vars = local_vars
        self.has_ret = has_ret
        self.ret_flag_key = f"{name}__ret"
        self.ret_val_key = f"{name}__retval"
        self.current_class = current_class
        self.loop_stack = []         # active for/while continue-flag keys, innermost last
        self.while_break_stack = []  # active while break-flag keys, innermost last
        self._tmp = 0

    def next_tmp(self):
        self._tmp += 1
        return self._tmp


def guard(code, ctx):
    """Wrap a compiled statement so it's a no-op once the function has
    returned, or the innermost enclosing loop has continue'd this
    iteration."""
    conds = []
    if ctx.has_ret:
        conds.append(f'not storage["{ctx.ret_flag_key}"]')
    for key in ctx.loop_stack:
        conds.append(f'not storage["{key}"]')
    if not conds:
        return code
    return f'({code} if ({" and ".join(conds)}) else None)'


# ---------------------------------------------------------------------------
# Assignment targets
# ---------------------------------------------------------------------------

def compile_assign_targets(target, ctx, rewriter, value_text):
    """Returns a list of `storage.update(...)`/`setattr(...)`/`base.update(...)`
    expression strings that together perform one assignment."""
    if isinstance(target, ast.Name):
        key = f"{ctx.name}__{target.id}"
        return [f"storage.update({key}={value_text})"]

    if isinstance(target, ast.Attribute):
        obj_text = render_expr(target.value, rewriter)
        return [f'setattr({obj_text}, "{target.attr}", {value_text})']

    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
        if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
            return [f"{target.value.id}.update({target.slice.value}={value_text})"]
        raise Unsupported("subscript assignment is only supported with a string-literal key")

    if isinstance(target, (ast.Tuple, ast.List)):
        tmp_key = f"{ctx.name}__tmp{ctx.next_tmp()}"
        parts = [f"storage.update({tmp_key}={value_text})"]
        for i, elt in enumerate(target.elts):
            if isinstance(elt, ast.Starred):
                raise Unsupported("starred assignment targets are not supported")
            parts.extend(compile_assign_targets(elt, ctx, rewriter, f'storage["{tmp_key}"][{i}]'))
        return parts

    raise Unsupported(f"unsupported assignment target: {ast.dump(target)}")


# ---------------------------------------------------------------------------
# Statement compilation
# ---------------------------------------------------------------------------

def compile_stmt(stmt, ctx, rewriter, has_ret_by_name):
    if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
        if isinstance(stmt, ast.AnnAssign):
            if stmt.value is None:
                return "None"
            targets = [stmt.target]
        else:
            targets = stmt.targets
        val = render_expr(stmt.value, rewriter)
        parts = []
        for t in targets:
            parts.extend(compile_assign_targets(t, ctx, rewriter, val))
        return parts[0] if len(parts) == 1 else "[" + ", ".join(parts) + "]"

    if isinstance(stmt, ast.AugAssign):
        opstr = AUGOP_TEXT.get(type(stmt.op))
        if opstr is None:
            raise Unsupported(f"unsupported augmented-assign operator: {stmt.op}")
        val = render_expr(stmt.value, rewriter)
        target = stmt.target

        if isinstance(target, ast.Name):
            key = f"{ctx.name}__{target.id}"
            return f'storage.update({key}=storage["{key}"]{opstr}({val}))'

        if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
            if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                base, keyname = target.value.id, target.slice.value
                return f'{base}.update({keyname}={base}["{keyname}"]{opstr}({val}))'

        if isinstance(target, ast.Attribute):
            obj_text = render_expr(target.value, rewriter)
            attr = target.attr
            return (
                f'setattr({obj_text}, "{attr}", '
                f'getattr({obj_text}, "{attr}"){opstr}({val}))'
            )

        raise Unsupported(f"unsupported augmented-assign target: {ast.dump(target)}")

    if is_docstring_stmt(stmt):
        return "None"

    if isinstance(stmt, ast.Expr):
        return render_expr(stmt.value, rewriter)

    if isinstance(stmt, ast.If):
        return compile_if(stmt, ctx, rewriter, has_ret_by_name)

    if isinstance(stmt, ast.While):
        return compile_while(stmt, ctx, rewriter, has_ret_by_name)

    if isinstance(stmt, ast.For):
        return compile_for(stmt, ctx, rewriter, has_ret_by_name)

    if isinstance(stmt, ast.Try):
        return compile_try(stmt, ctx, rewriter, has_ret_by_name)

    if isinstance(stmt, ast.With):
        return compile_with(stmt.items, stmt.body, ctx, rewriter, has_ret_by_name)

    if isinstance(stmt, ast.Return):
        val = render_expr(stmt.value, rewriter) if stmt.value is not None else "None"
        return f'storage.update(**{{"{ctx.ret_flag_key}": True, "{ctx.ret_val_key}": {val}}})'

    if isinstance(stmt, ast.Raise):
        if stmt.cause is not None:
            raise Unsupported("`raise ... from ...` is not supported")
        if stmt.exc is None:
            return f"{RT}.rt_raise()"
        return f"{RT}.rt_raise({render_expr(stmt.exc, rewriter)})"

    if isinstance(stmt, ast.Continue):
        if not ctx.loop_stack:
            raise Unsupported("`continue` outside a loop")
        return f'storage.update({ctx.loop_stack[-1]}=True)'

    if isinstance(stmt, ast.Break):
        if not ctx.while_break_stack:
            raise Unsupported("`break` is only supported inside `while` loops")
        return f'storage.update({ctx.while_break_stack[-1]}=True)'

    if isinstance(stmt, ast.Pass):
        return "None"

    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return "None"  # already resolved tree-wide by collect_imports()

    if isinstance(stmt, ast.Global) or isinstance(stmt, ast.Nonlocal):
        return "None"  # storage is already global/shared; nothing to do

    raise Unsupported(f"unsupported statement type: {type(stmt).__name__}")


def compile_seq(stmts, ctx, rewriter, has_ret_by_name):
    """Compile a list of statements into one list-literal expression (list
    literals evaluate their elements strictly left-to-right)."""
    real = [s for s in stmts if not isinstance(s, (ast.Pass, ast.FunctionDef))]
    if not real:
        return "[]"
    parts = [guard(compile_stmt(s, ctx, rewriter, has_ret_by_name), ctx) for s in real]
    return "[" + ", ".join(parts) + "]"


def compile_if(stmt, ctx, rewriter, has_ret_by_name):
    branches = []
    cur = stmt
    while True:
        branches.append((cur.test, cur.body))
        if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
            cur = cur.orelse[0]
            continue
        if cur.orelse:
            branches.append((None, cur.orelse))
        break

    items = []
    prior_conds = []
    for cond, body in branches:
        cond_text = render_expr(cond, rewriter) if cond is not None else None
        guard_parts = []
        if cond_text is not None:
            guard_parts.append(f"({cond_text})")
        guard_parts.extend(f"not ({pc})" for pc in prior_conds)
        guard_expr = " and ".join(guard_parts) if guard_parts else "True"
        body_expr = compile_seq(body, ctx, rewriter, has_ret_by_name)
        items.append(f"(({body_expr}) if ({guard_expr}) else None)")
        if cond_text is not None:
            prior_conds.append(cond_text)

    return "[" + ", ".join(items) + "]"


def compile_while(stmt, ctx, rewriter, has_ret_by_name):
    if stmt.orelse:
        raise Unsupported("while/else is not supported")

    break_key = f"{ctx.name}__brk{ctx.next_tmp()}"
    cont_key = f"{ctx.name}__cont{ctx.next_tmp()}"
    ctx.while_break_stack.append(break_key)
    ctx.loop_stack.append(cont_key)
    try:
        parts = [f"storage.update({cont_key}=False)"]
        parts += [guard(compile_stmt(s, ctx, rewriter, has_ret_by_name), ctx) for s in stmt.body]
        cond_text = render_expr(stmt.test, rewriter)
    finally:
        ctx.while_break_stack.pop()
        ctx.loop_stack.pop()

    parts.append(f'(({cond_text}) and not storage["{break_key}"])')
    tuple_text = "(" + ", ".join(parts) + ")[-1]"
    # `iter(callable, sentinel)` always runs the body once before its first
    # check, i.e. do/while -- so the loop is only entered at all if the
    # condition is already true, matching real `while` semantics. (`and`
    # short-circuits on a falsy left side without ever calling list(iter(...)),
    # and doesn't care that list(iter(...)) itself may come back falsy/empty.)
    loop_text = f"(({cond_text}) and list(iter(lambda: {tuple_text}, False)))"
    return f"[storage.update({break_key}=False), {loop_text}][-1]"


def compile_for(stmt, ctx, rewriter, has_ret_by_name):
    has_brk = contains_break(stmt.body)
    if has_brk or stmt.orelse:
        return compile_for_with_break_or_else(stmt, ctx, rewriter, has_ret_by_name, has_brk)

    # Fast path: no break, no else -> a plain comprehension. The loop
    # target is left as a bare, comprehension-scoped name (not storage).
    target_text = ast.unparse(stmt.target)
    iter_text = render_expr(stmt.iter, rewriter)

    cont_key = f"{ctx.name}__cont{ctx.next_tmp()}"
    ctx.loop_stack.append(cont_key)
    try:
        parts = [f"storage.update({cont_key}=False)"]
        parts += [guard(compile_stmt(s, ctx, rewriter, has_ret_by_name), ctx) for s in stmt.body]
    finally:
        ctx.loop_stack.pop()

    body_list = "[" + ", ".join(parts) + "]"
    return f"[{body_list} for {target_text} in {iter_text}]"


def compile_for_with_break_or_else(stmt, ctx, rewriter, has_ret_by_name, has_brk):
    """A for-loop using `break` and/or `else` can't be a comprehension (it
    can't exit early), so it's compiled to `_rt.rt_for(iterable, body,
    orelse=...)` instead: `body` is called once per item and may return
    `_rt.BREAK` to stop early. Here the loop target *is* storage-backed
    (bound via the same unpacking machinery as a plain assignment), since
    it's no longer a comprehension's own bound name."""
    iter_text = render_expr(stmt.iter, rewriter)
    cont_key = f"{ctx.name}__cont{ctx.next_tmp()}"
    brk_key = f"{ctx.name}__brk{ctx.next_tmp()}" if has_brk else None

    ctx.loop_stack.append(cont_key)
    if has_brk:
        ctx.while_break_stack.append(brk_key)
    try:
        parts = [f"storage.update({cont_key}=False)"]
        parts += compile_assign_targets(stmt.target, ctx, rewriter, "_item")
        parts += [guard(compile_stmt(s, ctx, rewriter, has_ret_by_name), ctx) for s in stmt.body]
        if has_brk:
            parts.append(f'({RT}.BREAK if storage["{brk_key}"] else None)')
    finally:
        ctx.loop_stack.pop()
        if has_brk:
            ctx.while_break_stack.pop()

    body_lambda = f"(lambda _item: ([{', '.join(parts)}])[-1])"
    orelse_arg = ""
    if stmt.orelse:
        orelse_expr = compile_seq(stmt.orelse, ctx, rewriter, has_ret_by_name)
        orelse_arg = f", orelse=(lambda: {orelse_expr})"

    call_expr = f"{RT}.rt_for({iter_text}, {body_lambda}{orelse_arg})"
    if has_brk:
        return f"[storage.update({brk_key}=False), {call_expr}][-1]"
    return call_expr


def compile_try(stmt, ctx, rewriter, has_ret_by_name):
    body_text = f"(lambda: {compile_seq(stmt.body, ctx, rewriter, has_ret_by_name)})"

    handler_items = []
    for h in stmt.handlers:
        type_text = render_expr(h.type, rewriter) if h.type is not None else "None"
        pname = h.name if h.name else "_exc"
        handler_body = compile_seq(h.body, ctx, rewriter, has_ret_by_name)
        handler_items.append(f"({type_text}, (lambda {pname}: {handler_body}))")
    handlers_text = "[" + ", ".join(handler_items) + "]"

    orelse_text = (
        f"(lambda: {compile_seq(stmt.orelse, ctx, rewriter, has_ret_by_name)})" if stmt.orelse else "None"
    )
    finally_text = (
        f"(lambda: {compile_seq(stmt.finalbody, ctx, rewriter, has_ret_by_name)})" if stmt.finalbody else "None"
    )
    return f"{RT}.rt_try({body_text}, {handlers_text}, orelse={orelse_text}, finally_={finally_text})"


def compile_with(items, body, ctx, rewriter, has_ret_by_name):
    if not items:
        return compile_seq(body, ctx, rewriter, has_ret_by_name)
    item = items[0]
    cm_text = render_expr(item.context_expr, rewriter)
    pname = "_cm"
    if item.optional_vars is not None:
        if not isinstance(item.optional_vars, ast.Name):
            raise Unsupported("only a simple `as name` is supported in a with-statement")
        pname = item.optional_vars.id
    inner = compile_with(items[1:], body, ctx, rewriter, has_ret_by_name)
    return f"{RT}.rt_with({cm_text}, (lambda {pname}: {inner}))"


# ---------------------------------------------------------------------------
# Function/method lambda compilation (shared by top-level defs, nested defs,
# and class methods)
# ---------------------------------------------------------------------------

def _params_and_defaults(args, import_aliases, qualified_name, has_ret_by_name, drop_first):
    if args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs:
        raise Unsupported("only plain positional parameters (no *args/**kwargs/keyword-only) are supported")
    all_args = args.args
    start = 1 if drop_first else 0
    num_defaults = len(args.defaults)
    default_for_index = {len(all_args) - num_defaults + i: d for i, d in enumerate(args.defaults)}
    default_rewriter = NameRewriter(qualified_name, set(), import_aliases, has_ret_by_name)

    sig_parts = []
    for i in range(start, len(all_args)):
        name = all_args[i].arg
        if i in default_for_index:
            dtext = render_expr(default_for_index[i], default_rewriter)
            sig_parts.append(f"{name}={dtext}")
        else:
            sig_parts.append(name)
    params = [all_args[i].arg for i in range(start, len(all_args))]
    return params, sig_parts


def compile_lambda_body(fd, qualified_name, import_aliases, has_ret_by_name, drop_first_param=False, current_class=None):
    params, sig_parts = _params_and_defaults(fd.args, import_aliases, qualified_name, has_ret_by_name, drop_first_param)

    skip_names = set()  # names never routed to storage even if assigned (none needed beyond 'self', handled via drop)
    local_names, nested_funcs = analyze_body(fd.body, skip_names)
    all_local_names = set(local_names) | {nf.name for nf in nested_funcs}

    has_ret = has_return_stmt(fd.body)
    ctx = FuncCtx(qualified_name, params, all_local_names, has_ret, current_class)
    rewriter = NameRewriter(qualified_name, all_local_names, import_aliases, has_ret_by_name, current_class)

    body_parts = []
    if has_ret:
        body_parts.append(f'storage.update(**{{"{ctx.ret_flag_key}": False}})')
    for p in params:
        if p in all_local_names:  # a parameter that also gets reassigned -> seed storage with its initial value
            body_parts.append(f"storage.update({qualified_name}__{p}={p})")
    for nf in nested_funcs:
        nf_qualified = f"{qualified_name}__{nf.name}"
        has_ret_by_name[nf_qualified] = has_return_stmt(nf.body)
        nf_lambda_text = compile_lambda_body(nf, nf_qualified, import_aliases, has_ret_by_name)
        body_parts.append(f"storage.update({nf_qualified}={nf_lambda_text})")

    real_stmts = [s for s in fd.body if not isinstance(s, (ast.Pass, ast.FunctionDef))]
    for s in real_stmts:
        body_parts.append(guard(compile_stmt(s, ctx, rewriter, has_ret_by_name), ctx))
    if not body_parts:
        body_parts.append("None")

    body_expr = "[" + ", ".join(body_parts) + "]"
    params_text = ", ".join(sig_parts)
    return f"(lambda {params_text}: {body_expr})" if params_text else f"(lambda: {body_expr})"


def compile_function(fd, import_aliases, has_ret_by_name):
    has_ret_by_name[fd.name] = has_return_stmt(fd.body)
    lam = compile_lambda_body(fd, fd.name, import_aliases, has_ret_by_name)
    return f"{fd.name} = {lam}"


# ---------------------------------------------------------------------------
# Class compilation
# ---------------------------------------------------------------------------

def compile_class(cd, import_aliases, has_ret_by_name):
    name = cd.name
    if cd.bases or cd.keywords:
        raise Unsupported(f"class inheritance is not supported: {name}")

    init_fd = None
    methods = []
    class_attrs = []  # (target, value) plain class-body assignments

    for item in cd.body:
        if isinstance(item, ast.FunctionDef):
            if item.name == "__init__":
                init_fd = item
            else:
                methods.append(item)
        elif isinstance(item, (ast.Assign, ast.AnnAssign)):
            if isinstance(item, ast.AnnAssign):
                if item.value is None:
                    continue
                class_attrs.append((item.target, item.value))
            else:
                if len(item.targets) != 1 or not isinstance(item.targets[0], ast.Name):
                    raise Unsupported(f"only simple class-level attributes are supported: {name}")
                class_attrs.append((item.targets[0], item.value))
        elif is_docstring_stmt(item):
            continue
        elif isinstance(item, ast.Pass):
            continue
        else:
            raise Unsupported(f"unsupported class body statement in {name}: {type(item).__name__}")

    # Register every method's return-ness up front, so calls between
    # sibling methods (self.other()) resolve correctly regardless of order.
    for m in methods:
        has_ret_by_name[f"{name}__{m.name}"] = has_return_stmt(m.body)
    if init_fd is not None:
        has_ret_by_name[f"{name}____init__"] = has_return_stmt(init_fd.body)

    class_rewriter = NameRewriter(f"{name}__class", set(), import_aliases, has_ret_by_name)
    setup_parts = [f'setattr(self, "_rt_class", "{name}")']
    for target, value in class_attrs:
        val_text = render_expr(value, class_rewriter)
        setup_parts.append(f'setattr(self, "{target.id}", {val_text})')

    for m in methods:
        qualified = f"{name}__{m.name}"
        lam_text = compile_lambda_body(
            m, qualified, import_aliases, has_ret_by_name, drop_first_param=True, current_class=name
        )
        setup_parts.append(f'setattr(self, "{m.name}", {lam_text})')

    if init_fd is not None:
        init_qualified = f"{name}____init__"
        params, sig_parts = _params_and_defaults(
            init_fd.args, import_aliases, init_qualified, has_ret_by_name, drop_first=True
        )
        local_names, nested_funcs = analyze_body(init_fd.body, set())
        all_local_names = set(local_names) | {nf.name for nf in nested_funcs}
        has_ret = has_return_stmt(init_fd.body)  # real __init__ shouldn't return a value, but tolerate it
        ctx = FuncCtx(init_qualified, params, all_local_names, has_ret, current_class=name)
        rewriter = NameRewriter(init_qualified, all_local_names, import_aliases, has_ret_by_name, current_class=name)
        for nf in nested_funcs:
            nf_qualified = f"{init_qualified}__{nf.name}"
            has_ret_by_name[nf_qualified] = has_return_stmt(nf.body)
            setup_parts.append(f"storage.update({nf_qualified}={compile_lambda_body(nf, nf_qualified, import_aliases, has_ret_by_name)})")
        for s in init_fd.body:
            if isinstance(s, (ast.Pass, ast.FunctionDef)):
                continue
            setup_parts.append(guard(compile_stmt(s, ctx, rewriter, has_ret_by_name), ctx))
        ctor_params, ctor_sig_parts = params, sig_parts
    else:
        ctor_params, ctor_sig_parts = [], []

    setup_parts.append("self")
    body_list = "[" + ", ".join(setup_parts) + "]"
    make_expr = f'(lambda self: ({body_list})[-1])(__import__("types").SimpleNamespace())'
    ctor_sig_text = ", ".join(ctor_sig_parts)
    ctor_lambda = f"(lambda {ctor_sig_text}: {make_expr})" if ctor_sig_text else f"(lambda: {make_expr})"
    return f"{name} = {ctor_lambda}"


# ---------------------------------------------------------------------------
# Module-level driver
# ---------------------------------------------------------------------------

def transform_module(source_text):
    tree = ast.parse(source_text)
    import_aliases = collect_imports(tree)
    has_ret_by_name = {}

    _CLASS_NAMES.clear()
    _CLASS_NAMES.update(node.name for node in tree.body if isinstance(node, ast.ClassDef))

    module_rewriter = NameRewriter("<module>", set(), import_aliases, has_ret_by_name)

    out_lines = ["storage = {}"]
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue  # replaced by inline __import__() at each use site
        if is_docstring_stmt(node):
            continue
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise Unsupported("unsupported top-level assignment")
            val = render_expr(node.value, module_rewriter)
            out_lines.append(f"{node.targets[0].id} = {val}")
            continue
        if isinstance(node, ast.FunctionDef):
            out_lines.append(compile_function(node, import_aliases, has_ret_by_name))
            continue
        if isinstance(node, ast.ClassDef):
            out_lines.append(compile_class(node, import_aliases, has_ret_by_name))
            continue
        if isinstance(node, ast.Expr):
            out_lines.append(render_expr(node.value, module_rewriter))
            continue
        raise Unsupported(f"unsupported top-level statement: {type(node).__name__}")

    return "\n\n".join(out_lines) + "\n"


def _default_minified_path(output_path):
    if output_path.endswith(".py"):
        return output_path[: -len(".py")] + "_min.py"
    return output_path + ".min.py"


def main():
    if len(sys.argv) not in (3, 4):
        print(
            "usage: python3 oneline_transform.py <input.py> <output.py> [<minified_output.py>]",
            file=sys.stderr,
        )
        raise SystemExit(1)
    with open(sys.argv[1]) as f:
        source = f.read()

    result = transform_module(source)
    with open(sys.argv[2], "w") as f:
        f.write(result)
    print(f"wrote {sys.argv[2]}")

    minified_path = sys.argv[3] if len(sys.argv) == 4 else _default_minified_path(sys.argv[2])
    minified = minify_source(result)
    minified = minified.replace("\n\n", ";")
    with open(minified_path, "w") as f:
        f.write(minified)
    print(f"wrote {minified_path} (one line, {len(minified)} chars)")


if __name__ == "__main__":
    main()
