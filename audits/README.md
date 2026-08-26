# Audits

Editorial audits for Parlance projects, packaged as Claude Code skills. Each one
answers a question about your narrative that a static validator cannot — whether an
ordering tells the story you meant, whether a character sounds like themselves,
whether a line can be reached in a state where it isn't true yet.

They are a separate, optional bundle. They are not part of the editor, not part of
the format spec, and not installed with either. Delete this directory and Parlance
behaves identically.

## The five rules these audits run on

**1. They never write your prose.** No audit drafts a line, rewrites a line, or
suggests replacement text. A finding names a *structural* fix — reorder this rung,
change this gate, this line asserts something the player can't know here — and stops.
The words are yours. This is a hard rule, restated in every skill, and it is the
first thing to check if you fork one.

**2. They never write to your repository at all.** Not `data/`, and not a helper
script beside it either. Audits read your project and produce a report in the
conversation; every command in every skill goes down a pipe, so running one leaves
`git status` exactly as it found it. If an audit ever proposes an edit, you make it.

**3. They judge your content against intent you declared, not against a house style.**
No audit has an opinion about what good writing is. Each one is anchored on something
you already wrote down:

| Audit | Anchor |
|---|---|
| `character-voice-audit` | the character's own `dialogueStyle` field |
| `quest-journal-audit` | the tense rule stated in `quest.schema.json` |
| `ladder-audit` | your stated arc for the character |
| `state-reachability-audit` | what the dialogue graph proves the player can know |
| `character-presence-audit` | the payoff scene you wrote, measured against its setup |

**When the anchor is missing, the audit stops and asks you for it.** It does not
substitute a standard of its own. An audit that would have to invent the intent in
order to judge against it is an audit that produces slop, and refusing is the whole
reason these are worth running.

**4. Findings are advisory.** They are warnings addressed to an author who knows
things the data doesn't. None of them gates CI, and none of them is right often
enough to. "Wins forever" may be an intended one-way door; a thin footprint may be
a deliberately minor character.

**Known limits, stated because the promise above is only worth what it excludes.**
An independent audit of this bundle found real defects, and the honest ones to know
before you rely on a result:

- The gathers glob entity directories **non-recursively** and assume the default `data/`
  layout. A project that nests dialogues in subdirectories, or that redirects `data` via
  `parlance.config.json`, is silently under-read — and an under-read looks exactly like a
  clean project. Check the reported node and word counts against what you expect before
  trusting any finding.
- The gathers assume a character's **filename matches its id**. The schema does not
  require that; a mismatch either crashes or silently reports zero.
- A mistyped character id reports zeros rather than an error.
- `state-reachability-audit`'s KNOWN set has **no kill logic**: `take_item` and
  `set_flag: false` are not modelled, so a fact once established is treated as permanent.
  Treat its KNOWN as "established somewhere upstream", not "still true here".

These are being fixed. Until they are, the bundle's second promise — loss is declared,
never silent — does not fully hold for the gather step, and you should read the counts.

**5. Nothing leaves your machine except what you send.** These are prompts. They
read local files through your own agent. There is no service, no account, no
telemetry, and no network call in any skill here.

## What is deliberately not in this bundle

Anything that generates content. Project scaffolding and draft-writing helpers are
buildable against this format and do not belong here.

Format migration is a different thing and lives in [`../importers/`](../importers/IMPORTERS.md):
an importer moves words a human already wrote between serializations. It authors
nothing, it is held to the same rule as the audits, and its output is verified against
the source string by string.

## Installing

Copy the audits you want into a project's skills directory:

```bash
cp -r audits/character-voice-audit /path/to/project/.claude/skills/
```

Take one, take five, take none. They share no code and no state; each `SKILL.md` is
self-contained.

## Telling an audit about your project

Every audit works with no configuration. If a project root contains an optional
`AUDIT_CONVENTIONS.md`, the audits read it for house rules they could not otherwise
know — a character whose ambiguity must never resolve, a chorus id that is a pool
rather than a person, a register system your writers work from. See
[`CONVENTIONS.md`](CONVENTIONS.md) for the format.

The file is optional in the strict sense: absent, every audit runs and simply has
less context. It is never required, never generated, and never written to.

## Contract version

These audits read the Parlance data contract: `dialogues`, `characters`, `quests`,
`locations`, `variables`, and the condition/effect vocabulary in
`common.schema.json`. They target contract **0.10.x**. A field rename upstream will
silently reduce an audit to finding nothing — which looks exactly like a clean
project. Re-check the anchors after any contract bump.
