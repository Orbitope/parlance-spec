# Import report — Cyberharcèlement

Source: two Yarn Spinner files, ~10,400 words. See [`SOURCE.md`](SOURCE.md) for
provenance and licence.

## 1. Verdict and counts

**`STOP converged`.** Nothing lost, nothing invented, no guard altered, no
validator error.

| | source | output |
|---|---|---|
| narration lines carried | 544 | 544 |
| options carried | 95 | 95 |
| lines under a `showIf` | — | 40 |
| dialogues | 96 Yarn nodes | 43 |
| characters | — | 17 |
| declared loss | 101 units | — |

Reproduce both halves from this directory:

```bash
python3 import.py
```

```bash
python3 ../../lib/parse_yarn.py episode1.yarn --emit manifest > /tmp/m1.json && python3 ../../lib/parse_yarn.py episode2.yarn --emit manifest > /tmp/m2.json && python3 ../../lib/check.py --root project --manifest /tmp/m1.json --manifest /tmp/m2.json --reset
```

The second command re-derives the yardstick from the vendored source and compares
the project against it. It is the whole claim of this example: you do not have to
believe that no prose was rewritten, because the check refuses to converge if any
was.

## 2. Declared loss — 101 units

Lead with this, because it is the part an author has to decide about. Every one
is reported with its source line in the manifest's `unmapped`.

| n | what | can the author fix it? |
|---|---|---|
| 40 | **Guarded on a function call** — `visited("Chat1")`, `hasMessage("Proof3")`, `visitedAllNodeOptions()`. A Parlance condition compares registered state against a literal and calls nothing; there is no read-count condition at all. | Only by restructuring: set a flag where the visit happens and gate on the flag. |
| 24 | **Conditional narration as the last beat of a conversation.** The node would need `showIf` and `isEnd` together, which the validator refuses — a player who fails the gate would have nowhere to go. | Yes: one line after it, or a jump onwards. |
| 17 | **Body of a choice that is itself unmappable**, so it can never be reached. | Follows from the two rows below it. |
| 12 | **A choice list with no narration line to host it** — options directly after another option block. A Parlance choice hangs off a node and every node needs text. | Yes: one line of narration before them. |
| 8 | **Conditional narration immediately before a choice list.** That line would have to host the choices, and `showIf` and `choices` are mutually exclusive. | Yes: swap the order, or add a line. |

Four of the five are ordering, not expressiveness — a line moved or added in the
source makes them importable. The first is not: read counts are a real gap
between what Yarn can test and what Parlance can.

**The single biggest gain is invisible here, because it no longer happens.** 40
guarded lines came across as `node.showIf`, including every `<<else>>` branch
under the negation of its `<<if>>`. Before `DialogueNode.showIf` all of those
were declared loss too.

## 3. Open questions for the author

- **A trailing `<<set>>`** with no line after it is attached to the preceding
  node's `onEnter`, so it fires as that line is entered rather than after it. No
  case in this story depends on the difference, but it is an approximation.
- **`<<set $score to 0>>`** — an absolute assignment to a counter has no Parlance
  effect: the vocabulary has `adjust_counter` with a delta and nothing else.
  Computing the delta needs the value at that point in the story, which is not
  knowable statically, so these are dropped rather than guessed. The `[FLAG]`
  warnings below are downstream of this.
- **Three jumps go nowhere** — to `PreBedroom3` and `Sms6aQ`, which exist but
  whose every line is declared loss. Those branches end where the jump was.
- **One `next` loop was cut**: `TestTitle` jumps to itself. Yarn allows it; a
  Parlance `next` ring can never be escaped, so the validator refuses one.

## 4. Validator state

**Zero errors.** 163 warnings, none of them a defect in the conversion:

| n | code | why |
|---|---|---|
| 98 | `REACH` | Nodes reachable only through `addMessage` / `addNodeOption` — custom Yarn commands driving the game's own inbox UI. Parlance has no equivalent, so those scenes are in the project but nothing routes to them. |
| 59 | `LADDER` | A character's dialogues are ordered but ungated, because the source never gave a condition. The first rung wins forever. Real, and not something to paper over with an invented gate. |
| 4 | `FLAG` | Downstream of the dropped absolute-counter and function-call gates: `didsharebad` and `didsharegood` are read but never set. |
| 2 | `TEXT` | `bg` and `time` are set by the story and never interpolated into a line — they drive the game's backdrop, not its prose. |

The `FLAG` warnings are true signals, not noise. They say the imported project
has gates that can never open, which is exactly what dropping their setters means.

## 5. What was NOT checked

The content check compares player-facing strings. **It does not verify that the
graph means what the Yarn meant** — that a jump landed on the right node, that a
choice gates on the right flag, or that the scenes are grouped into dialogues the
way an author would group them. Structure is the importer's judgment and the
author's review.

Specifically unverified here:

- **43 dialogues from 96 Yarn nodes**, grouped by `<<jump>>` connectivity. That is
  the rule the skill states, and it is mechanical; whether those are the right
  *scenes* is an editorial question nobody has answered.
- **17 characters**, one per distinct speaker name. `You`, `Narrator` and the game's
  own sentinel lines become characters like anyone else.
- **Ladder order** within each character, taken as source order.

## 6. How the mapping was done

By script — [`import.py`](import.py), on top of
[`../build_yarn_example.py`](../build_yarn_example.py) — rather than by hand. The
`yarn-import` skill has a model do the mapping, and at 96 nodes that is neither
reliable nor reproducible. The decisions encoded there are the ones the skill's
mapping table names.

The script reads every player-facing string from the parser's IR and copies it
byte for byte. It never composes a string, fills an optional field, or invents an
id: node ids come from Yarn node titles, choice ids from option text, character
ids from speaker names, variable ids from variable names. `progression.json` is
the one file with nothing to derive from — Yarn says nothing about skill
progression — so it is written at the schema's defaults.
