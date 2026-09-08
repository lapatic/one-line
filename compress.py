"""
compress.py — collapses Python source that's already all simple statements
(no `if`/`while`/`for`/`def`/`try`/`with`/`class` blocks -- see
oneline_transform.py, which produces exactly that shape) down to one
physical line, by stripping comments/blank lines/indentation and joining
statements with `;`.

This only works on source that's already block-free: a real `if:`/`while:`
with an indented suite can't be joined onto one line by this (or any)
token-shuffling -- Python's grammar requires a newline after a block
header. See oneline_transform.py's docstring for why, and for the tool that
gets ordinary Python into that block-free shape in the first place.
"""

import tokenize
from io import StringIO


def minify_source(code: str) -> str:
    """Collapse already block-free Python source to one line of text.

    Pure string -> string; this is what oneline_transform.py calls directly
    on its own output. `minify()` below is a thin, file-based wrapper kept
    for backwards-compatible / interactive standalone use.
    """
    code = code.replace(";", "")
    tokens = tokenize.generate_tokens(StringIO(code).readline)
    output = []
    previous = None

    for token in tokens:
        token_type, text, start, end, _ = token

        if token_type in (
            tokenize.ENCODING,
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.INDENT,
            tokenize.DEDENT,
        ):
            continue

        if token_type == tokenize.NEWLINE:
            output.append(";")
            previous = token
            continue

        if previous:
            prev_text = previous.string

            # Add whitespace only when removing it would merge tokens. This
            # also does the right thing for f-strings on every tokenizer
            # version: pre-3.12 emits one whole STRING token for an
            # f-string (nothing to merge inside it); 3.12+ (PEP 701) splits
            # it into FSTRING_START/MIDDLE/END around the interpolated
            # expressions' own tokens, but those all fall through to the
            # same "append the text" handling below, unspecial-cased, and
            # get the same merge-avoidance treatment as any other token.
            if (
                (prev_text[-1:].isalnum() or prev_text[-1:] == "_")
                and (text[:1].isalnum() or text[:1] == "_")
            ):
                output.append(" ")

        output.append(text)
        previous = token

    return "".join(output).rstrip(";")


def minify(filename):
    """Original interface: reads `<filename>.py`, minifies it, and
    overwrites it in place. Kept for interactive/manual use."""
    with open(filename + ".py", "r") as f:
        code = f.read()

    result = minify_source(code)

    with open(filename + ".py", "w") as f:
        f.write(result)


if __name__ == "__main__":
    minify(input("Filename (no .py)? "))
