# `AUDIT_CONVENTIONS.md` — telling the audits about your project

An optional file at your project root. Every audit reads it if it exists and runs
normally if it does not. Nothing generates it, nothing writes to it, and no audit
requires it.

It exists because the useful house rules are exactly the ones the data cannot state.
A validator can see that a rung is unreachable; it cannot know that one character's
ambiguity is load-bearing and must never resolve, or that `char_anon_crowd` is a pool
every passing extra speaks from rather than a person with a thin footprint.

Without this file those rules live inside forked skills, which is how a shared audit
becomes a private one. Keep them here instead and the audits stay generic.

## Format

Markdown. Headings the audits look for are listed below; anything else is ignored, so
you can keep prose for your writers in the same file. Every section is optional.

### `## Voice`

Where your register/style system lives, if you have one. A pointer is enough:

```markdown
## Voice
Canon: `lore/style.md`. Speakers are placed on two axes — formality and directness —
and a line is in character only if both hold. Contractions are fine everywhere;
period slang is not.
```

Whatever system you use, state it as something checkable. "Evocative but grounded" is
not a rule an audit can apply, and it will be ignored.

`character-voice-audit` reads this *in addition to* each character's `dialogueStyle`,
never instead of it. Per-character intent always wins over the project default.

### `## Chorus ids`

Character ids that are pools rather than individuals — an anonymous crowd, a rank of
generic guards, every passing stranger. Presence and voice audits judge these as a
group (is the seasoning consistent?) and never as characters with an arc.

```markdown
## Chorus ids
- `char_anon_bystander` — every passing stranger speaks from this id; it carries more
  words than any named character and none of them are a relationship.
```

### `## Unresolvable`

Characters or questions whose ambiguity is deliberate. Any audit that would recommend
a change *resolving* one of these must flag its own recommendation instead of making
it.

```markdown
## Unresolvable
- `char_steward` — loyal servant vs. quiet usurper must stay open in every state.
  No ladder ordering, no line, and no recommendation may collapse it.
```

### `## Re-entry`

Your policy on returning to a conversation. The presence audit needs this to tell a
real gap from a correct silence — a character the player revisits owes them an idle;
one who appears at a single consequential scene and leaves does not.

```markdown
## Re-entry
Persisting characters get an effect-free idle rung. One-way hinge characters do not —
after their scene the truthful state is silence or a soft refusal, and gating their
rung is a fix, not a defect.
```

### `## Player knowledge`

Facts the player is assumed to hold before the game starts, and named beats that
establish knowledge later. `state-reachability-audit` uses this to avoid reporting
premise as leakage.

```markdown
## Player knowledge
Assumed from the opening crawl: the war is over, the protagonist is a returning
veteran, the city is under curfew.
```

## Scope

These are editorial conventions for reviewing content. They are not runtime rules —
gameplay rules belong in `data/rules.json`, where the engine and both validators can
see them. Nothing in this file affects the game, the editor, or validation.
