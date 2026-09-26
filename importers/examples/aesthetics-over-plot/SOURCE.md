# Source

**Aesthetics Over Plot**, by ronynn. In the author's own description: *"Get a
job trying to impress an omniscient cactus 🌵, a wall, and a really cool donkey,
made for Spring Thing 2023."* Written in Twee for Twine's SugarCube 2 format.

| | |
|---|---|
| Repository | https://github.com/ronynn/Game-Jam-Submissions |
| Commit | `c3879a832be995f4c266a637b809f8104613384f` (the latest commit touching the file) |
| Retrieved | 2026-09-24 |
| File taken | `aesthetics.tw` (45 passages), byte for byte |
| Licence | GPL-3.0 — see [`LICENSE`](LICENSE), copied verbatim from `LICENSE` at the repository root at that commit |

Nothing else from that repository is here: none of the author's other games, no
compiled `.html`, no images.

## What the licence covers

The repository carries the GNU General Public License, version 3, at its root,
with no carve-out for prose or assets in it or in the README, which describes the
repository as "Source Code to all of my game jam submissions". This story's source
file is one of them. It is redistributed here under GPL-3.0 and no other terms —
and so is the imported `project/`, which is a work based on it. `LICENSE-SPEC`
grants nothing over this directory.

The file's `UserScript` passage embeds Chapel's `notify.min.js` for SugarCube,
with its own attribution comment intact; it is carried verbatim as part of the
author's file and plays no part in the import (script passages are code, and the
parser accounts for them as such).

## Why this story

It is a real SugarCube game rather than a template or a macro library — the
search for one turned up far more of the latter — and it uses the format the way
people do: HTML in its lines, links with setters (`[[Suit->Step2][$dress to
"suit"]]`), `<<if>>`/`<<elseif>>`/`<<else>>` both on their own lines and inline
mid-sentence, a `<<textbox>>` feeding a naked `$password` back into the prose, a
`StoryCaption` sidebar, and a third-party container macro (`<<notify>>`). 45
passages is small enough to read in full next to its report.

## Reproducing it

From this directory:

```bash
python3 import.py
```

That rewrites `project/`. To verify it — which is the point of the example — see
[`REPORT.md`](REPORT.md).
