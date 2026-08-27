# Import report — The Intercept

Source: one Ink file, 1,427 non-blank lines, ~17,100 words, 63 containers. See
[`SOURCE.md`](SOURCE.md) for provenance and licence.

## 1. Verdict and counts

**`STOP converged`.** Nothing lost, nothing invented, no guard altered, no
validator error.

| | source | output |
|---|---|---|
| narration lines carried | 546 | 546 |
| options carried | 300 | 300 |
| lines under a `showIf` | — | 78 |
| dialogues | 63 containers | 1 |
| declared loss | 120 units | — |
| nodes a player can reach | — | **387 of 546** |

Reproduce both halves from this directory:

```bash
python3 import.py
```

```bash
python3 ../../lib/parse_ink.py TheIntercept.ink --emit manifest > /tmp/m.json && python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
```

The second command re-derives the yardstick from the vendored source and compares
the project against it. It is the whole claim of this example: you do not have to
believe that no prose was rewritten, because the check refuses to converge if any
was.

**One dialogue, 546 nodes.** Every container is reachable from every other by a
divert, and a Parlance `goto` is within-dialogue only — so the story is one
dialogue by the rule, not by preference. It is also one *character*: The Intercept
is written in the first person with its dialogue inside quotation marks, so almost
no line carries a `Speaker:` prefix for the parser to derive a character from.

## 2. Declared loss — 120 units

Lead with this. Every one is reported with its source line in the manifest's
`unmapped`.

| n | what | can the author fix it? |
|---|---|---|
| 40 | **Body of a choice that is itself unmappable**, so it can never be reached. | Follows from the rows below; fix the choice and the body returns. |
| 26 | **Gated on a read count** — `{opts > 1}`, `{not shouted}`, `{claim_hooper_took_component.hoopers_hut_3}`. Ink can test how many times a knot, stitch or *labelled choice* has been visited. Parlance has no read-count condition at all. | Only by restructuring: set a flag where the visit happens and gate on that. |
| 25 | **Inline conditional alternative** — `{not think:What I am is\|I am} a problem—solver.` Two variants of PART of a line. The condition maps perfectly well; a Parlance node holds one authored string, so carrying this needs the sentence split at the brace, and the pieces either side are fragments rather than beats. | Yes: write it as two whole lines under a `{cond:` block. |
| 12 | **A choice list with no narration line to host it** — options that open a container, or follow a line that is itself declared loss. | Yes: one line of narration before them. |
| 12 | **Conditional narration immediately before a choice list.** That line would have to host the choices, and `showIf` and `choices` are mutually exclusive. | Yes: swap the order, or add a line. |
| 4 | **Conditional narration as the last beat** of the conversation — `showIf` and `isEnd` are mutually exclusive too. | Yes: a line after it, or a divert onwards. |
| 1 | **Variable text** — `{\|I rattle my fingers on the field table.\|}`, a sequence Ink picks between. A node holds one authored string. | No. |

Also reported in `unmapped` without costing a line: 41 expression assignments
(`~ lower(forceful)` — function calls the effect vocabulary cannot make), 37 glue
markers, 6 `CONST` declarations, 5 conditional diverts, and the tunnel below.

**The largest loss class in the spec's survey is gone.** `NODE_CONDITIONS_SPEC.md`
measured this story at ~20% of narration lines under a condition — 126 instances,
every one of them lost before `DialogueNode.showIf` existed. 78 of them now come
across as real gates, including each `- else:` branch under the negation of its
`if`. What remains conditional-shaped is the 25 inline alternatives and the 12+4
positional cases above, which are a different problem: the guard maps, the
*place* does not.

## 3. Open questions for the author

- **The tunnel is carried** — see §4. Of its three call sites only one is an
  unconditional divert; the other two sit inside conditional blocks and are
  declared as conditional diverts in their own right. The one that is carried
  agrees with itself about where the return goes, so it maps to a pair of
  ordinary gotos and nothing is lost.
- **`~ lower(forceful)` / `~ raise(evasive)`** are function calls that adjust a
  counter. Parlance's effect vocabulary is closed and calls nothing, so the
  adjustments are dropped. The `[FLAG]` warnings below are downstream of this.
- **Absolute counter assignment** (`~ x = 3`) has no effect to map to: the
  vocabulary has `adjust_counter` with a delta and nothing else, and the delta
  needs the value at that point in the story.
- **Loops were cut.** An Ink divert may point back into a chain already walked;
  a Parlance `next` ring can never be escaped, so the validator refuses one.

## 4. Validator state

**Zero errors.** 173 warnings:

| n | code | why |
|---|---|---|
| 159 | `REACH` | Nodes a player can no longer reach. See below — eight diverts, not a hundred problems. |
| 8 | `FLAG` | Downstream of the dropped `raise`/`lower` calls: flags set but never read, and one read but never set. |
| 4 | `FLOW` | A node where every choice has a `showIf` — the player may be stuck if none passes. True of the source too, where a read-count fallback covered it. |
| 1 | `LADDER` | The one character's dialogue list is ungated, so its first rung wins forever. |
| 1 | `COND` | A conditional node carries `onEnter` effects, which do not fire when it is skipped (advisory). |

### What a player can reach — 387 of 546

71% of the story is walkable. That number was **43** in the first version of this
import, and the whole difference is one construct read correctly. It is worth
setting out, because the wrong reading produced a confident and completely wrong
conclusion about the format.

**The tunnel is carried, as two ordinary gotos.**
`-> missing_reel -> harris_demands_component` is a call: run that scene, then
continue at `harris_demands_component`. The first version treated it as
unexpressible and ended the branch there — which severed the trunk, because that
call site is the unconditional gather every player passes through on the way out
of the waiting room.

It was never unexpressible. A Parlance `goto` may point **anywhere in the dialogue,
backwards included** — `validate.py` keeps `goto` cycles legal on purpose, because
hub dialogues loop — so the mapping is simply: the call site `goto`s the first node
of `missing_reel`, and `missing_reel`'s `->->` `goto`s the first node of
`harris_demands_component`. Nothing declared, nothing invented, no new construct.

What makes that legal here is that the tunnel has **one** call site the importer can
follow, so its return target is one node id — which is exactly what a `goto` field
holds. The parser works this out now (`tunnelReturns` in the IR) and reports a
tunnel only when its call sites disagree.

**A tunnel that IS loss, and what it costs.** With several call sites wanting
different returns, `->->` must reach a different node per caller and one field
cannot say two things. Even then it is not a format limit: duplicate the scene once
per return target and it works, because the format is perfectly happy with two
copies. What refuses is this importer — a copy puts the author's prose in twice and
the content check counts the second as invented. That is a rule about conversion,
not about Parlance.

### What still severs the story

The remaining 159 unreachable nodes sit behind **eight diverts** pointing at
containers that produce no node at all, every line in them declared loss. Five of
the eight point at `reveal_location_of_component`, a one-line knot whose only line
reads:

> "…I intended to `{ revealedhooperasculprit:pass it to Hooper|dispose of it }`
> once the fuss had died down."

An inline conditional **alternative**. The condition maps perfectly well; what does
not is a sentence that is partly conditional, because a node holds one authored
string. The line cannot be carried, the knot yields nothing, and everything behind
it is cut off.

So what actually gates this story is not control flow. It is the 25 inline
alternatives, each of which an author fixes by rewriting one sentence as two whole
lines under a `{cond:` block — exactly what the declared-loss table already says.

### Two corrections this section has already needed

Both were caused by reasoning about the manifest instead of walking the graph, and
both are why reachability is now a pinned figure in
`tooling/tests/test_importer_examples.py`:

1. The first draft blamed **conditional diverts** and put the count at 23. Eighteen
   of those were choice gates, which map to `choice.showIf` and `goto` perfectly.
2. The second blamed **the tunnel**, and concluded from it that the format needed a
   returning jump. The tunnel was carryable all along, by a backward `goto`. What
   the format would gain from a returning jump is the ability to express an
   *ambiguous* tunnel without duplicating prose — a far narrower claim, and not one
   this story establishes.

## 5. What was NOT checked

The content check compares player-facing strings. **It does not verify that the
graph means what the Ink meant** — that a divert landed on the right container,
that a gather converged where the weave said, or that a choice gates on the right
flag. Structure is the importer's judgment and the author's review.

Specifically unverified here:

- **The weave.** 338 options and 95 gathers were reconstructed from marker levels
  and the parser's `gathersTo`. Nothing checks that a branch rejoins where inkle
  intended.
- **One dialogue and one character**, both derived mechanically. Whether that is
  how an author would organise the story is an editorial question nobody has
  answered.
- **Bracket-less choices echo in Ink and do not in Parlance.** The words survive
  as `choice.text`, so the content check converges, but the player reads one
  fewer beat per choice. A reading difference, not lost text.

## 6. How the mapping was done

By script — [`import.py`](import.py), on top of
[`../build_ink_example.py`](../build_ink_example.py) — rather than by hand. The
`ink-import` skill has a model do the mapping, and at 63 containers and ~1,000
units that is neither reliable nor reproducible.

The script reads every player-facing string from the parser's IR and copies it
byte for byte. It never composes a string, fills an optional field, or invents an
id: node ids come from container titles, choice ids from option text, variable ids
from `VAR` names. `progression.json` is the one file with nothing to derive from —
Ink says nothing about skill progression — so it is written at the schema's
defaults.

## 7. What this import taught the parser

Worth recording, because it is the argument for doing worked imports at all.
Running a real story through `parse_ink.py` for the first time found eight defects
that the hand-written fixture could not, every one of which silently corrupted or
lost prose:

1. A line *beginning* with an inline `{cond: …}` was read as a conditional-block
   opener. The block never closed, and **230 lines inherited a guard they did not
   have**.
2. `- { teacup:` — a gather that also opens a block — was read as a gather whose
   text was `{ teacup:`, putting a line of prose in the manifest that nobody
   wrote, and parsing the block's body unguarded.
3. `- -` (spaced gather markers) counted as one level, which put ten labelled
   gathers out of reach of every divert pointing at them.
4. **Labels were not parsed at all.** 42 of the story's divert targets are
   labelled choices and gathers; every one read as a dangling reference.
5. `-> a -> b` was read as a tunnel plus prose, putting the container name
   `harris_demands_component` in the manifest as a line of dialogue.
6. A divert inside a conditional block was taken unconditionally.
7. Glue was stripped on one content path out of four, so a glued gather reached
   the manifest and the project differing by the one declared rewrite — which the
   content check reads as a line invented AND a line lost.
8. Orphan-body detection used the `parent` link, which records the *previous
   marker* — so the option after an unmappable one was treated as its child.
   Three choices were killed for standing next to a read-count gate.

Six of the eight were caught by `residue` or by the content check refusing to
converge. Two — the conditional divert and the orphan-body cascade — were found
only by reading the output.
