# Worked migrations

Three real stories, by other people, imported into Parlance — with the author's
original file sitting next to the result so you can check the claim rather than
believe it.

| Example | Format | Source | Lines carried | Declared loss | Reachable |
|---|---|---|---|---|---|
| [`the-intercept`](the-intercept/) | Ink | [inkle](https://github.com/inkle/the-intercept), MIT | 546 lines, 300 options | 120 units | 387 / 546 |
| [`cyberharcelement`](cyberharcelement/) | Yarn Spinner | [Play Curious](https://github.com/play-curious/cyberharcelement), MIT | 544 lines, 95 options | 101 units | 446 / 544 |
| [`not-weird-queer`](not-weird-queer/) | Twine / Harlowe | [Jake Kao](https://github.com/PyrrhicShadow/Pyrrhic-s-Twinery), MIT | 1,003 lines, 176 links | 182 units | 454 / 1,003 |

Each directory holds the vendored source, the imported `project/`, the
`import.py` that produced it, a `SOURCE.md` recording the commit and the licence,
and a `REPORT.md` — which is where to start.

## The claim, and how to check it

`PUBLISHED_SKILLS.md` says of the importers:

> Every importer's output is checked against the source string by string. A
> paraphrase — the most tempting failure, because it looks like tidying — halts
> the import and is never retried.

You can run that check yourself. From `the-intercept/`:

```bash
python3 ../../lib/parse_ink.py TheIntercept.ink --emit manifest > /tmp/m.json && python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
```

It re-derives the yardstick from the source in that directory and compares the
committed project against it, then prints `STOP converged` — no line missing, no
line invented, no guard altered, no validator error. Change one word in the
project and it says `STOP invented` and names it. `tooling/tests/test_importer_examples.py`
runs exactly this in CI, so the claim cannot rot quietly.

## What these examples are for

**They are the honest picture, not the flattering one.** Read each `REPORT.md`'s
declared-loss table before anything else: it is the part that says what the format
could not carry, and which of those losses an author could fix by moving one line.

### Read the last column

All three converge. All three carry every word of their source, provably
unaltered. What differs is how much of each story a player can still walk, and
that number turned out to be the most informative thing here — including about
our own mistakes.

- **Ink** — 71%. What is cut off sits behind eight diverts into knots whose every
  line is declared loss; five of them behind a single sentence containing an
  inline conditional alternative (`{cond: a|b}` mid-line), which a node cannot
  hold.
- **Twine** — 45%. Links gated on conditions Parlance cannot express: read
  counts (`visits`), text comparisons, and variables the story assigns as two
  different kinds. In Harlowe every forward motion is a link, so a guard that
  does not map takes everything behind it.
- **Yarn** — 82%. No single break; its unreachable 98 are scenes routed by custom
  commands driving the game's own inbox UI.

None of these is a defect in the conversion, and **none is visible to a content
check** — no prose went anywhere. They are visible only by walking the imported
graph from its entry, which is why every report here does it and why the figures
are pinned in `tooling/tests/test_importer_examples.py`.

**That pinning has already earned itself twice**, both times on The Intercept.
It read 43/546 until an Ink TUNNEL — `-> knot -> onward`, a call that returns —
was recognised as expressible after all: a Parlance `goto` may point anywhere in
the dialogue, backwards included, so a tunnel with one call site is just two
ordinary edges. Reading it as unexpressible had severed the trunk and produced a
confident conclusion that the format needed a new control-flow construct. It does
not. What it would gain from one is the ability to express an *ambiguous* tunnel
without duplicating the scene — which is a much narrower claim, and one none of
these three stories establishes.

Two things they show that a synthetic fixture cannot:

- **What a real migration actually costs.** All three converge, and all three lose
  something. Much of what they lose is *positional* — a line one place further on
  in the source would import — and each report says which of its losses an author
  could fix and which are real gaps in the format.
- **That the parsers survive contact with real prose.** They did not, at first.
  The Intercept alone found eight parser defects the hand-written fixtures could
  not, one of which put 230 lines under a guard they did not have. *Not Weird.
  Queer* found five more in a Twine parser that had already imported a different
  story cleanly — every one of them a wrong REASON attached to a correct loss.
  Section 7 (or 8) of each report lists them.

  The counterpart is worth knowing too: the simpler Harlowe story this one
  replaced, **egg.exe** (MIT), converged with 84 declared losses and zero
  validator errors and needed no restructuring at all. **A simple Twine story
  imports as-is.** The difficulty scales with how much of the language a story
  uses, not with whether the importer works.

## Licensing

The content under each example directory is **third party**. `LICENSE-SPEC` grants
MIT over `tooling/importers/` but explicitly not over this directory: each example
carries its upstream licence in its own `LICENSE`, is redistributed under those
terms and no others, and records in `SOURCE.md` the commit it came from and the
upstream's own words about what the licence covers. `spec_lint.py` refuses to pass
an example missing any of those three files.

Both sources are MIT. Neither upstream requires attribution; both get it anyway,
because a worked example that did not say whose writing it was showing would be a
poor one.
