# Import report — Aesthetics Over Plot

Source: one Twee file, 45 passages (40 of them story, the rest metadata, a
script, a stylesheet and a sidebar), SugarCube 2. See [`SOURCE.md`](SOURCE.md)
for provenance and licence.

## 1. Verdict and counts

**`STOP converged`.** Nothing lost, nothing invented, no guard altered, no
validator error.

| | source | output |
|---|---|---|
| narration lines carried | 333 | 333 |
| links carried | 62 | 62 |
| lines and links under a `showIf` | — | 22 |
| state changes carried (`set_text`) | — | 20 |
| declared rewrites | `$dress`, `$talking`, `$password` → `{…}` | — |
| dialogues | 40 passages | 1 |
| declared loss | 11 units (39 `unmapped` entries) | — |
| nodes a player can reach | — | **333 of 333** |

Reproduce both halves from this directory:

```bash
python3 import.py
```

```bash
python3 ../../lib/parse_sugarcube.py aesthetics.tw --emit manifest > /tmp/m.json && python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
```

The second command re-derives the yardstick from the vendored source and compares
the project against it. You do not have to believe that no prose was rewritten:
the check refuses to converge if any was. The only difference it permits is the
three declared sigil swaps — `$dress` in a line becomes `{dress}`, Parlance's
spelling of the same interpolation — and it accepts those by shape, nothing wider.

## 2. Declared loss — 11 units

| n | what | can the author fix it? |
|---|---|---|
| 7 | **The `StoryCaption` sidebar** — "You are wearing a $dress", the book you read. SugarCube renders it beside every passage; Parlance has no persistent chrome. | No: that is the engine's HUD, not a line. |
| 2 | **Gated on `$password.indexOf('abachan') > -1`** — a function call. Both the `<<if>>` and the `<<else>>` line go, because the else carries the negation of a guard that does not map. | Only by setting a flag where the name is entered — which is the engine's job here, since the name is typed. |
| 2 | **`<<button "restart">><<run UI.restart()>><</button>>`** — a link that runs code in place. A Parlance choice leads somewhere. | Yes: end the dialogue there and let the game offer restart. |

Also in `unmapped`, costing no line: 12 `<<notify>>` wrappers (the words inside
them — "Achievement Unlocked!" and friends — are carried as ordinary beats), the
`<<textbox>>` the player types their name into (`$password` is registered
`writtenBy: "engine"`), two `<<run UI.restart()>>` calls, and one expression
assignment, `$password to $password.toLowerCase()`.

### The loss the walk cannot see: 13 absolute counter assignments

`[[Suit->Step2][$dress to "suit"]]` maps — `$dress` is text. `[[Way of the
ronin|step3][$book to 1]]` does not. This story uses **seven** variables as enums
(`$book`, `$w`, `$chicken`, `$witty`, `$donk`, `$dignity`, `$flirt`): assigned a
literal number, tested with `is`. Parlance's effect vocabulary has
`adjust_counter` with a delta and nothing else, so each of the 13 assignments is
declared — and the **22 guarded units** that test them carry their `showIf`
faithfully and can never see it change. At play time `$book is 4` is never true
and `$dignity is 0` always is.

That is invisible to both the content check (every word is present) and the
reachability walk (every node is reachable), which is why it gets its own
heading. It is the single largest cost of this migration, and it is a gap in the
format rather than the importer: a `set_counter` effect — or a flag per enum
value — would carry all of it. An author can do the latter today by hand.

## 3. What a player can reach — 333 of 333

100%. Every passage in this story moves forward by a link or a button with a
literal destination, and none of those links sits under a guard that failed to
map, so nothing is severed. That is the SugarCube counterpart of the Twine
finding in [`not-weird-queer`](../not-weird-queer/REPORT.md): what breaks a Twine
import is a guard on the WAY FORWARD, and this story guards only narration.

Read it with §2's last heading: reachable is not the same as reached. A walk
treats a `showIf` as passable; the runtime does not.

## 4. Open questions for the author

- **The enums.** §2. A `set_counter` would carry them; so would four flags for
  `$book`. Which one is an authoring decision, not a conversion.
- **Defaults.** A variable never set in `StoryInit` is registered at its kind's
  zero (`0`, `""`). SugarCube leaves it undefined, and `undefined is 0` is false
  there — so `<<if $dignity is 0>>` before any assignment reads differently.
  This story has no `StoryInit`.
- **One dialogue from 40 passages**, grouped by link connectivity. Whether those
  are the right scenes is an editorial question nobody has answered.

## 5. Validator state

**Zero errors.** 2 warnings:

| n | code | why |
|---|---|---|
| 1 | `FLOW` | `Apologize` offers one link, `[[wall]]`, inside `<<elseif $dignity is 1>>`. In the source the other branch ends in a restart button; here that button is declared (§2) and `$dignity` can never become 1 (§2's last heading), so this node is where the imported story actually stops. |
| 1 | `TEXT` | `$talking` is only ever interpolated in the declared sidebar. |

## 6. What was NOT checked

The content check compares player-facing strings. **It does not verify that the
graph means what the SugarCube meant.** Structure is the importer's judgment and
the author's review.

Specifically unverified here:

- **Passage-to-scene shape.** SugarCube renders a passage at once; Parlance makes
  several beats with the links on the last. This story numbers its menus —
  `1.[[Suit->Step2]]: No doubts about it…` — and the `1.` and the text after the
  link come across as beats of their own, in source order, because joining them
  to the link would change the choice text.
- **Markup is carried verbatim.** `<h2>`, `<s>`, `<u>`, `> ` quote markers stay in
  the line. A line that is ONLY tags (`<center>`, `</div>`) is layout, not a beat.
- **No characters.** SugarCube names no speaker.

## 7. What this import taught the parser

It converged on the first run, which says less about the parser than about the
story: every construct in it was already on the list. Two decisions were made
because of it rather than found wrong by it:

1. **`//` is not a comment in SugarCube** — it is italics. The shared residue
   module blanked from `//` to end of line for every format; for SugarCube (and
   ChoiceScript) it now blanks only real comments (`/* */`, `/% %/`, `<!-- -->`),
   or an italicised word would have taken the rest of its line out of the count.
2. **A naked `$name` needed a rewrite longer than the cap.** `$password` →
   `{password}` is nine characters, and `check.py` caps a rewrite at eight so
   that a phrase cannot be laundered into another. A sigil swap is now accepted
   by SHAPE — `$id` to `{id}` with the id the source name lowercased — and every
   other rewrite keeps the cap.
