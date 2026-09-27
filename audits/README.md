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
suggests replacement text. A finding names a *structural* fix — retune this offer,
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
| `offer-audit` | your stated arc for the character |
| `state-reachability-audit` | what the dialogue graph proves the player can know |
| `character-presence-audit` | the payoff scene you wrote, measured against its setup |
| `cookbook-conformance-audit` | the pattern cookbook recipe each site is reaching for |

**When the anchor is missing, the audit stops and asks you for it.** It does not
substitute a standard of its own. An audit that would have to invent the intent in
order to judge against it is an audit that produces slop, and refusing is the whole
reason these are worth running.

**4. Findings are advisory.** They are warnings addressed to an author who knows
things the data doesn't. None of them gates CI, and none of them is right often
enough to. "Wins forever" may be an intended one-way door; a thin footprint may be
a deliberately minor character.

**Known limits, stated because the promise above is only worth what it excludes.**
An independent audit of this bundle found real defects. Most are fixed: every gather now
globs entity directories recursively (so dialogues nested in subfolders are read), honours
a `data` override in `parlance.config.json`, and finds a character by its `id` field
rather than its filename; `state-reachability-audit` now revokes facts (`set_flag: false`,
`take_item`, `adjust_counter`, `advance_quest`) as well as establishing them. What still
holds:

- `character-presence-audit`'s first gather reports **zeros for a mistyped character id**
  rather than an error (the voice and offer gathers stop and say so). A character with
  0 spoken nodes is more often a typo than a finding.
- A file a gather can't parse is skipped rather than reported, and an under-read looks
  exactly like a clean project. Check the reported node and word counts against what you
  expect before trusting any finding.
- `state-reachability-audit` can't see through `any`/`not` gates or world state, and a
  counter it has seen adjusted goes unknown rather than being recomputed. Each skill states
  its own limits; read them.

Until those are gone, the bundle's second promise — loss is declared, never silent — does
not fully hold for the gather step, and you should read the counts.

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

Take one, take all, take none. They share no code and no state; each `SKILL.md` is
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
`common.schema.json`. They target contract **0.15.x**. A field rename upstream will
silently reduce an audit to finding nothing — which looks exactly like a clean
project. Re-check the anchors after any contract bump.
