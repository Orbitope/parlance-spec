# Importers

Migration into Parlance from the formats writers are already using.

| Skill | Source format | Status |
|---|---|---|
| [`yarn-import`](yarn-import/SKILL.md) | Yarn Spinner (`.yarn`) | working |
| [`ink-import`](ink-import/SKILL.md) | Ink (`.ink`) | working |
| `twine-import` | Twine — Harlowe and SugarCube are separate targets | not started |

Yarn came first because its shape is closest to Parlance's: nodes, options, jumps and
`<<set>>` map almost one-to-one, which makes it the cheapest honest proof that the
pipeline works. Ink is a programming language rather than a format — knots, diverts
and variables map, while tunnels, threads, lists and external functions do not, and
those are exactly the declared losses an importer has to be candid about.

## How an import is verified

Every importer shares `lib/check.py`, and the point of it is that the loop does not
get to decide when it is finished.

An import loop that repairs its own output has one dangerous failure mode: the
cheapest way to silence a validator finding is often to write something. `check.py`
runs the reference validator **and** a content-preservation check over the same
output, then returns a verdict the skill must obey:

| Verdict | Meaning |
|---|---|
| `STOP converged` | No errors, nothing lost, nothing invented. |
| `CONTINUE` | Defects remain and the last pass reduced them. |
| `STOP no-progress` | The last pass did not strictly reduce the defect count. |
| `STOP cap` | Iteration cap reached. |
| `STOP invented` | The output contains prose that is not in the source. Hard stop. |

The iteration cap and the strictly-decreasing rule live in the script rather than in
the skill's prose, so a model cannot reason its way into one more pass. `STOP invented`
is never retried: another pass cannot un-invent a line, so a human has to look.

### Declared loss does not block convergence

Some things Yarn can express, this importer cannot yet convert — a narration line
guarded by `<<if>>` is the live case. The parser marks these,
and `check.py` reports them as `missing_declared` **without** counting them as
defects. That is deliberate: if declared loss blocked convergence, no story containing
one could ever finish, and the loop's cheapest escape would be to fabricate a mapping.

The distinction the check draws is between loss the author is told about and loss
nobody notices.

**Half of this is now done.** `DialogueNode.showIf` shipped in **0.11.0**, so the target
exists and the old reasons — which said a Parlance *node* has no `showIf` — were false and
have been corrected: they now say this importer does not map guards yet, which is the true
statement. Guarded narration is still declared loss, deliberately, until the mapping below
is built. Two things must change together when it is, and the second is easy to miss:

1. The reason strings in `parse_yarn.py` and `parse_ink.py` — and the `missing_declared`
   entries the fixtures assert — become mappings instead of losses.
2. An `else` branch does **not** get the same `showIf` as its `if` branch. Ink and Yarn
   both write the alternative without restating the condition; mapping both branches to
   the guard would show the two lines together whenever it holds, which reads as
   duplicated narration rather than a missing line, and no content check would flag it —
   nothing is lost and nothing is invented. The else branch needs the negation.

### Residue: the loss the manifest cannot see

`check.py` compares the imported project against the manifest, which catches
everything the manifest knows about and nothing it does not. Prose a parser drops
**before** writing the manifest is invisible to that comparison by construction —
the yardstick is short by exactly the amount that went missing, so the two agree.

An audit found live instances of that in both parsers: a `->` inside a sentence read
as a divert and excising the rest of it, a URL whose `//` was read as a comment, a
BOM making the first line of a Yarn file unrecognisable so the node parsed with no
title, and an inline `<<if>>` guard dropped because the depth counter was read before
it was incremented.

So each parser also emits `residue`: every word in the source that reached no unit, no
declared-unmappable construct and no recognised command, with its line. `check.py`
refuses to converge while `residue` is non-empty, and says so as a **parser gap** — the
repair for it is a fix to the parser, never a hand-mapping in the project.

Two properties make it work rather than merely exist:

- It is computed from the manifest's own `units` and `unmapped`, not from a second
  parse that could drift from them. It measures the artefact actually used as the
  yardstick.
- It counts words as a **multiset**. A parser that eats one occurrence of a repeated
  word corrupts the sentence just as surely as one that eats a rare word, and set
  accounting cannot see it: `The rope -> the cleat, then around the post.` loses a
  `the` and still contains two more.

Word-level rather than byte-level is deliberate. Format punctuation legitimately
disappears (`<<`, `->`, `{$`), so demanding byte coverage would be pure noise; losing a
word of a writer's prose never has an innocent explanation.

**Every strip pattern is a hole in the accounting**, and this is where the idea is
easiest to break, because a hole looks exactly like a source with nothing missing. Three
rules, each learned by breaking it:

1. **Never strip a construct that can carry prose.** Ink braces are the case that proves
   it: `{a|b}` alternatives and `{cond: line}` conditionals are player-facing text, and a
   blanket `\{[^{}]*\}` reported an entirely dropped line as fully accounted for — the
   original defect, rebuilt inside the fix. Only the non-prose HEAD of a brace group is
   stripped; everything past a `:` or a `|` stays required.
2. **Order matters.** A broad marker pattern placed first eats the prefix of a construct
   the next pattern needs to see: `^\s*[*+-]+` consumed the `-` of `-> END`, leaving
   `> END` unmatched by the divert pattern, and `END` reported as lost prose.
3. **Negated character classes must exclude the newline.** `[^:]*` crosses lines happily.
   The else-branch pattern once matched four source lines at a stretch — a divert, a
   blank line, a knot header and the opening of the next conditional — and removed all of
   them from the count.

`tooling/tests/test_importers.py` guards all three, and the guards are meta-tests: they
do not check a parser, they check that the checker can still see. The strongest is
`test_every_recorded_line_is_visible_if_lost` — erase all record of one source line and
residue must notice, for every line in both fixtures. A line whose disappearance is
undetectable is a blind spot, and a real parser bug there would converge silently.

`residue` is covered by the manifest's integrity digest along with `units` and
`rewrites`, so emptying it by hand is refused as tampering rather than obeyed.

### What it does not check

The content check compares player-facing strings. It does not verify that the graph
you built means what the source meant — that a jump landed on the right node, or that
a choice gates on the right flag. Structure is still the importer's judgment and the
author's review. Every import report is required to say so.

## Testing an importer

`fixtures/` holds a small story per format and the Parlance project a faithful import
of it produces. Each one deliberately includes constructs the format can express and
Parlance cannot, so the declared-loss path is exercised rather than assumed:
`toll_house.yarn` has a conditional narration line; `ferry_landing.ink` has eleven
kinds, including a tunnel, a thread, a `LIST`, a read-count gate and variable text.

One of the eleven is not loss at all, and is the most instructive entry in either
fixture: a bracket-less Ink choice **echoes** its text into the story and a Parlance
choice does not. Nothing goes missing — the words are there as `choice.text`, so the
content check converges — but the player reads one fewer beat. It is the worked
example of the limit stated above: the check compares strings, not meaning.

The Ink fixture is also the regression test for the boundary that matters most. Its
faithful import converges with seven strings under `missing_declared` and none under
`missing_unexplained`; delete a line from a copy and the check returns `CONTINUE`
naming that string; reword one and it returns `STOP invented` naming the string and
the node it landed in.
