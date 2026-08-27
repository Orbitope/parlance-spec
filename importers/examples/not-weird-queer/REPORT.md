# Import report — Not Weird. Queer

Source: one compiled Twine story, 167 passages, Harlowe. See
[`SOURCE.md`](SOURCE.md) for provenance and licence.

## 1. Verdict and counts

**`STOP converged`.** Nothing lost, nothing invented, no guard altered, no
validator error.

| | source | output |
|---|---|---|
| narration lines carried | 1,003 | 1,003 |
| links carried | 176 | 176 |
| lines under a `showIf` | — | 159 |
| dialogues | 167 passages | 19 |
| declared loss | 182 units | — |
| nodes a player can reach | — | **454 of 1,003** |

Reproduce both halves from this directory:

```bash
python3 import.py
```

```bash
python3 ../../lib/parse_twine.py Not-Weird-Queer-0-0-008.html --emit manifest > /tmp/m.json && python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
```

The second command re-derives the yardstick from the vendored source and compares
the project against it. It is the whole claim of this example: you do not have to
believe that no prose was rewritten, because the check refuses to converge if any
was.

## 2. Declared loss — 182 units

| n | what | can the author fix it? |
|---|---|---|
| 60 | **Gated on a Harlowe keyword, not a variable** — `visits`, how many times this passage has been seen. Parlance has no read-count condition and no clock. | Only by restructuring: set a flag on first arrival and gate on that. |
| 51 | **Gated on a variable whose kind cannot be derived** — the story assigns it from an expression, or assigns it as two different kinds in different places (`$gender` is set to `"male"` in one passage and to `0` in another). Reading it as either would silently change when the line shows. | Yes: keep a variable to one kind. |
| 38 | **Gated on a text variable** — `(if: $name is "Ryan")`. There is no text-valued condition in the Parlance vocabulary at all. | Only by restructuring into a flag. |
| 24 | **Conditional narration hosting a passage's links.** Harlowe shows a whole passage at once, so its links hang off the last line; if that line is guarded it would carry `showIf` and `choices` together, which the validator refuses (`COND`). | Yes: one unguarded line at the end of the passage. |
| 7 | **Conditional narration as the last beat** of a passage with no link out — `showIf` and `isEnd` are mutually exclusive too. | Yes: a line after it, or a link onwards. |
| 2 | **A link with no narration line to host it** — the passage opens with the link. | Yes: one line before it. |

Also reported in `unmapped` without costing a line: Harlowe macros with no
Parlance equivalent — `(icon-counter:)`, `(text-style:)`, `(align:)`,
`(link-goto:)`, `(event:)`, `(cond:)` — and the computed-text macros
`(print:)` and `(display:)`.

**159 guarded lines came across as `node.showIf`**, including every `(else:)`
hook under the negation of its `(if:)`. That is more conditional narration than
any other example here carries, and it is the reason this story replaced the
first one.

## 3. What a player can reach — 454 of 1,003

45%. What is cut off sits behind links whose guards did not map: in Harlowe every
forward motion is a link, so a link inside an `(if:)` whose condition cannot be
carried takes everything behind it with it.

The three biggest guard classes above are all conditions Parlance genuinely
cannot express — a read count, a text comparison, an underivable kind — so this
is a real cost rather than a mapping the importer declined to make. The report
for [`the-intercept`](../the-intercept/REPORT.md) has the counterpart case, where
a construct that looked unexpressible turned out not to be.

**Walk the graph; do not read the declared-loss total.** 182 losses out of 1,179
units is 15%, and it costs 55% of the story — because one loss on a trunk link is
worth a hundred on the leaves. Reachability is pinned for every example in
`tooling/tests/test_importer_examples.py` for exactly this reason.

## 4. Open questions for the author

- **`$gender` is assigned as two kinds.** `"male"` in one passage, `0` in
  another. The importer will not pick; both readings change when lines appear.
- **`(either:)` and `(ds:)`** choose at play time — `(set: $deadname to (either:
  "Jessica", "Allison", "Zoë"))`. Parlance conditions read authored state, so the
  variable's kind is underivable and its gates are declared.
- **Absolute counter assignment.** `(set: $self to 0)` has no effect to map to:
  the vocabulary has `adjust_counter` with a delta and nothing else. `(set: $self
  to it + 1)` maps fine — `it` gives the delta.
- **19 dialogues from 167 passages**, grouped by link connectivity. Whether those
  are the right scenes is an editorial question nobody has answered.

## 5. Validator state

**Zero errors.** 603 warnings:

| n | code | why |
|---|---|---|
| 549 | `REACH` | §3 — links whose guards did not map. |
| 27 | `TEXT` | Text variables set by the story and never interpolated into a line. |
| 14 | `FLOW` | A node where every choice has a `showIf` — the player may be stuck if none passes. True of the source too. |
| 9 | `COND` | A conditional node carries `onEnter` effects, which do not fire when it is skipped (advisory). |
| 4 | `FLAG` | Downstream of dropped assignments: flags set but never read. |

## 6. What was NOT checked

The content check compares player-facing strings. **It does not verify that the
graph means what the Twine meant.** Structure is the importer's judgment and the
author's review.

Specifically unverified here:

- **Passage-to-scene shape.** Harlowe renders a whole passage at once, so its
  lines and links are one screen; Parlance makes several beats the player
  advances through, with the choices at the end. Faithful in content, different
  in rhythm.
- **No characters.** Harlowe names no speaker, so every line is unattributed
  narration. That is what the source says; it is not what an author would want.
- **Markup is carried verbatim.** `<span>` and `<ul>` in a line stay in the line.
  Stripping them would be a rewrite, and the rewrite budget in `check.py` is
  capped at token scale for exactly that reason.

## 7. What this import taught the parser

`parse_twine.py` had already imported one story cleanly when this one was tried.
It found five more defects, and the pattern in them is the useful part: **every
one produced a wrong REASON attached to a correct loss.** The losses were real;
the explanations pointed an author at the wrong line.

1. **`(set:)` takes several assignments at once** — `(set: $gender to "male",
   $noun to "boy", $sbj to "he")` — and only the first was read. Most of the
   story's variables stayed undeclared, so guards on them were reported as "the
   source never declares this name", which was not true of the story.
2. **A macro's argument was accounted against the macro's first line**, so a
   `(set:)` spanning a dozen lines had every line but one counted as prose the
   parser had lost — 137 residue lines on a story with nothing wrong with it.
3. **`$name's` stripped to a bare `'s`**, whose `s` the word pattern counted as a
   word nobody wrote.
4. **`(icon-counter: bind $self, …)` binds a NUMBER.** Reading every bind as text
   made four counters conflict with themselves and resolve to unknown, which
   turned every guard on them into declared loss. Fixing this alone took carried
   guards from 37 to 137.
5. **`visits` is a Harlowe keyword**, not a variable — a read count, which
   Parlance cannot express. Reported as an undeclared name, it sent the reader
   hunting for a missing `(set:)` for something the language provides.

Two further disagreements surfaced when the import was first run against the
validator, both between the parser's model and the importer's:

- The parser checked whether the line **immediately before** each link was
  guarded. The importer hangs **all** of a passage's links off its **last** line,
  because that is how Harlowe renders. A guarded last line therefore hosted a
  choice list anyway — `showIf` with `choices`, which `COND` rejects.
- The importer emitted `set_text` effects for variables whose kind the parser had
  refused to derive, so they were never registered — a dangling reference the
  validator caught as `REF`.

Neither was visible to the content check. Both were caught by running the
validator over the result, which is why the gate runs it.

## 8. How the mapping was done

By script — [`import.py`](import.py), on top of
[`../build_twine_example.py`](../build_twine_example.py). The script reads every
player-facing string from the parser's IR and copies it byte for byte, never
composing a string, filling an optional field, or inventing an id.

## 9. The simple case, for contrast

The first Twine example imported here was **egg.exe** by Henrique Teixeira Karez
(MIT) — 75 passages, 981 lines, 98 links. It converged with **84 declared losses
and zero validator errors**, and 88 of its guarded lines came across as
`node.showIf`.

It is not vendored any more, because it exercised too little to be worth half a
megabyte: only 42 of its imported nodes were reachable, all behind one link gated
on a text variable, and its shape — audio cues, input widgets, endings decided by
comparing two counters — is not how most people write Twine.

But the number is worth keeping, because it says something this story cannot:
**a simple Harlowe story imports as-is.** No parser changes were needed for it
beyond the four its own first run exposed, and nothing about it needed an author
to restructure anything before it would convert. The difficulty scales with how
much of the language a story uses, not with whether the importer works.
