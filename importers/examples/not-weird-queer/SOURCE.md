# Source

**Not Weird. Queer** (a working title), by Jake Kao. In the author's own
description: *"a game about navigating middle school as a transgender person.
loosly autobiographical."* Written in Twine 2 with the Harlowe format.

| | |
|---|---|
| Repository | https://github.com/PyrrhicShadow/Pyrrhic-s-Twinery |
| Commit | `131fb674d68c4561985339123bc55333e59c819b` |
| Retrieved | 2026-08-26 |
| File taken | `twine/Not-Weird-Queer-0-0-008.html` (167 passages, the latest of eight versions in the repository) |
| Licence | MIT — see [`LICENSE`](LICENSE), copied verbatim from `LICENSE.md` at the repository root |

Nothing else from that repository is here: no images, no stylesheets, none of the
other four games in the collection.

## What the licence covers

A plain MIT licence at the repository root, Copyright (c) 2023 Jake Kao, with no
carve-out for prose or assets anywhere in it or in the README. The README
describes the repository as "a collection games made on Twine", of which this is
one. It is redistributed here under those terms.

Attribution is not required by MIT. It is here anyway, and the author's own
description of the work is quoted rather than paraphrased, because a worked
example that did not say whose writing it was showing would be a poor one.

## The published `.html`, not Twee

This repository ships the compiled story, which is what Twine produces and what
people distribute — no `.twee` exists for it. That is the ordinary case rather
than the exception, and it is why `parse_twine.py` reads the published file
first: see the note at the top of that parser. The story's prose is escaped in
the compiled form, and the parser decodes it on read, which returns the author's
bytes exactly.

`lamp_room.twee` and `lamp_room.html` in `fixtures/` are the same story in both
encodings, and the suite asserts they parse to identical units. That equivalence
is what makes reading a compiled file safe.

## Why this story

It was chosen after the first Twine example, `egg.exe`, turned out to exercise
very little: 4% of its imported nodes were reachable, and its shape — audio
cues, input widgets, endings decided by comparing two counters — is not how most
people write Twine.

This one is the opposite kind of test. 167 passages, 175 `(if:)` hooks and 164
`(set:)` calls, and it found five defects in a parser that had been written days
earlier and had already imported one story cleanly. Every one of the five
produced a **wrong reason attached to a correct loss** — see [`REPORT.md`](REPORT.md) §7.

## Reproducing it

From this directory:

```bash
python3 import.py
```

That rewrites `project/`. To verify it — which is the point of the example — see
[`REPORT.md`](REPORT.md).
