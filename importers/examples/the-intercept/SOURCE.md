# Source

**The Intercept**, by [inkle](https://www.inklestudios.com/). Bletchley Park,
1942: a component from the Bombe machine has gone missing and a cryptographer is
waiting to be interviewed. Written in Ink, built for a game jam, and published as
inkle's own worked example of how they structure an Ink project.

| | |
|---|---|
| Repository | https://github.com/inkle/the-intercept |
| Commit | `2a816b56e61ce4bf02bec1c638074645bdd871e3` |
| Retrieved | 2026-08-26 |
| File taken | `Assets/Ink/TheIntercept.ink` (1,427 non-blank lines, ~17,100 words) |
| Licence | MIT — see [`LICENSE`](LICENSE), the notice from the repository's README |

Nothing else from that repository is here: no Unity project, no plugins, no
audio. The single `.ink` file is the whole story and is all that is needed to
reproduce the import.

## What the licence covers, in the upstream's own words

The repository's `README.md` states it directly, and unusually clearly for a
game — it names the STORY, not only the code:

> **The Intercept** and **ink** are released under the MIT license. Although we
> don't require attribution, we'd love to know if you decide to use **ink** a
> project!
>
> ### The MIT License (MIT)
> Copyright (c) 2016 inkle Ltd.

That is the notice reproduced in [`LICENSE`](LICENSE). Attribution is not
required; it is here anyway, because a worked example that did not say whose
writing it was showing would be a poor one.

## Why this story

It was chosen before any of this was built, as the hardest honest test available.
`tooling/NODE_CONDITIONS_SPEC.md` measured it at **~20% of narration lines under
a condition — 126 instances**, the highest of any corpus surveyed and the single
largest argument for adding `DialogueNode.showIf` to the format at all. Importing
it before that field existed would have dropped a fifth of the narration.

It is also a hard test of the weave: 63 containers, 338 choices, 95 gathers, and
54 labelled choices and gathers used as divert targets.

## Reproducing it

From this directory:

```bash
python3 import.py
```

That rewrites `project/` from `TheIntercept.ink`. To verify it — which is the
point of the example — see [`REPORT.md`](REPORT.md).
