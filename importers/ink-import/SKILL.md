---
name: ink-import
description: Migrate an Ink (inkle) story into a Parlance project — parse deterministically, map the structure, then converge against the reference validator and a content-preservation check until the import is clean or the gate stops you. Use when someone wants to move an Ink story into Parlance, or to evaluate how much of an existing Ink story the format can carry. Never rewrites, paraphrases, or invents prose; anything Ink can express and Parlance cannot is reported to the author, not papered over.
---

# Ink → Parlance import

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

Ink raises the stakes on the second half of the contract. Yarn is a serialization
with a little logic bolted on; Ink is a small programming language, and a language
has features a data format simply does not have. **Expect a long declared-loss
section, and lead with it.** An Ink import that reports nothing lost is either a very
plain story or a dishonest report.

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
python3 lib/parse_ink.py story.ink --emit ir       > ir.json
python3 lib/parse_ink.py story.ink --emit manifest > manifest.json
```

`ir.json` is what you map from: containers (knots and stitches) in source order,
items in order with their weave level, speakers, gates, effects, diverts, and the
gather each choice falls into. `manifest.json` is the contract the check verifies
against — every line and option in the source, plus the declared rewrites.

Two fields there are answers, not raw material. `variableKinds` is each variable's
Parlance kind as DERIVED from its `VAR` declaration and the assignments the story
makes — register the variables that way rather than deciding yourself. And a unit's
`showIf` is its guard, already translated into a Parlance condition with the branch
negations worked out; copy it onto the node or choice verbatim.

Read `ir.unmapped` first. It lists Ink constructs with no Parlance equivalent, and
it is the spine of your final report.

Two fields in the IR do most of the mapping work for you:

- **`level`** — Ink's indentation is cosmetic. Nesting is the count of `*`/`+`/`-`
  markers, and that is what `level` holds. Never infer structure from whitespace.
- **`gathersTo`** — the index of the gather a choice falls into when its body runs
  off the end. That is the `next` target for the last node of the body.

`ir.declarations` holds `VAR`/`CONST`/`LIST`/`EXTERNAL`/`INCLUDE` with the kind
derived from the initialiser: `true`/`false` → flag, an integer → counter, a quoted
string → text.

### 2. Map

**An Ink knot is not a Parlance dialogue.** This is the mapping decision that
matters most and the one most likely to be got wrong. Parlance's `goto` is
within-dialogue only, so a set of knots connected by diverts must become **one**
dialogue with the diverts as `goto`/`next` targets. Split into separate dialogues
only where the story has genuinely disconnected components, or where a divert
crosses into what is clearly a different scene entered by its own gate.

| Ink | Parlance |
|---|---|
| connected divert component | one dialogue |
| `=== knot ===` | node id prefix within that dialogue — not a dialogue of its own |
| `= stitch` | a further id prefix; still the same dialogue as its knot |
| `Speaker: text` | node `text` + `speakerId` |
| a line with no `Speaker:` | node `text`, no `speakerId` — narration |
| consecutive lines | separate nodes chained with `next` — never merged |
| `* text` / `+ text` | a `choice` on the node carrying the line above it |
| `* front[choice-only]after` | `choice.text` is `front + choice-only`; `front + after` is a node the choice `goto`s |
| `* text` with no brackets | `choice.text` only — but Ink **echoes** it and Parlance does not; see below |
| `-> knot` / `-> knot.stitch` | `goto`/`next` the first node of that container |
| `-> END` / `-> DONE` | `isEnd: true` on the node that reaches it |
| a gather `-` | not a node of its own: it is the `next` target the bodies above it converge on |
| a gather with text (`- text`) | an ordinary node, and the convergence point |
| `* {flag} text` | `choice.showIf` |
| `{flag: line}` around a **line** | one node + `node.showIf` |
| `{ cond:` … `- else:` … `}` blocks | one node + `showIf` per line; the else branch gets the NEGATED condition |
| `~ v = true` | `effects: [{type: set_flag, …}]` on the choice whose body holds it |
| `~ v = v + 1`, `~ v++`, `~ v += 2` | `adjust_counter` — a numeric variable is a counter, not a flag |
| `~ v = "…"` | `set_text`, with the variable registered `kind: "text"` |
| `VAR v = false` / `= 0` / `= "…"` | an entry in `variables.json`, kind flag / counter / text |
| `CONST N = 2` | inline the value at its use sites; **not** a variable registry entry |
| global `# tag`, knot `# tag` | `dialogue.tags` |
| `<>` (glue) | dropped; both lines survive as separate nodes |

### The echo divergence, and why it is reported rather than fixed

In Ink, a bracket-less `* Text` choice prints "Text" into the story after it is
taken. That is exactly why the `[]` form exists — to suppress the echo. Parlance does
not echo: `chooseChoice` "carries no player-facing strings"
(`tooling/RUNTIME_CONTRACT.md`), so the chosen text never becomes a story beat.

This is invisible to the content check, and that is the point worth understanding.
The words are still in the project as `choice.text`, so nothing is missing and nothing
is invented — `check.py` converges. What changes is what the player *reads*: one
fewer beat per bracket-less choice.

`parse_ink.py` reports these once per file with a count and line numbers. Do **not**
"fix" it by also emitting the choice text as a narration node: that puts the same
string in the data twice and reads as an importer artefact to a Parlance author. Put
it in the report and let the author decide — accepting it, or rewriting those choices
in Ink's `front[choice-only]after` form so the printed remainder becomes a real line,
are both reasonable and neither is yours to choose.

It is the clearest example of the limit `IMPORTERS.md` states: the check compares
strings, not meaning. A converged import can still read differently from its source.

**Never merge a back-and-forth into one node.** One node per speaker, chained by
`next`. Merging is the most common way an import quietly loses the rhythm of a scene
while passing every count-based check.

**Every node needs `text`.** A Parlance node requires it, so a choice list has to
hang off the line that precedes it. Where Ink puts a choice list immediately after
another choice's bracket-only text, there is no line to hang it on — that is a
question for the author, not a licence to write a linking sentence.

**Never invent an id.** Derive every id from the source: knot and stitch names,
variable names, and — for choices, which Ink does not name — a slug of the choice's
own text, the way the fixture does. If the source gives you no name for something,
that is a question for the author, not a naming opportunity.

**Never fill an optional field.** `summary`, `description`, `dialogueStyle`,
`archetype` and friends stay absent. The author writes them or they stay empty.

#### Conditional narration, and the one that will tempt you

Ink guards any line with `{condition: …}`, inline or as a multi-line block, and
`parse_ink.py` maps those onto `node.showIf` — **it has already done the work**. Read
`unit.showIf` in the manifest and write it onto the node. Do not re-derive the
condition from the source yourself, and in particular do not write the guard onto an
`else` branch:

> An `else` branch carries the NEGATION of every branch above it. Ink writes the
> alternative without restating the condition, so the tempting mapping gives both
> branches the same guard — and then the player reads two lines where the author wrote
> one. No line is missing and none is invented.

`check.py` compares the conditions in the output against the manifest and reports
`condition_mismatch` when they disagree, in either direction. It is the only defect
class the string comparison cannot see, which is why it is checked rather than trusted.

A guarded node needs `next`, and may carry neither `choices` nor `isEnd`
(validator rule `COND`) — a conditional node is interstitial narration.

What is still declared loss is narrower, and the parser says which each time: a guard
on a variable whose kind the source never reveals, a read count, a `LIST`, a
comparison between two variables, and a line whose guard would have to sit on the node
hosting a choice list. For those, do **not** wrap the line in a choice to make it fit —
that fabricates a decision the player never made and puts a phantom entry in their
history. Carry them into the report so the author can decide. Expect a downstream
validator warning too: dropping the line often orphans the flag it read, which
surfaces as `[FLAG] … set but never read`. That warning is a true signal, not noise.

### What does NOT map

Everything here is reported, never approximated. The parser marks each one; you
carry it into the report with its source line.

| Ink | Why Parlance cannot carry it |
|---|---|
| a guard on a variable the source never assigns | its Parlance kind (flag / counter / text) cannot be derived, and reading an untyped name as a flag would change when the line shows |
| a guard comparing two variables, or containing arithmetic | a condition compares one registered variable against a literal |
| a guard on a text variable | there is no text-valued condition in the vocabulary |
| conditional narration immediately before a choice list | the line would have to host those choices, and a node may not carry `showIf` and `choices` together (`COND`) |
| variable text `{a\|b\|c}`, cycles `{&…}`, shuffles `{~…}`, once `{!…}` | a node holds one authored string, chosen by the author, not by visit count |
| read counts as conditions `{knot > 1}` | there is no visit counter in the condition vocabulary, and importing the choice ungated would change when the player may take it |
| tunnels `-> knot ->` and returns `->->` | `goto` does not return. Faithful **only** where the tunnel has a single call site and can be inlined; with two call sites the return target is genuinely ambiguous and the author has to choose |
| threads `<- knot` | a thread weaves a second flow into the current one; a Parlance dialogue has one point of control. Content reachable only through a thread is dropped and reported |
| `LIST` | variables are flags, counters and text slots — there is no set-valued type to hold or test |
| `EXTERNAL` functions | Parlance data calls nothing; its effect vocabulary is closed |
| parameterised knots `=== knot(x) ===` | a `goto` carries no arguments, so the parameters have nowhere to go |
| functions, `~ return`, arithmetic in conditions | there is no expression language — conditions compare a flag, counter, reputation, relationship, skill, item or quest stage against a literal |
| `~ temp v = …` | a temp is scoped to the knot call and has no registry entry to map to |
| once-only `*` choices | a Parlance choice does not disappear once taken. Reproducing that needs a flag plus a `showIf` — a variable the source never declared, so **do not invent one**. Reported once for the whole file rather than per choice |
| glue `<>` | a node is a discrete beat; the join is lost, though both lines survive |
| per-line tags `# tag` | a dialogue carries `tags`; a node does not |
| `CONST` | Parlance registers mutable state only. Inline the value; do not declare a counter the story never writes |
| `INCLUDE` | parse and import each file, then reconcile the manifests |

Sticky `+` choices need no entry: a Parlance choice is sticky by default, so `+` is
the case that maps and `*` is the case that does not.

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

One rewrite is declared for Ink, and only one: the glue marker `<>` is removed from
the line it sits in. Interpolation needs none — Ink writes `{var}` and so does
Parlance. Anything else that differs between source and output is a defect, not a
formatting difference.

### 4. What you may repair in the loop

Only structural defects:

- dangling `goto`/`next`/`entry` ids, missing nodes, unregistered variables
- a variable registered with the wrong kind (flag vs counter vs text)
- ladder/entry wiring so the dialogue is reachable
- schema-shape errors (a required field with a structural value, e.g. `entry`)

Never repair a defect by writing prose, inventing an id, or altering a source line.
If a validator finding can only be silenced that way, it is a question for the
author. Put it in the report and leave it failing.

## The report

Every import ends with a written report, converged or not:

1. **Verdict and counts** — lines and options in, lines and options out.
2. **Declared loss** — everything in `unmapped` and `missing_declared`, each with the
   Ink construct, the source line number, and why Parlance cannot carry it. This is
   the most valuable section; with Ink it will rarely be empty, so lead with it.
3. **Open questions** — anything you could not map without guessing. A tunnel with
   more than one call site and a choice list with no line to hang on both belong here.
4. **Validator state** — remaining errors and warnings, with the ones caused by
   declared loss called out as such.
5. **What was NOT checked** — the content check compares player-facing strings. It
   does not verify that your graph shape means what the Ink meant: that a divert
   landed on the right container, that a gather converged where the weave said, or
   that a choice gates on the right flag. Structure is your judgment and the author's
   review. Say so.

A clean import with a dozen declared losses is a good outcome, honestly reported. An
import that converged because the awkward lines were quietly reworded is a failure
that looks like a success, which is why `check.py` refuses to let it happen.

## Fixture

`../fixtures/ferry_landing.ink` and `../fixtures/ferry_landing_imported/` are a small
story and the project a faithful import of it produces. The story deliberately
contains a tunnel, a thread, a `LIST`, an `EXTERNAL`, a `CONST`, glue, a line tag,
variable text, a read-count gate and both forms of conditional narration — the inline
`{cond: text}` and a `{ cond: … - else: … }` block whose two branches must map to a
guard and its negation — so the
declared-loss path is exercised rather than assumed.

```bash
python3 lib/parse_ink.py ../fixtures/ferry_landing.ink --emit manifest > /tmp/m.json
python3 lib/check.py --root ../fixtures/ferry_landing_imported --manifest /tmp/m.json --reset
```

That prints `STOP converged` with four entries under `missing_declared` and none
under `missing_unexplained`. Delete a line from a copy of the project and it returns
`CONTINUE` naming the string; reword one and it returns `STOP invented` naming the
string and the node it landed in.
