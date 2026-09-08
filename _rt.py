"""
_rt.py — tiny runtime support module for oneline_transform.py's generated code.

Python's `try/except` and `with` are block statements with no expression form
at all (unlike `if`/`while`, which can be rebuilt from ternaries and the
`iter(callable, sentinel)` trick). There is no way to catch an exception or
run a context manager from inside a single expression using only builtins.

So rather than pretend otherwise, the generated one-liner calls out to the
two tiny real functions below, which stay normal multi-line Python and are
NOT run through compress.py themselves -- only imported (via
`__import__("_rt")`, consistent with how the generated code inlines
`math`/`random`) by the generated file.
"""


def rt_try(body, handlers, orelse=None, finally_=None):
    """
    body:     zero-arg callable for the try block.
    handlers: list of (exc_types_or_None, handler) pairs, checked in order.
              exc_types_or_None is a class/tuple of classes to match, or
              None for a bare `except:`. handler is a one-arg callable
              taking the caught exception (or a dummy value for `except:`).
    orelse:   optional zero-arg callable, run if body() raised nothing.
    finally_: optional zero-arg callable, always run last.
    Returns whatever the branch that actually ran returned.
    """
    result = None
    raised = False
    try:
        result = body()
    except BaseException as e:
        raised = True
        for exc_types, handler in handlers:
            if exc_types is None or isinstance(e, exc_types):
                result = handler(e)
                break
        else:
            raise
    try:
        if not raised and orelse is not None:
            result = orelse()
    finally:
        if finally_ is not None:
            finally_()
    return result


def rt_isinstance(obj, checks):
    """A compiled class is a factory function, not a real type, so
    `isinstance(x, SomeCompiledClass)` can't work as plain Python isinstance
    any more. The generated code rewrites such calls to
    `rt_isinstance(x, checks)`, where each compiled-class name in `checks`
    has been replaced by its name as a string (checked against the
    `_rt_class` tag every instance is stamped with); anything else in
    `checks` (a real external type) is still checked with real isinstance."""
    if not isinstance(checks, tuple):
        checks = (checks,)
    for c in checks:
        if isinstance(c, str):
            if getattr(obj, "_rt_class", None) == c:
                return True
        elif isinstance(obj, c):
            return True
    return False


BREAK = object()  # sentinel a for-loop body returns to request an early exit


def rt_for(iterable, body, orelse=None):
    """`for target in iterable: body` with break/else support (the plain,
    no-break, no-else case compiles to a bare comprehension instead and
    never calls this). `body(item)` returning `BREAK` stops the loop and
    skips `orelse`, matching real for/break/else semantics."""
    broke = False
    for item in iterable:
        if body(item) is BREAK:
            broke = True
            break
    if not broke and orelse is not None:
        orelse()


def rt_with(context_manager, body):
    """`with context_manager as x: body(x)`, as a single call."""
    with context_manager as value:
        return body(value)


def rt_raise(exc=None):
    """`raise` (bare, re-raising the exception currently being handled) or
    `raise exc`. Called from inside an rt_try handler, a bare rt_raise()
    still re-raises correctly: we're still within the dynamic extent of the
    real `except` block in rt_try above, which is all `raise` needs."""
    if exc is None:
        raise
    raise exc
