---
name: yarn-import
description: Migrate a Yarn Spinner story into a Parlance project — parse deterministically, map the structure, then converge against the reference validator and a content-preservation check until the import is clean or the gate stops you. Use when someone wants to move a Yarn/Yarn Spinner project into Parlance, or to evaluate how much of an existing Yarn story the format can carry. Never rewrites, paraphrases, or invents prose; anything Yarn can express and Parlance cannot is reported to the author, not papered over.
---

# Yarn → Parlance import

Moves a story a human already wrote from one serialization to another. It is a
conversion, not an authoring task, and the difference is load-bearing:

**Nothing in this skill writes prose.** Not a line, not a summary, not a
`dialogueStyle`, not a placeholder. Every player-facing string in the output must
have come from the source file byte for byte, and `check.py` enforces that
mechanically rather than trusting you to remember it.

The failure this is built against is not laziness, it is helpfulness. The cheapest
way to silence "flag read but never set" is to invent a setter. The cheapest way to
fill a `summary` field is to write one. The cheapest way to fix a line that does not
quite fit a node is to reword it. Each is a small, reasonable-looking act that turns
a migration into a rewrite the author never agreed to.

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
python3 lib/parse_yarn.py story.yarn --emit ir       > ir.json
python3 lib/parse_yarn.py story.yarn --emit manifest > manifest.json
```

`ir.json` is what you map from: nodes, items in order with indentation, speakers,
commands, jumps, variables. `manifest.json` is the contract the check verifies
against — every line and option in the source, plus the declared rewrites.

Two fields there are answers, not raw material. `variableKinds` is each variable's
Parlance kind as DERIVED from what the story does with it — register the variables
that way rather than deciding yourself. And a unit's `showIf` is its guard, already
translated into a Parlance condition with the branch negations worked out; copy it
onto the node or choice verbatim.

Read `ir.unmapped` first. It lists Yarn constructs with no Parlance equivalent, and
it is the spine of your final report.

### 2. Map

**A Yarn node is not a Parlance dialogue.** This is the mapping decision that
matters most and the one most likely to be got wrong. Parlance's `goto` is
within-dialogue only, so a set of Yarn nodes connected by `<<jump>>` must become
**one** dialogue with the jumps as `goto` targets. Split into separate dialogues only
where the Yarn story has genuinely disconnected components, or where a jump crosses
into what is clearly a different scene entered by its own gate.

| Yarn | Parlance |
|---|---|
| connected jump component | one dialogue |
| node title | node id prefix within that dialogue; keep the source title in `title` |
| `Speaker: text` | node `text` + `speakerId` |
| consecutive lines | separate nodes chained with `next` — never merged |
| `-> option` | a `choice` |
| `<<jump X>>` | `goto` the node that starts X |
| `<<set $v to true>>` | `effects: [{type: set_flag, ...}]` |
| `<<set $v to 3>>` | `adjust_counter` — a numeric variable is a counter, not a flag |
| `<<if $v>>` around an **option** | `choice.showIf` |
| `<<if $v>>` around a **line** | one node + `node.showIf` |
| `<<elseif>>` / `<<else>>` | one node + `showIf` per line; each branch carries the NEGATION of the branches above it |
| `<<declare>>` / any `$var` | an entry in `variables.json` |

**Never merge a back-and-forth into one node.** One node per speaker, chained by
`next`. Merging is the most common way an import quietly loses the rhythm of a scene
while passing every count-based check.

**Never invent an id.** Derive every id from the source: node titles, speaker names,
variable names. If the source gives you no name for something, that is a question for
the author, not a naming opportunity.

**Never fill an optional field.** `summary`, `description`, `dialogueStyle`,
`archetype` and friends stay absent. The author writes them or they stay empty.

#### Conditional narration, and the one that will tempt you

Yarn guards any line with `<<if>>`, and `parse_yarn.py` maps those onto `node.showIf`
— **it has already done the work**. Read `unit.showIf` in the manifest and write it
onto the node. Do not re-derive the condition from the source yourself, and in
particular do not write the `if`'s guard onto an `<<else>>` branch:

> An `<<else>>` (or a later `<<elseif>>`) carries the NEGATION of every branch above
> it. Yarn writes the alternative without restating the condition, so the tempting
> mapping gives both branches the same guard — and then the player reads two lines
> where the author wrote one. No line is missing and none is invented.

`check.py` compares the conditions in the output against the manifest and reports
`condition_mismatch` when they disagree, in either direction. It is the only defect
class the string comparison cannot see, which is why it is checked rather than trusted.

A guarded node needs `next`, and may carry neither `choices` nor `isEnd`
(validator rule `COND`) — a conditional node is interstitial narration.

What is still declared loss is narrower, and the parser says which each time. The two
you will actually meet:

- **A guard on a variable the story never assigns.** Its kind cannot be derived, and a
  number is truthy in Yarn too, so reading it as a flag would silently change when the
  line shows. Register the variable in the source or accept the loss — do not guess.
- **A guarded line immediately before an option block.** That line would have to be the
  node hosting those choices, and `showIf` and `choices` are mutually exclusive.

For those, do **not** wrap the line in a choice to make it fit — that fabricates a
decision the player never made and puts a phantom entry in their history. Carry them
into the report so the author can decide. Expect a downstream validator warning too:
dropping the line often orphans the flag it read, which surfaces as
`[FLAG] ... set but never read`. That warning is a true signal, not noise.

### 3. Check, and let it decide

```bash
python3 lib/check.py --root <project> --manifest manifest.json --reset   # first pass
python3 lib/check.py --root <project> --manifest manifest.json           # each pass after
```

It runs the reference validator and a content-preservation check over the same
output, and returns one verdict:

| Verdict | Exit | What you do |
|---|---|---|
| `STOP converged` | 0 | Done. Write the report. |
| `CONTINUE` | 1 | Repair what it listed, run it again. |
| `STOP no-progress` | 2 | Your last pass did not reduce defects. Stop; report what is left. |
| `STOP cap` | 2 | Iteration cap. Stop; report what is left. |
| `STOP invented` | 2 | **Hard stop.** The output contains prose not in the source. |
| source not accounted for | 2 | **Hard stop, and not yours to fix.** The PARSER dropped words before the manifest was written. Report it; do not hand-map around it. |

**The script owns the stopping decision, not you.** The cap and the
strictly-decreasing-defects rule live in `check.py` precisely so that a loop cannot
talk itself into one more pass. Do not re-run with `--reset` to clear a `no-progress`
or `cap` verdict; resetting a loop you have not repaired is how a bounded loop becomes
an unbounded one.

The last row is the one that will not look like your problem, and is not. `check.py`
prints the offending source lines and the words that reached nothing, then refuses to
run at all. The repair is a fix to the parser — mapping the missing prose by hand
would put text in the project that the manifest cannot vouch for, which is precisely
the shape of an invented line.

`STOP invented` is never retried. A further pass cannot un-invent a line. Show the
author the exact strings and where they landed.

### 4. What you may repair in the loop

Only structural defects:

- dangling `goto`/`next`/`entry` ids, missing nodes, unregistered flags
- a variable registered with the wrong kind (flag vs counter)
- ladder/entry wiring so the dialogue is reachable
- schema-shape errors (a required field with a structural value, e.g. `entry`)

Never repair a defect by writing prose, inventing an id, or altering a source line.
If a validator finding can only be silenced that way, it is a question for the
author. Put it in the report and leave it failing.

## The report

Every import ends with a written report, converged or not:

1. **Verdict and counts** — lines and options in, lines and options out.
2. **Declared loss** — everything in `unmapped` and `missing_declared`, each with the
   Yarn construct, the source line number, and why Parlance cannot carry it. This is
   the most valuable section; lead with it if it is non-empty.
3. **Open questions** — anything you could not map without guessing.
4. **Validator state** — remaining errors and warnings, with the ones caused by
   declared loss called out as such.
5. **What was NOT checked** — the content check compares player-facing strings. It
   does not verify that your graph shape means what the Yarn meant. Say so.

A clean import with three declared losses is a good outcome, honestly reported. An
import that converged because the awkward lines were quietly reworded is a failure
that looks like a success, which is why `check.py` refuses to let it happen.
