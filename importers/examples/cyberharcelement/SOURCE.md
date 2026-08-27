# Source

**Cyberenquête / Cyberharcèlement**, by [Play Curious](https://playcurious.games/).
An educational game about cyberbullying, written in Yarn Spinner.

| | |
|---|---|
| Repository | https://github.com/play-curious/cyberharcelement |
| Commit | `94da48807cf700ee1d5d2f53e8893f5428871ad3` |
| Retrieved | 2026-08-26 |
| Files taken | `scripts/episode1.yarn`, `scripts/episode2.yarn` |
| Licence | MIT — see [`LICENSE`](LICENSE), copied verbatim from the repository root |

Nothing else from that repository is here. The game's images, code, fonts and
build tooling are not vendored, not needed to reproduce the import, and — in the
case of the images — explicitly outside its MIT grant.

## What the licence covers, in the upstream's own words

The repository carries a plain MIT `LICENSE` (Copyright (c) 2024 Play Curious).
Its `README.md` adds one qualification, quoted here in full so you can read it
for yourself rather than take this file's word for it:

> This project's code is licensed under the MIT License.
>
> However, all visual assets (images) belong to Play Curious, and are licensed
> for use to France Médiation, Citéo and Instant Sciences for using and promoting
> the Cyberenquête game.

The carve-out names visual assets. The two `.yarn` files vendored here are
neither images nor covered by it, and they are redistributed under the MIT terms
in `LICENSE`. No image from the project is included.

This is a weaker statement than the other worked example's: inkle's README for
*The Intercept* says the game is MIT, in those words. Play Curious's says "code".
If you are making a redistribution decision of your own, read both documents at
the commit above rather than relying on the reading here.

## Two files, two namespaces

`episode1.yarn` and `episode2.yarn` are separate Yarn projects, not two halves of
one. Nine node titles — `Start`, `Bedroom2`, `Bedroom3`, `Bedroom4`, `Chat1`,
`Outside1`, `PreOutside1`, `Sms1`, `Sms2` — are defined in **both**, as different
scenes. They are imported under separate id namespaces (`n_episode1_…`,
`n_episode2_…`) for that reason.

That is worth knowing before you reuse this shape: keyed by title alone, the
second file's nine nodes vanish silently and take their prose with them. The
first version of the import script did exactly that, and the content check caught
it as 49 missing lines.

## Reproducing it

From this directory:

```bash
python3 import.py
```

That rewrites `project/` from the two `.yarn` files. To verify it — which is the
point of the example — see [`REPORT.md`](REPORT.md).
