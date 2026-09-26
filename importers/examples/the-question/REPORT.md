# Import report — The Question

Source: one Ren'Py script, 252 lines, 5 labels. See [`SOURCE.md`](SOURCE.md) for
provenance and licence.

## 1. Verdict and counts

**`STOP converged`.** Nothing lost, nothing invented, no guard altered, no
validator error.

| | source | output |
|---|---|---|
| say statements carried (incl. 2 menu captions) | 71 | 71 |
| menu choices carried | 4 | 4 |
| lines under a `showIf` | — | 1 |
| staging statements carried as `engine` effects | 33 | 33 |
| `$` assignments carried as effects | 1 | 1 |
| characters | 2 `define`s | 2 |
| dialogues | 5 labels | 1 |
| declared loss | 0 units | — |
| nodes a player can reach | — | **71 of 71** |

Reproduce both halves from this directory:

```bash
python3 import.py
```

```bash
python3 ../../lib/parse_renpy.py script.rpy --emit manifest > /tmp/m.json && python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
```

The second command re-derives the yardstick from the vendored source and compares
the project against it. It is the whole claim of this example: you do not have to
believe that no prose was rewritten, because the check refuses to converge if any
was.

## 2. Declared loss — 0 units

No line and no choice was lost. Six things were, and none of them is prose:

| n | what | why |
|---|---|---|
| 4 | **Text tags** — `{b}` / `{/b}` around *Good Ending* and *Bad Ending*. | Parlance text is plain. The words inside the tags are carried; the bold is not. |
| 2 | **Character presentation** — `color="#c8ffc8"` and `color="#c8c8ff"`. | A Parlance character carries a name. How the engine draws its name box is not data. |

The staging — `scene bg meadow`, `show sylvie green smile`, `with dissolve`,
`play music "illurock.opus"` — is not lost. Each is a statement-shaped command
with literal arguments, and each rides as a 0.15 `engine` effect on the node it
precedes, in source order: `{"type": "engine", "command": "show", "args":
["sylvie", "green", "smile"]}`. What an engine does with it is the engine's
business, exactly as Ren'Py's is.

## 3. What a player can reach — 71 of 71

All of it. The five labels are joined by `jump`s, so they are one dialogue, and
every node is on a path from `start`.

**Read that as the easy case, not as a benchmark.** The Question is a teaching
sample: two menus, one flag, no `call`, no Python, no conditional jump. It shows
that the ordinary Ren'Py idiom maps one-for-one; it does not show what a large
game built on `call`/`return`, screens and Python costs, and nothing here should
be read as a claim about that. The fixture `fixtures/night_market.rpy` carries
those constructs so the declared-loss path is exercised; a real story that leans
on them would be the example worth adding next.

## 4. Open questions for the author

- **`m` is "Me".** The Question's narrator-protagonist is a defined Character,
  so the import makes it a Parlance character like Sylvie. Whether the player
  should be a character at all in the target game is an editorial question.
- **The two endings are `{b}`-bold in the source** and plain here. If the
  emphasis matters, it has to come back through the engine's presentation of
  `isEnd` nodes, not through the text.

## 5. Validator state

**Zero errors.** 0 warnings.

## 6. What was NOT checked

The content check compares player-facing strings and the conditions on them.
**It does not verify that the graph means what the script meant.** Structure is
the importer's judgment and the author's review.

Specifically unverified here:

- **Effect placement.** A staging statement rides on the NEXT line's node,
  because that is the beat it prepares. Ren'Py runs it at the same point in the
  flow, so the order is the same — but nothing in the check compares effects.
- **Fall-through.** A choice block with no `jump` continues after the menu, and a
  label with no `jump` or `return` continues into the next label. Both are
  Ren'Py's rules, built into the importer; the check sees strings, not edges.
- **Speakers.** Each line's `speakerId` is the `define`d variable it names
  (`s`, `m`), and each character's name is the string in its `Character(...)`
  with the `_()` translation wrapper removed.
