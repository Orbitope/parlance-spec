# Importers

Migration into Parlance from the formats writers are already using.

| Skill | Source format | Status |
|---|---|---|
| [`yarn-import`](yarn-import/SKILL.md) | Yarn Spinner (`.yarn`) | working |
| [`ink-import`](ink-import/SKILL.md) | Ink (`.ink`) | working |
| [`twine-import`](twine-import/SKILL.md) | Twine / Harlowe (published `.html`, or `.twee`) | working |
| SugarCube | Twine's other story format | not started — a different macro language, and `twine-import` refuses a story that declares it |

[`examples/`](examples/README.md) holds three real migrations — inkle's *The
Intercept* (Ink), Play Curious's *Cyberharcèlement* (Yarn) and
Jake Kao's *Not Weird. Queer* (Twine) — each with the author's original file
beside the imported project, so the claim below can be
re-run rather than believed. Start with their `REPORT.md`s: the declared-loss
tables are the honest picture of what a migration costs.

## Will your story survive the move?

Read this before you start one. Three real migrations are enough to answer it
concretely, and the answer is not "it depends".

**One question decides most of it: how does your story move forward?**

- **The player picks from options you wrote** — it will carry well. That is what a
  Parlance dialogue *is*: authored beats, chained, with choices on them.
- **The engine works out where to go** — it will not. Every construct that computes a
  destination at play time has no equivalent, because a Parlance `goto` names one node,
  written into the data by you.

That second category is the whole of what broke the three imports, and it is worth
naming its members, because they do not look alike in the source:

| Construct | Formats |
|---|---|
| a call that returns to **different** places per caller | Ink `-> knot ->` where the call sites disagree. One call site is fine — a `goto` may point backwards, so the tunnel is two ordinary edges |
| a jump chosen by a condition | Harlowe `(goto:)`, `(link-goto:)`, a link inside an `(if:)` hook whose test will not map |
| a gate on **how many times** something has been seen | Ink `{knot > 1}`, Yarn `visited()`, `visitedAllNodeOptions()` |
| a destination handed to game code | Yarn custom commands, Ink `EXTERNAL` |

Three other classes are lost without breaking the flow — text computed at play time
(Ink `{a|b}`, Harlowe `(print:)`), calls into the engine (`(track:)`, `~ raise(x)`), and
input beyond a choice (`(input-box:)`, `(dropdown:)`). Those cost you lines and effects;
the table above costs you the *story*.

### Converging is not the same as working

This is the part no content check can tell you, and the reason to read a report rather
than a verdict. All three worked migrations converge — every word present, provably
unaltered, no validator error — and two of them produce a story a player can barely walk:

| Story | Format | Reachable | Severed by |
|---|---|---|---|
| Cyberharcèlement | Yarn | 446 / 544 | nothing single — custom commands route its UI |
| The Intercept | Ink | 387 / 546 | knots whose every line is declared loss, mostly one inline `{cond: a\|b}` |
| Not Weird. Queer | Harlowe | 454 / 1,003 | links gated on read counts, text comparisons and underivable kinds |

A single unmappable construct in the wrong place severs everything behind it, and the
string comparison converges happily while it does, because no prose went anywhere.

**So: after any import, walk the graph from the dialogue's `entry` and count what you can
reach.** Do not infer it from the manifest — a count of declared losses says nothing about
where they fell. Every report in `examples/` does this, and a first draft of one of them
blamed the wrong construct precisely because it counted reasons instead of walking.

### Which format ports best

Yarn, then Twine, then Ink — and the ordering is about the SOURCE, not the importer.
Yarn Spinner is a serialization format whose shape is close to Parlance's. Ink and Harlowe
are programming languages, and a story that uses them as such is leaning on exactly the
runtime flow control that does not cross over. A simple Ink story ports cleanly; an Ink
story built on tunnels and read counts does not.

---

Yarn came first because its shape is closest to Parlance's: nodes, options, jumps and
`<<set>>` map almost one-to-one, which makes it the cheapest honest proof that the
pipeline works. Ink is a programming language rather than a format — knots, diverts
and variables map, while tunnels, threads, lists and external functions do not, and
those are exactly the declared losses an importer has to be candid about. Twine
came third and is the odd one out: Harlowe has no weave and no fallthrough, so its
structure is the simplest of the three to map — and its flow is the most fragile,
because a passage's ONLY way forward is a link.

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

Some things a source format can express, these importers cannot convert — an Ink
`LIST`, a tunnel, a read-count gate. The parser marks these, and `check.py` reports
them as `missing_declared` **without** counting them as defects. That is deliberate:
if declared loss blocked convergence, no story containing one could ever finish, and
the loop's cheapest escape would be to fabricate a mapping.

The distinction the check draws is between loss the author is told about and loss
nobody notices.

### Conditional narration: a whole loss class, closed

Guarded narration used to be the largest entry on that list — 4–20% of narration
lines across the corpora measured in `NODE_CONDITIONS_SPEC.md`, and the reason every
import of every story lost content permanently. `DialogueNode.showIf` shipped in
**0.11.0** and both parsers now map onto it: Yarn's `<<if>>`/`<<elseif>>`/`<<else>>`
around a line, Ink's `{cond: text}`, its `{ cond: … - else: … }` blocks (nested, and
the switch form where the branch heads are literals), and choice gates in both.

`lib/conditions.py` is the translation, shared so that the two importers cannot
disagree about the same guard. It refuses rather than approximates: Parlance's
condition vocabulary is closed, so a guard it cannot express EXACTLY comes back as a
reason, and the caller declares the loss. What is left is narrow and each case says
which — a variable whose kind the source never reveals, a read count, a `LIST`, a
comparison between two variables, and a guarded line that would have to host a choice
list (a node may not carry `showIf` and `choices` together).

Two things about it are worth knowing before you touch it.

**The else branch needs the NEGATION, and nothing downstream can see if it does not
get one.** Ink and Yarn both write the alternative without restating the condition, so
the tempting mapping gives both branches the same guard — and then the player reads
two lines where the author wrote one. No line is missing and none is invented, so the
content check converges on it happily. That is why `check.py` compares the CONDITIONS
too, reporting `condition_mismatch` when the output disagrees with the manifest about
a guard, in either direction: a guard dropped or altered, and a gate on a line the
source never gated. Convergence is blocked either way.

**A guard is all-or-nothing.** Dropping an unmappable conjunct from an otherwise
mappable guard leaves a condition that holds strictly more often, so the line shows in
states the author gated it out of — the same invisible-to-string-accounting defect,
one step subtler. `conditions.translate` refuses the whole expression instead.

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
4. **A pattern that matches too LITTLE is the same bug wearing the opposite coat.** The
   Yarn command pattern was `<<[^>\n]*>>`, which excludes `>` from the body — so
   `<<if $coins >= 2>>` matched nothing at all, counted as prose, and refused to converge
   on a story with nothing wrong with it. Neither fixture contained a comparison, so
   nothing said so until a real one did.

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

Two layers, and the second is the one that finds things. `fixtures/` holds a
small story per format that we wrote; `examples/` holds real stories that we did
not. The fixtures exercise every path deliberately, and the examples exercise the
paths nobody thought of — running The Intercept through `parse_ink.py` for the
first time found eight defects the fixtures structurally could not, one of which
put 230 lines under a guard they did not have. `tooling/tests/test_importer_examples.py`
re-derives each example's manifest from its vendored source and re-runs the gate,
so neither the imports nor the reports can rot quietly.

`fixtures/` holds a small story per format and the Parlance project a faithful import
of it produces. Each one deliberately includes constructs the format can express and
Parlance cannot, so the declared-loss path is exercised rather than assumed, and both
now also carry an `if`/`else` pair whose branches must map to a guard and its
NEGATION: `toll_house.yarn` has one conditional line in the one position that cannot
be carried (immediately before a choice list) and one if/else that can;
`ferry_landing.ink` has a tunnel, a thread, a `LIST`, a read-count gate, variable
text, an inline `{cond: text}` and a `{ cond: … - else: … }` block.

One of those is not loss at all, and is the most instructive entry in either
fixture: a bracket-less Ink choice **echoes** its text into the story and a Parlance
choice does not. Nothing goes missing — the words are there as `choice.text`, so the
content check converges — but the player reads one fewer beat. It is the worked
example of the limit stated above: the check compares strings, not meaning.

The Ink fixture is also the regression test for the boundary that matters most. Its
faithful import converges with four strings under `missing_declared` and none under
`missing_unexplained`; delete a line from a copy and the check returns `CONTINUE`
naming that string; reword one and it returns `STOP invented` naming the string and
the node it landed in.

And the boundary that no string comparison reaches: give either fixture's `else`
branch the same `showIf` as its `if`, and `missing` and `invented` both stay empty
while `condition_mismatch` names the line and shows what the guard should have been.
