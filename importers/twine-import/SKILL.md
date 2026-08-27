---
name: twine-import
description: Migrate a Twine story written in Harlowe into a Parlance project — parse the published .html (or Twee) deterministically, map the structure, then converge against the reference validator and a content-preservation check until the import is clean or the gate stops you. Use when someone wants to move a Twine/Harlowe project into Parlance, or to evaluate how much of an existing Twine story the format can carry. Never rewrites, paraphrases, or invents prose; anything Harlowe can express and Parlance cannot is reported to the author, not papered over.
---

# Twine (Harlowe) → Parlance import

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

## Ask for the published `.html`

That is the file a Twine story always has — Twine produces it, and it is what
people distribute. `.twee` only exists if the author uses `tweego` or exports it,
so asking for Twee first turns most migrations into a favour you need from the
author. Both work; lead with the HTML.

Its prose is escaped, and decoding that is not a rewrite — escaping is something
Twine did on the way out, and decoding returns the author's bytes exactly. The
parser does it on read.

**Check the format before anything else.** A compiled story declares it:

```bash
grep -o 'format="[^"]*"' story.html | head -1
```

Twine is a tool, not a language. SugarCube writes `<<set $x to 1>>` and Harlowe
writes `(set: $x to 1)`; they share no syntax. `parse_twine.py` refuses a story
that is not Harlowe, because parsing one with the other's parser does not fail —
it quietly produces a project whose prose is full of unparsed macros, and no
downstream check would call that wrong.

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
python3 lib/parse_twine.py story.html --emit ir       > ir.json
python3 lib/parse_twine.py story.html --emit manifest > manifest.json
```

(`.twee` works at the same commands, where the author has it.)

`ir.json` is what you map from: passages in source order, items in order, macros
with their arguments, links with their targets, and `start` — the passage Twee's
`StoryData` names as the story's entry, which is **not** necessarily the first one
in the file.

Two more fields there are answers, not raw material. `variableKinds` is each
variable's Parlance kind as DERIVED from the `(set:)` calls the story makes —
register the variables that way rather than deciding yourself. And a unit's
`showIf` is its guard, already translated into a Parlance condition with the hook
negations worked out; copy it onto the node or choice verbatim.

Read `ir.unmapped` first. It lists the Harlowe constructs with no Parlance
equivalent, and it is the spine of your final report.

### 2. Map

**A passage is a SCENE, not a node.** Harlowe renders a whole passage at once and
shows every link in it together, so a passage of six lines and three links is one
screen with three ways out. In Parlance that becomes six nodes chained by `next`,
with all three choices on the last of them.

| Harlowe | Parlance |
|---|---|
| link-connected passages | one dialogue |
| passage name | node id prefix within that dialogue |
| a line of a passage | a node; consecutive lines chained with `next` — never merged |
| `[[Text\|Target]]`, `[[Text->Target]]`, `[[Target<-Text]]` | a `choice` on the LAST node of the passage, `goto` the target's first node |
| `[[Target]]` | the same, with the target name as the choice text — which is what the player reads |
| `(if: $v)[ … ]` | one node + `node.showIf` per line inside the hook |
| `](else:)[ … ]` | the same, with the NEGATED condition |
| `(if: $v)[ [[link]] ]` | `choice.showIf` |
| `(set: $v to true)` | `effects: [{type: set_flag, …}]` |
| `(set: $v to it + 1)` | `adjust_counter` — `it` is the variable's own value |
| `(set: $v to "…")` | `set_text`, the variable registered `kind: "text"` |
| a passage with no link out | `isEnd: true` on its last node |
| `StoryData`'s `start`, or `<tw-storydata startnode>` | the dialogue's `entry` — **not** the first passage in the file |

**The passage boundary is the one that matters.** Everything in a passage is one
screen to the player, so text that follows a link is still beside it. Attaching
each link where it happens to appear splits a passage's choices across two nodes
and orphans the second — which is a defect the validator will report as
unreachable nodes, and which the content check cannot see at all, since every
string is present.

**Never merge consecutive lines into one node.** One line, one beat. Merging is
the commonest way an import quietly loses the rhythm of a scene while passing
every count-based check.

**Never invent an id.** Derive every id from the source: passage names, link text,
variable names. If the source gives you no name for something, that is a question
for the author, not a naming opportunity.

**Never fill an optional field.** `summary`, `description`, `dialogueStyle`,
`archetype` and friends stay absent. The author writes them or they stay empty.

#### Conditional narration, and the one that will tempt you

Harlowe guards anything with a hook — `(if: $v)[ … ]` — and `parse_twine.py` maps
those onto `node.showIf`. **It has already done the work.** Read `unit.showIf` in
the manifest and write it onto the node. Do not re-derive the condition, and in
particular do not write the `if`'s guard onto an `(else:)` branch:

> An `(else:)` hook carries the NEGATION of every branch above it. Harlowe writes
> `](else:)[` — closing and opening in one gesture, restating nothing — so the
> tempting mapping gives both branches the same guard, and then the player reads
> two lines where the author wrote one. No line is missing and none is invented.

`check.py` compares the conditions in the output against the manifest and reports
`condition_mismatch` when they disagree, in either direction. It is the only
defect class the string comparison cannot see, which is why it is checked rather
than trusted.

A guarded node needs `next`, and may carry neither `choices` nor `isEnd`
(validator rule `COND`) — a conditional node is interstitial narration.

**A hook that is not a conditional still holds prose.** `(text-style:"underline")[…]`,
`(box:)[…]`, `(align:)[…]` style their contents; the macro is declared loss and
the words inside are the author's and stay required.

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

**The script owns the stopping decision, not you.** Do not re-run with `--reset`
to clear a `no-progress` or `cap` verdict.

No rewrites are declared for Twine — not one. Harlowe interpolates `$var` and
Parlance interpolates `{var}`, which is not a token-for-token swap, so a variable
named inside a line stays exactly as the author wrote it and the report says so.
Anything that differs between source and output is a defect, not a formatting
difference.

### 4. What you may repair in the loop

Only structural defects:

- dangling `goto`/`next`/`entry` ids, missing nodes, unregistered variables
- a variable registered with the wrong kind (flag vs counter vs text)
- ladder/entry wiring so the dialogue is reachable
- schema-shape errors (a required field with a structural value, e.g. `entry`)

Never repair a defect by writing prose, inventing an id, or altering a source
line. If a validator finding can only be silenced that way, it is a question for
the author. Put it in the report and leave it failing.

### What does NOT map

Everything here is reported, never approximated.

| Harlowe | Why Parlance cannot carry it |
|---|---|
| a condition comparing two variables (`$luz > $sombra`) | a condition compares one registered variable against a literal |
| a condition on a text variable (`$name is ""`) | there is no text-valued condition in the vocabulary |
| a guard on a variable the story never `(set:)`s | its kind cannot be derived, and reading an untyped name as a flag would change when the line shows |
| `(print:)`, `(display:)` | text computed at play time; a node holds one authored string |
| `(input-box:)`, `(dropdown:)`, `(cycling-link:)` | input widgets — Parlance data collects nothing from the player |
| `(track:)`, `(masteraudio:)` and the rest of HAL | audio; the effect vocabulary is closed and calls nothing |
| `(text-style:)`, `(align:)`, `(box:)`, `(css:)` | presentation. The hook's CONTENTS survive as prose; the styling does not |
| `(random:)`, `(either:)` | chosen at play time rather than by the author |
| `(live:)`, `(after:)`, `(event:)` | time-driven; a Parlance node is advanced by the player |
| `(link-goto:)`, `(goto:)` | flow computed at play time rather than an authored edge |
| a link inside a hook whose guard does not map | the choice would be offered in states the author gated it out of |
| a conditional line immediately before a link | that line would have to host the choices, and `showIf` and `choices` are mutually exclusive (`COND`) |
| a conditional line as the last beat of a passage with no link out | `showIf` and `isEnd` are mutually exclusive too |

## The report

Every import ends with a written report, converged or not:

1. **Verdict and counts** — lines and links in, lines and links out, and **how
   many nodes a player can actually reach**. Walk the graph from the dialogue's
   entry; do not infer it from the manifest. In Twine every forward motion is a
   link, so a single unmappable guard on one link can sever the story — and the
   content check will converge happily while it does.
2. **Declared loss** — everything in `unmapped` and `missing_declared`, each with
   the Harlowe construct, the source line number, and why. Lead with it.
3. **Open questions** — anything you could not map without guessing.
4. **Validator state** — remaining errors and warnings, with the ones caused by
   declared loss called out as such.
5. **What was NOT checked** — the content check compares player-facing strings. It
   does not verify that your graph means what the Twine meant. Say so.

A clean import with a dozen declared losses is a good outcome, honestly reported.
An import that converged because the awkward lines were quietly reworded is a
failure that looks like a success, which is why `check.py` refuses to let it
happen.

## Fixture

`../fixtures/lamp_room.twee` and `../fixtures/lamp_room_imported/` are a small
story and the project a faithful import of it produces. `lamp_room.html` is the
same story compiled, and the suite asserts the two parse to the same units —
that equivalence is what makes reading the published file safe. The story deliberately
contains an `(if:)`/`(else:)` pair whose branches must map to a guard and its
NEGATION, a styling hook holding prose, a `(track:)` call, a `(print:)`, and a
guard on a variable the story never declares — so the declared-loss path is
exercised rather than assumed.

```bash
python3 lib/parse_twine.py ../fixtures/lamp_room.twee --emit manifest > /tmp/m.json
python3 lib/check.py --root ../fixtures/lamp_room_imported --manifest /tmp/m.json --reset
```

That prints `STOP converged` with two entries under `missing_declared` and none
under `missing_unexplained`. Delete a line from a copy of the project and it
returns `CONTINUE` naming the string; reword one and it returns `STOP invented`
naming the string and the node it landed in. Give the `(else:)` branch the same
`showIf` as its `(if:)` and neither of those notices — `condition_mismatch` does.

## A worked migration

`../examples/not-weird-queer/` is a real Twine story (MIT) imported end to end,
with the author's published `.html` beside the result and a report that leads
with what was lost. Read it before starting one of your own — in particular §7,
which lists the five parser defects that story found in a parser that had already
imported a different one cleanly.
