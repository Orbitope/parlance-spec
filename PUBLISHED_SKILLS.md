# Published skills

Claude Code skills for [Parlance](https://github.com/Orbitope/parlance) projects, in
two bundles. Both are inside the MIT carve-out (`LICENSE-SPEC`) and publish to
`parlance-spec` alongside the schema and the reference validator — forking one for
your own project is the point, and a licence that withholds that makes them useless.

- **[`audits/`](audits/README.md)** — editorial audits. They read a project and report
  on it: whether a dialogue ladder's ordering tells the intended story, whether a
  character sounds like themselves, whether a line can be reached in a state where it
  is not yet true, and whether a use of a `COOKBOOK.md` recipe trips that recipe's
  documented pitfall.
- **[`importers/`](importers/IMPORTERS.md)** — format migration. They move a story you
  already wrote out of another tool and into Parlance, then verify nothing was lost.
  [`importers/examples/`](importers/examples/README.md) holds three real migrations
  — one per format — each with the author's original file beside the result.

They are optional and separate. Nothing here is part of the editor, and nothing here
is installed with it. Take one skill, take all of them, take none.

## The one rule

**Nothing in either bundle writes prose.**

Not a line of dialogue, not a summary, not a description, not a placeholder. The
audits report and never draft. The importers convert and never paraphrase. If a field
is empty, it stays empty until a human fills it.

This is enforced, not promised:

- Every audit's commands are reads. None writes to `data/`.
- Every importer's output is checked against the source string by string. A paraphrase
  — the most tempting failure, because it looks like tidying — halts the import and
  is never retried, because a further pass cannot un-invent a line.

You can run that check on the worked examples yourself; one command per example,
in each one's `REPORT.md`. It is there so this page's promise is a property you
can verify rather than a claim you have to take on trust.

The second rule follows from the first: **loss is declared, never silent.** Both tools
report what they could not do. An audit that cannot judge without inventing the intent
stops and asks for it. An importer that meets a construct Parlance cannot carry names
it, its source line, and why — rather than quietly approximating.

A migration with three declared losses is a good outcome, honestly reported. One that
came out clean because the awkward lines were reworded is a failure that looks like a
success.

## Why these can exist at all

Both bundles are downstream of one property: a Parlance narrative is structured JSON
with a declared contract and a reference validator. You can compute what the player
provably knows at a given line, and you can prove an imported story still contains
every string the original did. Neither is possible against a pile of prose.

## Installing

Copy the skills you want into your project's skills directory:

```bash
cp -r audits/character-voice-audit  /path/to/project/.claude/skills/
cp -r importers/yarn-import         /path/to/project/.claude/skills/
```

The importers also need their `lib/` alongside them. Each skill is otherwise
self-contained: no shared state, no configuration, no network calls, no telemetry.

## Contract version

These read the Parlance data contract — `dialogues`, `characters`, `quests`,
`locations`, `variables`, and the condition/effect vocabulary. They target contract
**0.12.x**. After a contract bump, re-check them: a renamed field will usually reduce a
tool to finding nothing, which looks exactly like a clean project.

That is not a formality. This line said **0.9.x** for three releases after the fact,
across the one bump that mattered to the importers — `DialogueNode.showIf` in 0.11.0,
which turned a whole class of declared loss into a mapping. Move it with the contract,
not with the next person who notices.
