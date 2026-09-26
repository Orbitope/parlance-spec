---
name: sugarcube-import
description: Migrate a Twine story written in SugarCube 2 into a Parlance project — parse the published .html (or Twee) deterministically, map the structure, then converge against the reference validator and a content-preservation check until the import is clean or the gate stops you. Use when someone wants to move a Twine/SugarCube project into Parlance, or to evaluate how much of an existing SugarCube story the format can carry. Never rewrites, paraphrases, or invents prose; anything SugarCube can express and Parlance cannot is reported to the author, not papered over.
---

# Twine (SugarCube) → Parlance import

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

## Ask for the published `.html`, and check the format

The compiled file is what a Twine story always has; `.twee`/`.tw` only exists if
the author uses `tweego` or exports it. Both work. The compiled file declares its
format:

```bash
grep -o 'format="[^"]*"' story.html | head -1
```

`parse_sugarcube.py` refuses a story that declares anything but SugarCube, and
`parse_twine.py` (Harlowe) refuses SugarCube and points here. Twine is a tool, not
a language: the formats share no syntax, and reading one with the other's parser
yields a project full of unparsed macros that no check would call wrong.

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
python3 lib/parse_sugarcube.py story.html --emit ir       > ir.json
python3 lib/parse_sugarcube.py story.html --emit manifest > manifest.json
```

`ir.json` is what you map from: story passages in source order, each with its
`items` (lines, options, commands, gotos) and its `exit`, plus `start` — the
passage StoryData or `startnode` names, else SugarCube's own default, `Start`.

Several fields are answers, not raw material. Copy them; do not re-derive them:

| IR field | what it already decided |
|---|---|
| `variableKinds`, `defaults`, `engineWritten` | each variable's kind from the assignments the story makes; `StoryInit`'s literal assignments as registry defaults; variables an input widget writes (register those `writtenBy: "engine"`) |
| `item.showIf` | the guard, translated, with `<<else>>` and `<<default>>` carrying the NEGATION of every branch above them |
| `item.parlance` | the Parlance effects a `<<set>>`, a link setter, a `<<link>>` body or a custom macro maps to |
| `item.carrier` | which beat's `onEnter` a state change rides (an item index, or `"exit"` for the text-less node holding a linkless passage's choices). `null` means it has none and is declared |
| `passage.exit` | `choices`, `goto` (the passage's last beat gets `next`), or `end` |
| `rewrites` | `$name` → `{name}` for each TEXT variable a line interpolates. Apply them to every string you write, exactly as `check.py` applies them to the source |

Read `ir.unmapped` first. It is the spine of your final report.

### 2. Map

**A passage is a SCENE, not a node** — the same rule as Harlowe. SugarCube renders
a whole passage at once, so its lines become beats chained by `next` and ALL its
links go on the last beat (or on a text-less node, when the passage has links and
no line of its own — legal since 0.15).

| SugarCube | Parlance |
|---|---|
| link-connected passages | one dialogue |
| a line of a passage | a node; consecutive lines chained with `next` — never merged |
| a line that is only HTML tags (`<center>`, `</div>`) | nothing: layout, not a beat |
| `[[Text\|Target]]`, `[[Text->Target]]`, `[[Target<-Text]]`, `[[Target]]` | a `choice` on the passage's last node, `goto` the target's first node |
| `[[Text\|Target][$x to true]]` | the same, with `effects` from `item.parlance` |
| `<<link "Text" "Target">>…<</link>>`, `<<button>>`, or a `<<goto>>` in the body | the same; the body's `<<set>>`s become the choice's `effects` |
| `<<goto "P">>` (unguarded) | the last beat's `next` → P's first node |
| `<<if>>` / `<<elseif>>` / `<<else>>`, `<<switch>>` / `<<case>>` / `<<default>>` | `node.showIf` / `choice.showIf` from the IR |
| `<<set $f to true>>` / `$n += 2` / `$n++` / `$n to $n - 1` / `$t to "…"` | `set_flag` / `adjust_counter` / `set_text`, on the carrier's `onEnter` |
| `<<customWidget "a" 2>>`, `<<audio "x" play>>` — literal args | an `engine` effect, command in snake_case (`custom_widget`) |
| `$name` in a line, `name` a text variable | `{name}` — a declared rewrite |
| a passage with no link out | `isEnd: true` on its last node |

**Never merge consecutive lines, never invent an id, never fill an optional
field.** Derive ids from passage names and link text.

**A state change has one right place.** Parlance fires `onEnter` on arrival; a
guarded beat that is skipped fires nothing; a beat holding choices or ending the
dialogue fires its effects even when its own line is hidden. So the parser picks a
carrier that fires exactly when the source's `<<set>>` would, and declares the
change when there is none. Do not "rescue" a declared one onto a nearby node — it
would fire at another time, and no check can see that.

### 3. Check, and let it decide

```bash
python3 lib/check.py --root <project> --manifest manifest.json --reset   # first pass
python3 lib/check.py --root <project> --manifest manifest.json           # each pass after
```

| Verdict | Exit | What you do |
|---|---|---|
| `STOP converged` | 0 | Done. Write the report. |
| `CONTINUE` | 1 | Repair what it listed, run it again. |
| `STOP no-progress` | 2 | Your last pass did not reduce defects. Stop; report what is left. |
| `STOP cap` | 2 | Iteration cap. Stop; report what is left. |
| `STOP invented` | 2 | **Hard stop.** The output contains prose not in the source. |
| source not accounted for | 2 | **Hard stop, and not yours to fix.** The PARSER dropped words before the manifest was written. Report it; do not hand-map around it. |

**The script owns the stopping decision, not you.**

The only declared rewrites are sigil swaps (`$name` → `{name}`), and `check.py`
accepts them by SHAPE: the id must be the source name lowercased. Anything else
that differs between source and output is a defect.

### 4. What you may repair in the loop

Only structural defects — dangling `goto`/`next`/`entry` ids, unregistered
variables, a wrong kind, reachability wiring, schema-shape errors. Never repair a
defect by writing prose, inventing an id, or altering a source line.

### What does NOT map

Everything here is reported, never approximated.

| SugarCube | Why Parlance cannot carry it |
|---|---|
| an absolute counter assignment (`<<set $n to 3>>` outside `StoryInit`) | the vocabulary has `adjust_counter` with a delta and nothing else |
| an assignment from an expression, a `_temp` variable | an effect writes a literal to a registered, persistent variable |
| a condition on a text variable, two variables, a function (`visited()`, `.includes()`), `def`/`ndef` | a condition compares one registered variable against a literal |
| `<<print>>`, `<<=>>`, `<<include>>`, a naked non-text `$var` or `$obj.prop` | text computed at play time; only a text variable fills a `{placeholder}` |
| `<<textbox>>`, `<<checkbox>>`, `<<cycle>>` and the other input widgets | Parlance data collects nothing from the player |
| `<<run>>`, `<<script>>`, `<<addclass>>`, `<<replace>>`, `<<timed>>`, `<<linkreplace>>` | JavaScript, DOM and time. A container's CONTENTS survive as prose; the macro does not |
| a guarded `<<goto>>`, `<<back>>`, `<<return>>`, a `[[link]]` to `$var` | a jump chosen at play time; a Parlance edge names one node |
| a `<<link>>` with no destination | an in-place action; a choice leads somewhere |
| `StoryCaption`, `StoryMenu`, `PassageHeader`/`Footer`/`Ready`/`Done` | chrome rendered around every passage |
| a `<<widget>>` body | rendered wherever it is invoked (the INVOCATION maps to `engine`) |
| a custom macro with a variable argument | an `engine` command carries literals only |

## The report

Every import ends with a written report, converged or not:

1. **Verdict and counts** — lines and links in and out, and **how many nodes a
   player can actually reach**, by walking the graph from the entry.
2. **Declared loss** — everything in `unmapped` and `missing_declared`, with the
   construct, the source line, and why. Lead with it. Call out separately any
   guard whose variable the import can never change (an enum set only by
   absolute assignment): the walk treats that `showIf` as passable, the runtime
   does not.
3. **Open questions**, 4. **Validator state**, 5. **What was NOT checked** — the
   content check compares strings, not whether the graph means what the story
   meant. Say so.

## Fixture

`../fixtures/cellar_door.twee` (and `cellar_door.html`, the same story compiled)
with `../fixtures/cellar_door_imported/`, which is the output of
`../examples/build_sugarcube_example.py`. It carries an `<<if>>/<<elseif>>/<<else>>`
and a `<<switch>>` whose later branches must map to negations, a link setter, a
`<<link>>` with a body, a text-variable interpolation, a custom widget as an
`engine` effect, and the declared paths: `<<print>>`, `<<textbox>>`, a container
macro, an absolute counter set, a guarded `<<goto>>`, a `_temp`, `<<back>>`, a
sidebar and a widget body.

```bash
python3 lib/parse_sugarcube.py ../fixtures/cellar_door.twee --emit manifest > /tmp/m.json
python3 lib/check.py --root ../fixtures/cellar_door_imported --manifest /tmp/m.json --reset
```

## A worked migration

`../examples/aesthetics-over-plot/` is a real SugarCube game (GPL-3.0) imported
end to end, with the author's `.tw` beside the result. Its report's §2 is the
case for reading a report rather than a verdict: every node reachable, and 22
guarded lines that can never change, because the story uses counters as enums.
