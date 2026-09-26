---
name: arcweave-import
description: Migrate an Arcweave project (its "Export → JSON" project file) into a Parlance project — parse it deterministically, map the structure, then converge against the reference validator and a content-preservation check until the import is clean or the gate stops you. Use when someone wants to move an Arcweave story into Parlance, or to evaluate how much of an existing Arcweave project the format can carry. Never rewrites, paraphrases, or invents prose; anything Arcweave can express and Parlance cannot is reported to the author, not papered over.
---

# Arcweave → Parlance import

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

## Ask for the JSON export

In Arcweave, **Export → JSON** writes the whole project as one file: `boards`,
`elements`, `connections`, `branches`, `conditions`, `jumpers`, `components`,
`attributes`, `variables`, `notes`, `assets` and `startingElement`, each collection
keyed by id. That file is the input. Not a screenshot, not the web view, not a
game-engine export that has already been through a plugin.

**The parser is strict about what it knows and loud about the rest.** Its reading
of the export format was reconstructed from the published format and the engine
plugins that consume it, not validated against every version Arcweave has shipped.
The design takes that seriously: every string in the file is accounted for (see
*Residue* below), so a field this parser has never heard of — the case where an
export version moved something — comes back as a **parser gap**, never as a
quietly thinner project.

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
python3 lib/parse_arcweave.py project.json --emit ir       > ir.json
python3 lib/parse_arcweave.py project.json --emit manifest > manifest.json
```

`ir.json` is what you map from: `elements` in export order, each with its `items`
(one per paragraph, effects already attached) and its `routes` (where its outputs
lead, with branches and jumpers already resolved); `characters`; `variableKinds`
and `defaults`; and `start` — the export's `startingElement`.

Two things there are answers, not raw material. `variableKinds` comes from the
TYPES Arcweave declares (`boolean` → flag, `integer` → counter, `string` → text);
nothing about a kind is guessed. And a unit's or route's `showIf` is its guard,
already translated into a Parlance condition with the `elseif`/`else` negations
worked out; copy it onto the node or choice verbatim.

Read `ir.unmapped` first. It is the spine of your final report.

### 2. Map

| Arcweave | Parlance |
|---|---|
| elements joined by connections | one dialogue |
| `startingElement` | the dialogue's `entry` |
| element title | node id prefix (the title labels the canvas; it is not shown to the player) |
| a paragraph of element content | a node; consecutive paragraphs chained with `next` — never merged |
| `<br>` inside a paragraph | two nodes: two lines |
| one unlabelled output | `next` on the element's last node |
| labelled outputs | `choices` on the element's last node; the label is the choice text |
| an element with outputs and no text | a text-less choice node (0.15) |
| no outputs | `isEnd: true` |
| a jumper | the element it points at |
| a LABELLED connection into a branch | one choice per arm, each with that arm's `showIf` — its own test AND the negation of every arm above it. The label appears once per arm in the data and once per state to the player, since the arms are exclusive |
| Arcscript `if` / `elseif` / `else` / `endif` around paragraphs | `node.showIf` on each paragraph, negations included |
| `x = true` on a boolean | `set_flag` |
| `x = "…"` on a string | `set_text` |
| `x += n`, `x -= n` on an integer | `adjust_counter` |
| a variable | a registered variable, kind from its type, `default` from its value |
| a component attached to an element, alone | that element's lines' `speakerId`, and a character `{id, name}` from the component's name |

**Markup is not prose.** Element content and labels are HTML; a unit's text is
the text between the tags with entities decoded (`&amp;` → `&`) — every
character a character of the source, nothing added. Inline formatting and
component mentions are declared; the words inside them stay required.

**Effects ride on the next paragraph in the same branch.** Unguarded effects at
the end of an element ride on its last node: Arcweave runs an element's script on
entering it, before its outputs are offered, and a Parlance node's `onEnter` fires
before its choices do. A guarded effect with no paragraph after it in its branch is
declared, not moved.

**Never invent an id.** Node ids come from element titles, choice ids from labels,
character ids from component names. **Never fill an optional field.** Component
attributes stay declared rather than becoming a `description` — they are the
author's data, and choosing a field for them is a decision for the author.

#### The `else` arm, and the one that will tempt you

> An `else` condition — in a branch, or in Arcscript around a paragraph — carries
> the NEGATION of every arm above it. Arcweave writes neither negation down, so the
> tempting mapping gives the `else` choice no gate at all, and then the player
> sees both routes whenever the first test holds. No line is missing and none is
> invented.

`check.py` compares the conditions in the output against the manifest and reports
`condition_mismatch` when they disagree, in either direction.

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
| source not accounted for | 2 | **Hard stop, and not yours to fix.** The PARSER dropped words before the manifest was written — or met a field it does not know. Report it; do not hand-map around it. |

**The script owns the stopping decision, not you.** No rewrites are declared for
Arcweave: anything that differs between source and output is a defect.

#### Residue, for a JSON source

A JSON export has no lines worth reporting against — an element's whole content
is one line of the file. So the residue check runs over a PROJECTION: every string
leaf of the export, one per line, in document order, and a unit's `lineno` is its
leaf's position there (`path` names the leaf, e.g. `elements/<id>/content`). Every
leaf is in the projection. Ids and enum-like settings (`theme`, `type`,
`sourceType` …) are recognised as structure; everything else must reach a unit, a
declared loss, or a statement the parser understood.

### 4. What you may repair in the loop

Only structural defects: dangling `goto`/`next`/`entry` ids, missing nodes,
unregistered variables, a variable with the wrong kind, offer/entry wiring,
schema-shape errors. Never repair a defect by writing prose, inventing an id, or
altering a source string.

### What does NOT map

Everything here is reported, never approximated.

| Arcweave | Why Parlance cannot carry it |
|---|---|
| a branch reached by an UNLABELLED connection | the engine picks the route without the player; `next`/`goto` name one node, `showIf` gates display, not destination. Labelling the connection makes it importable |
| an unlabelled output beside labelled ones | a bare option; a Parlance choice needs text, and none is invented |
| a labelled connection into a branch whose arm is also labelled | two texts for one choice |
| `visits()`, `random()`, `roll()`, `show()`, `reset()`, `resetAll()`, `abs()` and every other function | the effect and condition vocabularies are closed and call nothing; there is no visit count |
| `x = 3` on an integer | `adjust_counter` takes a delta; there is no absolute set |
| an assignment from an expression (`x = y + 1`) | effects write literals or add a literal delta |
| a `float` variable | a counter is an integer, and rounding would be a rewrite |
| a condition comparing two variables, or a string | a condition compares one registered variable against a literal; there is no text condition |
| component attributes | no field holds them verbatim |
| board notes | an annotation on the canvas, attached to no line |
| assets (covers, images, audio) | media, not data |
| inline formatting, mention links | Parlance text is plain |
| several components on one element | which one speaks is not in the data; the lines are narration |

## The report

Every import ends with a written report, converged or not:

1. **Verdict and counts** — paragraphs and labels in, lines and choices out, and
   **how many nodes a player can actually reach**. Walk the graph from the
   dialogue's entry; do not infer it from the manifest. One unlabelled branch on
   the trunk cuts off everything behind it, and the content check will converge
   happily while it does.
2. **Declared loss** — everything in `unmapped` and `missing_declared`, each with
   the construct, its `path`, and why. Lead with it.
3. **Open questions** — anything you could not map without guessing; in
   particular whether a single attached component really is the speaker.
4. **Validator state** — remaining errors and warnings.
5. **What was NOT checked** — the content check compares player-facing strings. It
   does not verify that your graph means what the Arcweave board meant, and it
   does not compare effects. Say so.

## Fixture

`../fixtures/harbour_watch.json` and `../fixtures/harbour_watch_imported/` are a
small hand-made export and the project a faithful import of it produces. It
carries a labelled connection into an `if`/`else` branch (two gated choices, the
second under the negation), Arcscript `if`/`else` around paragraphs, a jumper, a
mention, an entity, and the declared-loss path: an unlabelled branch gated on
`visits()`, a `random()` assignment, a component attribute and a board note.

```bash
python3 lib/parse_arcweave.py ../fixtures/harbour_watch.json --emit manifest > /tmp/m.json
python3 lib/check.py --root ../fixtures/harbour_watch_imported --manifest /tmp/m.json --reset
```

## No worked migration yet

The other importers each ship a real third-party story under `../examples/`.
This one does not: no Arcweave project exported under a licence that clearly
permits redistribution was obtainable when it was written. The fixture above is
ours and says so. A real export, clearly licensed, is the example worth adding —
and, going by every other format here, the one that will find what the fixture
could not.
