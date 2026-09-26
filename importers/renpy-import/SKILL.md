---
name: renpy-import
description: Migrate a Ren'Py visual novel script (.rpy) into a Parlance project — parse it deterministically, map the structure, then converge against the reference validator and a content-preservation check until the import is clean or the gate stops you. Use when someone wants to move a Ren'Py story into Parlance, or to evaluate how much of an existing Ren'Py script the format can carry. Never rewrites, paraphrases, or invents prose; anything Ren'Py can express and Parlance cannot is reported to the author, not papered over.
---

# Ren'Py → Parlance import

Moves a story a human already wrote from one serialization to another. It is a
conversion, not an authoring task, and the difference is load-bearing:

**Nothing in this skill writes prose.** Not a line, not a summary, not a
`dialogueStyle`, not a placeholder. Every player-facing string in the output must
have come from the source file byte for byte, and `check.py` enforces that
mechanically rather than trusting you to remember it.

The failure this is built against is not laziness, it is helpfulness. The cheapest
way to silence "flag read but never set" is to invent a setter. The cheapest way
to fill a `summary` field is to write one. Each is a small, reasonable-looking act
that turns a migration into a rewrite the author never agreed to.

## Ask for the scripts, not the build

A Ren'Py game's story is in `game/*.rpy`. The compiled `.rpyc` files and the
`.rpa` archives are build output; do not decompile them — the author has the
sources, and a decompiler's output is not their text. Parse each `.rpy` that
holds story (usually `script.rpy` and whatever the author split it into);
`options.rpy`, `screens.rpy` and `gui.rpy` are configuration and can be skipped.

## The pipeline

```
parse (deterministic)  →  map (your judgment)  →  check (deterministic)  →  repair
                                                        ↑                      │
                                                        └──────────────────────┘
                                                   the loop, bounded by check.py
```

You do the mapping. You never do the transcription, and you never decide when to
stop.

### 1. Parse

```bash
python3 lib/parse_renpy.py script.rpy --emit ir       > ir.json
python3 lib/parse_renpy.py script.rpy --emit manifest > manifest.json
```

`ir.json` is what you map from: labels in file order, each a flat list of items
(`line`, `menu` with its caption and choices, `jump`, `return`), the effects
already attached to the item that carries them, `characters` (each `define`d
Character's name, `_()` removed), `variableKinds` and `defaults` from `default`
statements, and `start`.

Two fields there are answers, not raw material. `variableKinds` is each
variable's Parlance kind as DERIVED from the literals the script assigns — register
the variables that way rather than deciding yourself. And an item's `showIf` is
its guard, already translated into a Parlance condition with the `elif`/`else`
negations worked out; copy it onto the node or choice verbatim.

Read `ir.unmapped` first. It lists the Ren'Py constructs with no Parlance
equivalent, and it is the spine of your final report.

### 2. Map

| Ren'Py | Parlance |
|---|---|
| labels joined by `jump` or fall-through | one dialogue |
| `label start:` | the dialogue's `entry` |
| a say statement `e "…"` / `"…"` | a node; `speakerId` is the Character's variable (`e`), narration has none |
| `define e = Character(_("Eileen"))` | a character `{id: "e", name: "Eileen"}` |
| consecutive say statements | nodes chained with `next` — never merged |
| `menu:` | a node with `choices`; its caption say statement (if any) is the node's `text`, otherwise the node has no `text` (0.15) |
| `"Choice" if cond:` | a choice with `showIf` (and `whenLocked: "show"` when the script sets `config.menu_include_disabled = True`) |
| a choice block with no `jump` | its last node's `next` is whatever follows the menu — Ren'Py falls through |
| a label with no `jump`/`return` at its end | its last node's `next` is the next label's first node — Ren'Py falls through |
| `jump label` | `next` / `goto` the label's first node |
| `return` (from `start`'s flow) | `isEnd: true` |
| `if` / `elif` / `else` around say statements | one node per line + `node.showIf` (the `elif`/`else` guards carry the NEGATION of every branch above) |
| `default x = False` / `1` / `"a"` | a variable, kind flag / counter / text, with that default |
| `$ x = True`, `$ x = "a"` | `set_flag`, `set_text` |
| `$ x += 1`, `$ x -= 1` | `adjust_counter` |
| `show`, `scene`, `hide`, `play`, `stop`, `queue`, `with`, `pause`, `window`, `voice`, `nvl`, `camera` | an `engine` effect: the statement's keyword as `command`, its literal tokens as `args` |
| `"… [name] …"` where `name` is a text variable | `{name}` — the one declared rewrite |
| `{b}`, `{i}`, `{w}` and the other text tags | removed from the line and reported; the words inside stay |
| `_("…")` | the string, wrapper removed |

**Effects ride on the next line in the same scope.** The parser has already put
each one there — on the node's `onEnter`, or on a choice when it opens the choice's
block. An effect that has nothing after it to ride on is declared, not moved: moving
it past a gated line, or onto one, changes when it fires.

**Never merge consecutive lines into one node.** One line, one beat.

**Never invent an id.** Derive every id from the source: label names, Character
variable names, variable names. If the source gives you no name for something,
that is a question for the author, not a naming opportunity.

**Never fill an optional field.** `summary`, `description`, `dialogueStyle`,
`archetype` and friends stay absent. The author writes them or they stay empty.

#### The `else` branch, and the one that will tempt you

> An `else:` block carries the NEGATION of every branch above it. Ren'Py writes
> neither negation down, so the tempting mapping gives both branches the same
> guard — and then the player reads two lines where the author wrote one. No line
> is missing and none is invented.

`check.py` compares the conditions in the output against the manifest and reports
`condition_mismatch` when they disagree, in either direction.

A guarded line that ENDS the conversation or hosts choices hides only its line
(0.15) and still fires its `onEnter`. If such a line carries effects from inside
its `if`, the gate would stop holding them back; the example builder refuses that
shape rather than emitting it.

### 3. Check, and let it decide

```bash
python3 lib/check.py --root <project> --manifest manifest.json --reset   # first pass
python3 lib/check.py --root <project> --manifest manifest.json           # each pass after
```

A story split across several `.rpy` files is parsed per file and checked with one
`--manifest` per file against the one project.

| Verdict | Exit | What you do |
|---|---|---|
| `STOP converged` | 0 | Done. Write the report. |
| `CONTINUE` | 1 | Repair what it listed, run it again. |
| `STOP no-progress` | 2 | Your last pass did not reduce defects. Stop; report what is left. |
| `STOP cap` | 2 | Iteration cap. Stop; report what is left. |
| `STOP invented` | 2 | **Hard stop.** The output contains prose not in the source. |
| source not accounted for | 2 | **Hard stop, and not yours to fix.** The PARSER dropped words before the manifest was written. Report it; do not hand-map around it. |

**The script owns the stopping decision, not you.** Do not re-run with `--reset`
to clear a `no-progress` or `cap` verdict.

The manifest declares two rewrites, `[`→`{` and `]`→`}`, for interpolation. The
parser only lets a line through where every bracket in it names a registered TEXT
variable, so the swap is token for token. Anything else that differs between source
and output is a defect.

### 4. What you may repair in the loop

Only structural defects: dangling `goto`/`next`/`entry` ids, missing nodes,
unregistered variables, a variable with the wrong kind, offer/entry wiring,
schema-shape errors. Never repair a defect by writing prose, inventing an id, or
altering a source line.

### What does NOT map

Everything here is reported, never approximated.

| Ren'Py | Why Parlance cannot carry it |
|---|---|
| `call label` / `return` as a subroutine | no cross-dialogue call/return (decided); the flow continues after the call as if the label had not run |
| a `jump` or `return` inside an `if` | a destination chosen by a condition; `next`/`goto` are unconditional |
| a `menu` inside an `if` | a gated node with choices still offers them; the menu cannot be gated as a whole |
| `python:`, `init python:`, and any `$` line that is not an assignment of a literal | the effect vocabulary is closed and calls nothing |
| `$ x = 3` on a number | `adjust_counter` takes a delta; there is no absolute set |
| `[x]` where `x` is a number or an expression, `[x!u]`, `[[` | a placeholder names a TEXT variable and nothing else |
| `screen`, `transform`, `style`, `image`, `init`, `translate` blocks | presentation and configuration, not story |
| `Character(..., color=…, image=…)` arguments | a character carries a name; presentation is the engine's |
| image attributes on a say statement (`e happy "…"`), `id`, `(…)` arguments | expression changes and engine options with no field |
| `jump expression …`, `show expression …` | a destination or image computed at play time |
| an `if` on a variable the script never assigns a literal | its kind cannot be derived |

## The report

Every import ends with a written report, converged or not:

1. **Verdict and counts** — lines and choices in, lines and choices out, and **how
   many nodes a player can actually reach**. Walk the graph from the dialogue's
   entry; do not infer it from the manifest. A single `jump` inside an `if` can
   cut off everything behind it, and the content check will converge happily
   while it does.
2. **Declared loss** — everything in `unmapped` and `missing_declared`, each with
   the construct, the source line number, and why. Lead with it.
3. **Open questions** — anything you could not map without guessing.
4. **Validator state** — remaining errors and warnings.
5. **What was NOT checked** — the content check compares player-facing strings. It
   does not verify that your graph means what the script meant, and it does not
   compare effects. Say so.

## Fixture

`../fixtures/night_market.rpy` and `../fixtures/night_market_imported/` are a small
script and the project a faithful import of it produces. It carries an
`if`/`elif`/`else` chain whose branches must map to a guard and its NEGATIONS, a
gated menu choice under `config.menu_include_disabled`, a text-variable
interpolation beside a counter one that cannot be carried, a text tag, staging
statements, and the declared-loss path: a `call`, an `init python:` block, a `jump`
inside an `if`, and an absolute counter assignment.

```bash
python3 lib/parse_renpy.py ../fixtures/night_market.rpy --emit manifest > /tmp/m.json
python3 lib/check.py --root ../fixtures/night_market_imported --manifest /tmp/m.json --reset
```

## A worked migration

`../examples/the-question/` is Ren'Py's own sample game, *The Question* (MIT),
imported end to end with the script beside the result. It is the easy case — its
report says so and says why.
