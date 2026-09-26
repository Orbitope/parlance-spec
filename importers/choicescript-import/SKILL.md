---
name: choicescript-import
description: Migrate a ChoiceScript game (startup.txt and its scene files) into a Parlance project — parse it deterministically into an explicit graph, map the registry and scene grouping, then converge against the reference validator and a content-preservation check until the import is clean or the gate stops you. Use when someone wants to move a ChoiceScript game into Parlance, or to evaluate how much of one the format can carry. Never rewrites, paraphrases, or invents prose; anything ChoiceScript can express and Parlance cannot is reported to the author, not papered over.
---

# ChoiceScript → Parlance import

Moves a game a human already wrote from one serialization to another. It is a
conversion, not an authoring task, and the difference is load-bearing:

**Nothing in this skill writes prose.** Not a line, not a summary, not a
placeholder. Every player-facing string in the output must have come from the
source files byte for byte, and `check.py` enforces that mechanically rather than
trusting you to remember it.

The failure this is built against is not laziness, it is helpfulness. The cheapest
way to silence "flag read but never set" is to invent a setter; the cheapest way to
carry a `*stat_chart` is to write lines describing it. Each turns a migration into a
rewrite the author never agreed to.

## Ask for the scenes directory

A ChoiceScript game is `startup.txt` plus one `.txt` per scene, usually under
`web/mygame/scenes/`. The parser starts at `startup.txt`, follows `*scene_list`
and every `*goto_scene`, and reads each scene it names.

**Check the licence of what you are handed.** ChoiceScript itself is under the
ChoiceScript License, which forbids commercial use of "code written for use with
the ChoiceScript interpreter". A game's own author can license their scenes as they
like, but an import of a game you do not own is a question for its author first.

## The pipeline

```
parse (deterministic)  →  map (your judgment)  →  check (deterministic)  →  repair
                                                        ↑                      │
                                                        └──────────────────────┘
                                                   the loop, bounded by check.py
```

### 1. Parse

```bash
python3 lib/parse_choicescript.py path/to/scenes --emit ir       > ir.json
python3 lib/parse_choicescript.py path/to/scenes --emit manifest > manifest.json
```

ChoiceScript's structure is INDENTATION and its flow FALLS THROUGH: the line after
an `*if` block runs whether or not the block did, a `*fake_choice` option's body
rejoins the text below the menu, `*finish` moves to the next scene in
`*scene_list`. None of that is written down as an edge — so the parser builds the
graph itself, exactly, and `ir.nodes` IS the dialogue's node list: ids derived
from scene and line (`n_startup_22`, `c_keeper_4`), every `next`, `goto`,
`showIf`, `whenLocked` and `onEnter` already decided. Do not re-derive control
flow a script derived exactly; spend your judgment on the report.

Also answers, not raw material: `variableKinds` and `defaults` (from `*create` /
`*temp` literals and the `*set`s the game makes), `engineWritten` (`*input_text`
targets — register them `writtenBy: "engine"`), `onceFlags` (see below), and
`entry`. Read `ir.unmapped` first: it is the spine of your report.

### 2. Map

What is left is small, and deliberate:

| ChoiceScript | Parlance |
|---|---|
| the whole game | ONE dialogue — `*goto_scene` and `*finish` cross scene files, and a `goto` is within-dialogue only |
| a prose line | a node; consecutive lines chained with `next` — never merged |
| `*choice` / `*fake_choice`, `#option` | a node with `choices`; the line just above the menu becomes that node's `text` |
| `*if (c) #option`, an `*if` block around options | `choice.showIf` |
| `*selectable_if (c) #option` | `choice.showIf` + `whenLocked: "show"` — shown greyed, never selectable |
| `*hide_reuse` / `*disable_reuse` | the COOKBOOK one-shot recipe: a flag per option (`reuse_<scene>_<line>`, in `onceFlags`), set by the choice, gating it — `whenLocked: "show"` for disable |
| `*label` / `*goto` / `*goto_scene` / `*finish` | edges; `*finish` → the first node of the next scene in `*scene_list` |
| `*ending`, or the end of the last scene | `isEnd` (a menu whose option ends the game is `isEnd` too) |
| `*if` / `*elseif` / `*else` whose bodies only narrate and set state | `node.showIf` on each beat; later branches under the NEGATION of every branch above |
| `*set v true` / `*set v +2` / `*set v -1` / `*set v "text"` | `set_flag` / `adjust_counter` / `set_text`, on the node that fires when the source's `*set` would |
| `*create v 50` | a registry entry, default 50 |
| `*page_break Text`, `*finish Text` | a text-less node whose one choice is the button text |
| bare `*page_break`, `*line_break`, `*comment` | nothing — presentation |
| `*image f.png`, `*sound f.mp3` | an `engine` effect |
| `${name}` for a text variable | `{name}` — the one declared rewrite, `${` → `{` |

**Never merge lines, never invent an id, never fill an optional field.**

### 3. Check, and let it decide

```bash
python3 lib/check.py --root <project> --manifest manifest.json --reset   # first pass
python3 lib/check.py --root <project> --manifest manifest.json           # each pass after
```

One manifest covers every scene file; its units and residue carry their `file`.

| Verdict | Exit | What you do |
|---|---|---|
| `STOP converged` | 0 | Done. Write the report. |
| `CONTINUE` | 1 | Repair what it listed, run it again. |
| `STOP no-progress` / `STOP cap` | 2 | Stop; report what is left. |
| `STOP invented` | 2 | **Hard stop.** The output contains prose not in the source. |
| source not accounted for | 2 | **Hard stop, and not yours to fix.** The PARSER dropped words. Report it. |

### 4. What you may repair in the loop

Only structural defects — dangling ids, unregistered variables, a wrong kind,
schema-shape errors. Never by writing prose, inventing an id, or altering a line.

### What does NOT map

Everything here is reported, never approximated.

| ChoiceScript | Why Parlance cannot carry it |
|---|---|
| fairmath, `*set v %+10` | proportional to the distance from 0/100; `adjust_counter` adds a fixed delta, and approximating it changes every later stat test |
| an absolute counter assignment, `*set v 10`; an expression | the vocabulary has `adjust_counter` with a delta, and effects write literals |
| an `*if` whose branch jumps (`*goto`, `*finish`, a `*choice` inside it) | a jump chosen by a condition. The whole block is declared — this is ChoiceScript's commonest idiom (`*if (x)` / text / `*finish`), and the report should say how much it cost |
| a `*set` with no node that fires exactly when it would (e.g. first thing in a scene, straight before an `*if` that reads it) | Parlance fires effects on arrival at a node; attaching it elsewhere would change what a test reads |
| `*gosub`, `*gosub_scene`, `*return` | a call that returns; a Parlance edge does not come back |
| `*rand` | chosen at play time |
| `$!{v}`, `@{v a\|b}`, `${v}` of a number or flag | computed text; only a text variable fills a `{placeholder}` |
| `*input_text`, `*input_number` | player input (the variable is registered `writtenBy: "engine"`) |
| `*achievement`, `*achieve`, `*stat_chart` | engine UI; their text is declared with them |
| `*temp` counter | re-initialised on each scene run; only its first value (the default) carries |
| `*if` + `*selectable_if` on one option | one gate per choice, locked or hidden, not both |

## The report

Every import ends with a written report, converged or not: verdict and counts
(with **reachable nodes, by walking the graph**), declared loss first, open
questions, validator state, and what was not checked — the content check compares
strings, not whether the graph means what the game meant.

## Fixture

`../fixtures/lighthouse_stair/` (three scenes) and
`../fixtures/lighthouse_stair_imported/`, the output of
`../examples/build_choicescript_example.py`. It carries a `*choice` with a plain,
a `*selectable_if`, a `*hide_reuse` and an `*if`-gated option, an
`*if`/`*elseif`/`*else` that must map to negations, a `*fake_choice` that rejoins,
`*page_break` and `*finish` buttons, `${name}` interpolation, an `*image`, and the
declared paths: fairmath, an `*if` that jumps, `${}` of a number, `*rand`,
`*gosub`/`*return`, `*achievement`/`*achieve`.

```bash
python3 lib/parse_choicescript.py ../fixtures/lighthouse_stair --emit manifest > /tmp/m.json
python3 lib/check.py --root ../fixtures/lighthouse_stair_imported --manifest /tmp/m.json --reset
```

## No worked migration yet

There is no ChoiceScript story under `../examples/`. The obvious candidate, the
sample game bundled with ChoiceScript, is under the ChoiceScript License (no
commercial use — not terms this repository can redistribute under), and no game
source was found under a licence that clearly permits redistribution. The parser
has been run against that sample locally, where it converges; it is not
vendored, and its numbers are not quoted here. An example is only vendored under a
licence that clearly permits it, so until one turns up the fixture is the only
evidence — and a fixture exercises the paths somebody thought of, not the ones a
real game finds.
