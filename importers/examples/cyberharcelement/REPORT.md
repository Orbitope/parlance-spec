# Import report — Cyberharcèlement

Source: two Yarn Spinner files, ~10,400 words. See [`SOURCE.md`](SOURCE.md) for
provenance and licence.

## 1. Verdict and counts

**`STOP converged`.** Nothing lost, nothing invented, no guard altered, no
validator error.

| | source | output |
|---|---|---|
| narration lines carried | 591 | 591 |
| options carried | 110 | 110 |
| lines under a `showIf` | — | 47 |
| dialogues | 96 Yarn nodes | 47 |
| characters | — | 17 |
| declared loss | 37 units | — |
| nodes a player can reach | — | **516 of 596** |

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

## 2. Declared loss — 37 units

Lead with this, because it is the part an author has to decide about. Every one
is reported with its source line in the manifest's `unmapped`.

| n | what | can the author fix it? |
|---|---|---|
| 37 | **Guarded on a function call** — `visited("Chat1")`, `hasMessage("Proof3")`, `visitedAllNodeOptions()`. A Parlance condition compares registered state against a literal and calls nothing; there is no read-count condition at all. | Only by restructuring: set a flag where the visit happens and gate on the flag. |
That is the only row left, and it is not ordering: read counts are a real gap
between what Yarn can test and what Parlance can.

**0.15 removed the positional losses.** Four rows this table used to carry (64 units) —
a guarded line immediately before a choice list, a guarded line as the last beat,
and a choice list with no narration line to host it, and the unreachable bodies behind those — are gone. Parlance 0.15
lets `showIf` on a node with `choices` or `isEnd` hide only the LINE (the choices
still show, the conversation still ends), and lets a node carry choices with no
`text` at all. The importer now emits those shapes as the source wrote them, so
none of it is declared, and none of it needed a line the source did not contain.

**Custom commands are carried, not declared (0.15).** The story drives its own
UI through 98 custom Yarn commands — `<<addMessage Email1>>`,
`<<addNodeOption Chat1>>`, `<<addForegroundImage student-group-1 30 440>>` and
nine other names. Before Parlance had an `engine` effect every one was listed
in `unmapped` as a command with no equivalent. Now **71** come across as
`{"type": "engine", "command": "add_message", "args": ["Email1"]}`. The name is
snake_cased because the validator requires that (`addMessage` becomes
`add_message`, and nothing else about it changes), and the args are typed as
the source wrote them. They sit in the node's `onEnter`, or on a choice, in
source order (five more than with the 0.14 node shapes: a line or option
block that used to be declared for its position is now emitted, so the
commands beside it have a node to ride on). The
other **27** have no line after them in their Yarn node to
ride on: mostly nodes made only of commands, such as `Bedroom1`'s
`addMessage`/`addNodeOption` block, and one under a declared-loss choice.
`import.py` names each of those in a `note:` line with its source line. None of
the 98 was ever a line of prose, so the declared-loss count above does not move.
The manifest's `unmapped` list shrinks from 202 entries to 42 — the engine
mapping and the 0.15 node shapes together.

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

**Zero errors.** 83 warnings, none of them a defect in the conversion:

| n | code | why |
|---|---|---|
| 80 | `REACH` | Nodes reachable only through `addMessage` / `addNodeOption` — custom Yarn commands driving the game's own inbox UI. They are now carried as `engine` effects (`add_message`, `add_node_option`), but an engine command is opaque to the runtime by design: it hands the name to the game and draws no edge, so those scenes are in the project and nothing in the data routes to them. |
| 1 | `FLAG` | Downstream of the dropped function-call gates: `didshowbackpackvideo` is set but its only reader is a `visited(...)` gate. (Before 0.15 three more were downstream of lines that were declared for position alone; they are carried now.) |
| 2 | `TEXT` | `bg` and `time` are set by the story and never interpolated into a line — they drive the game's backdrop, not its prose. |

The source gave the characters' dialogues no conditions. The importer marks one dialogue
per speaker — the first the source presents — with a bare `offer` for that character, and
leaves the rest reachable only through the graph, so there is no finding — where the old
character ladder reported all 59 as first-rung-wins-forever `LADDER` warnings.

The `FLAG` warnings are true signals, not noise. They say the imported project
has gates that can never open, which is exactly what dropping their setters means.

## 5. What was NOT checked

The content check compares player-facing strings. **It does not verify that the
graph means what the Yarn meant** — that a jump landed on the right node, that a
choice gates on the right flag, or that the scenes are grouped into dialogues the
way an author would group them. Structure is the importer's judgment and the
author's review.

Specifically unverified here:

- **47 dialogues from 96 Yarn nodes**, grouped by `<<jump>>` connectivity. That is
  the rule the skill states, and it is mechanical; whether those are the right
  *scenes* is an editorial question nobody has answered.
- **17 characters**, one per distinct speaker name. `You`, `Narrator` and the game's
  own sentinel lines become characters like anyone else.
- **Which dialogue each character offers.** The importer offers one per speaker (the first
  the source presents, no gate, no priority tier); every other dialogue of that speaker is
  reached by the jumps the source wrote. Whether that is the scene the character should
  open with is an editorial call.

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
