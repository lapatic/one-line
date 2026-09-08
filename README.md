# one-line

Turns ordinary Python into a single-line, expression-only equivalent (`def` becomes a `lambda`, `if`/`while`/`for` become comprehensions or iterator tricks, locals live in a shared `storage` dict, etc.), then collapses that onto one physical line of code.

## Usage

```
python3 oneline_transform.py input.py output.py [output_min.py]
```

- `input.py` — your normal Python script
- `output.py` — the transformed, still-readable expression-only version (useful for debugging the transform)
- `output_min.py` — the same code minified to one line, ready to run (defaults to `output.py` with `_min` inserted before `.py`)

If the input uses `try`/`except`, `with`, or `raise`, keep `_rt.py` next to the generated file(s) at runtime — it's imported automatically.

### Supported subset

Imports (`import x`, no `from ... import`), assignment (incl. unpacking, augmented, annotated), `if`/`elif`/`else`, `while`, `for` (with `break`/`continue`), `try`/`except`/`else`/`finally`, `with`, `return`/`raise`, functions (incl. defaults, nested/closures), and single-level classes with methods and instance attributes. Most expressions (f-strings, comprehensions, calls) pass through as-is.

## Standalone minifier

`compress.py` just does the last step (joining already block-free statements with `;`) — run it directly if your source has no `if`/`while`/`for`/`def`/`try`/`with`/`class` blocks:

```
python3 compress.py
```

## Examples

There is an example script at ["normal.py"](normal.py), which I then manually converted into functional lambdas, at ["formatted.py"](formatted.py), and then compress.py was used to turn it into one line (removes whitespace and adds in semicolons). The final result can be seen at ["minimized.py"](minimized.py).

Also, and not yet converted (for dramatic effect) is attached ["mpy.py"](mpy.py), a video engine for auto-uploading youtube videos I made a few years ago, which has much more complex code in it to showcase the use of this converter (now I also haven't exactly fully tested the final result, it should work but maybe it doesn't idk).

## AI Disclosure

Most of this codebase was assisted in creation by using artificial intelligence tools. Originally, the example script was AI generated, and then a human (me) painstakingly sat through converting it to something that could be one-lined (["formatted.py"](formatted.py)). Then, I outlined the process and the guide I wanted (not attached here), and then made a very rudimentary auto-converter. After that, I passed it on to AI which converted it into the full ["oneline_transform.py"](oneline_transform.py) you see here, with all of the features it has. The file ["_rt.py"](_rt.py) was also AI generated as a helper script for that, giving some much needed functionality for the full one-line conversion. Finally, all but the last two sections of this README were created using AI. If you have issues with the use of these tools, just don't use this codebase. Anyways, for those of you who are fine with it, enjoy!

## Edit

Ok I just realized I could've totally used the walrus operator, :=, to make it a lot cleaner, maybe I'll get back to that, but it's unlikely.