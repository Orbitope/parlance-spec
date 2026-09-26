# Source

**The Question**, the short sample game that ships with Ren'Py: a student
decides whether to ask a childhood friend a question, and the two outcomes that
follow. Written in Ren'Py's own script language by the Ren'Py project.

| | |
|---|---|
| Repository | https://github.com/renpy/renpy |
| File taken | `the_question/game/script.rpy` (252 lines), from the `master` branch |
| Git blob | `ec1766da8e202ff4194812560519aa80228dabb2` — the SHA-1 of the vendored bytes, so the copy here is checkable against the repository's object store |
| Retrieved | 2026-09-24 |
| Licence | MIT — see [`LICENSE`](LICENSE), copied verbatim from `sphinx/source/license.rst` (blob `c86c22a827c96b92e97f2ab5a5c254a312037d9f`) |

The commit SHA is not recorded: this migration was vendored from a session
whose network policy allowed raw file reads but not the GitHub API that names
commits. The blob SHA pins the exact bytes instead, which is the property that
matters for a vendored source — anyone can `git log --find-object=ec1766da` in a
clone of the repository to find every commit that carried this file.

Nothing else from that repository is here: no images, no music, no
`options.rpy`/`screens.rpy`/`gui.rpy`, none of the translations under `tl/`.

## What the licence covers

Ren'Py's licence page opens: *"Most of Ren'Py is covered by the terms of the
following (MIT) license"*, and names the exceptions explicitly — portions derived
from LGPL-licensed source, and third-party dependencies, each listed with its own
licence. The game scripts in the repository are neither: they are the Ren'Py
project's own files, in its own tree, under its MIT grant. The same page extends
those terms to the demo's artwork (*"The artwork in the demo is released by
various copyright holders, under the same terms"*), which is not vendored here in
any case.

Two things this is deliberately NOT relying on:

- **The CC0 "Generated Project Dedication"** on the same page. It covers the
  `script.rpy` that Ren'Py GENERATES for a new project, not this one.
- **Anything about the tutorial game.** Only The Question is vendored.

It is redistributed here under the MIT terms, with the licence text alongside.

## Why this story

It is the one Ren'Py script nearly every Ren'Py author has read, and it is the
language's own idiom rather than anyone's house style: `define` with `_()`,
`default`, `scene`/`show`/`with`/`play`, a `menu:` with a caption, `jump`, a `$`
assignment, an `if` around a line, text tags, and `return`.

It is also small and linear, which cuts both ways — see [`REPORT.md`](REPORT.md)
§3 for what that means for how much this example proves.

## Reproducing it

From this directory:

```bash
python3 import.py
```

That rewrites `project/`. To verify it — which is the point of the example — see
[`REPORT.md`](REPORT.md).
