# Parlance — Data Schema

> **Pre-1.0.** The contract is not yet stable: breaking changes may land in any
> minor release. See `tooling/VERSIONING.md` before pinning a version.

> **License: MIT** (see `LICENSE-SPEC`). These files are meant to be copied —
> vendor them into your port and republish freely. The Parlance *editor* is
> licensed separately and is not covered by that grant.

## Purpose

This folder defines the *contract* that all game data obeys. Every JSON file under
`/data` must validate against one of these schemas. The validator (in `/tooling`)
enforces both the shape of each file (schema validation) and the relationships
*between* files (consistency validation) — e.g. "every faction a dialogue references
must actually exist."

## The two layers

- `/lore` — human-readable Markdown. The canon, the feel, the "why."
- `/data` — machine-readable JSON. What the game and tools consume.

Every `/data` entity may carry a `loreRef` pointing at a `/lore` file (and optionally
an anchor within it). This keeps prose and data from silently drifting apart.

## Entity types (each has its own schema file)

| Entity      | File                  | What it is                                            |
|-------------|-----------------------|-------------------------------------------------------|
| Skill       | `skill.schema.json`   | A stat the player character checks against in dialogue. |
| Faction     | `faction.schema.json` | A political/religious group with reputation tracking. |
| Character   | `character.schema.json` | An NPC, including faction membership and stats.     |
| Dialogue    | `dialogue.schema.json`  | A graph of nodes + choices with conditions/effects. |
| Quest       | `quest.schema.json`     | Objectives, stages, and the flags they set.         |
| Location    | `location.schema.json`  | A place in the world.                                |
| Variable    | `variable.schema.json`  | A registry of every flag/counter/text id used.      |
| Item        | `item.schema.json`      | A thing the player can carry. Possession is runtime state; this gives it a name. |
| Ending      | `ending.schema.json`    | A final outcome and the conditions that unlock it.  |
| Codex       | `codex.schema.json`     | A player-facing knowledge entry, optionally unlocked by a condition. |

## The shared vocabulary: Conditions and Effects

This is the heart of the system. Branching logic everywhere — dialogue gates, quest
triggers, ending unlocks — is expressed with the *same* two structures, defined in
`common.schema.json`:

**Condition** — a testable predicate. Examples:
- `{ "type": "reputation", "faction": "faction_harbour", "op": ">=", "value": 3 }`
- `{ "type": "flag", "flag": "knows_the_password", "value": true }`
- `{ "type": "skill", "skill": "instinct", "op": ">=", "value": 8 }`
- `{ "type": "quest", "quest": "task_intro", "op": ">=", "stage": "stg_accepted" }`  (at or past a stage)
- `{ "type": "relationship", "character": "npc_wren", "op": ">=", "value": 2 }`
- `{ "type": "all", "of": [ ...conditions... ] }`  (AND)
- `{ "type": "any", "of": [ ...conditions... ] }`  (OR)

**Effect** — a state change. Examples:
- `{ "type": "set_flag", "flag": "told_the_truth", "value": true }`
- `{ "type": "adjust_reputation", "faction": "faction_harbour", "delta": 2 }`
- `{ "type": "adjust_relationship", "character": "npc_wren", "delta": 1 }`
- `{ "type": "give_item", "item": "item_lantern" }`
- `{ "type": "set_text", "variable": "player_name", "value": "Wren" }`

Because conditions and effects only ever reference IDs from the variable registry,
the factions list, the skills list, etc., the validator can check that *every*
reference resolves. That's what catches inconsistencies before they reach the game.

## A Check (used inside dialogue choices)

A check wraps a skill roll around a choice.
- `active` checks are rolled (pass/fail, can be retried per game rules TBD).
- `passive` checks silently reveal/hide a choice based on a threshold (no roll).

```
"check": {
  "mode": "active",
  "skill": "rhetoric",
  "difficulty": 12,
  "onSuccess": "node_official_convinced",
  "onFailure": "node_official_suspicious"
}
```

## Text variables and interpolation

A project may let the player name the protagonist, so authored strings that address or
refer to them must substitute that value when rendered.

`variable.schema.json` has a fourth `kind` for this: **`text`**.

```json
{ "id": "player_name", "kind": "text", "description": "The name the player chose", "default": "the newcomer" }
```

A text variable is a **string-substitution slot, not a gate**. There is no `text`
condition type and there will not be one — branch on a flag set alongside the value.

**Writing one** — the `set_text` effect:

```json
{ "type": "set_text", "variable": "player_name", "value": "Wren" }
```

`value` is always a literal. Capturing free-text player input is the engine's job; the
engine calls the effect with whatever string it collected. Parlance has no input-capture
concept.

**Reading one** — a `{var_id}` placeholder in authored text:

```json
{ "id": "n_wake", "text": "Sit down, {player_name}." }
```

Single braces, a bare variable id, no spaces, no filters, no modifiers. This is a
substitution layer, not an expression language: no conditionals, formatting, nesting, or
arithmetic.

**Where placeholders are substituted** — player-facing strings only:

`DialogueNode.text` · `Choice.text` · `Objective.text` · `Stage.description` ·
`Quest.journalName`

Ids, `name`, `summary`, `notes`, and every other authoring-facing field are left alone; a
brace there is just a brace.

**Runtime shape.** `GameState` gains a `texts: Record<string, string>` field, seeded by
`createDefaultState` from each text variable's `default` and written by `set_text`.
`interpolate(text, state)` (from `@parlance/core`) does the substitution at **render
time** — authored JSON always keeps the placeholder, and a value is never baked into
content. A placeholder with no value renders **as written** (`{player_name}`) and logs a
warning, so the failure is visible in-game instead of silently blanking. It never throws.

There is no escaping mechanism in v1 — see `tooling/RUNTIME_CONTRACT.md`
§ Text interpolation for the full contract, including that limitation.

### TEXT validator checks

| Check | Severity |
|---|---|
| a `{placeholder}` naming a variable that does not exist, or one that is not `kind:"text"` | error |
| a `text` variable no `set_text` ever writes and which has no `default` | warning |
| a `text` variable declared but never referenced in any authored string | warning |

## The quest journal (Quest, Stage, Objective)

The engine's quest UI — "the journal" — renders, per active quest: the completed
stages as a retrospective list, and the **current** stage's available routes.
It is framed diegetically as the protagonist's *intentions* — what the
protagonist has decided to do — not as a task list handed down by the game. All
authored text in these fields is in their voice.

Future stages are never shown. The journal shows completed stages and the
current stage only; there is deliberately no `hidden`, `revealWhen`, or
next-stage preview field.

### Stage

| Field | Meaning |
|---|---|
| `id`, `order` | identity + intended sequence (the validator checks ordering sanity) |
| `description` | **RETROSPECTIVE** — what the protagonist *did*, shown once the stage is complete. Not a to-do. |
| `objectives` | the forward-looking routes shown while the stage is **current** (see below) |
| `completeWhen` | the sole authority on stage completion |
| `onComplete` | effects fired when `completeWhen` first holds |

The retrospective/intention split is the thing to keep straight: `description`
is past tense and appears *after* the stage; `objectives` are present tense and
appear *during* it.

### Objective

Objectives are **inline**, not an entity type — they live inside `Stage` exactly
as `Choice` lives inside `DialogueNode`. There is no `data/objectives/`, no
registry, and no id-uniqueness across the project; ids need only be unique
within their stage.

```json
{
  "id": "ob_ask_the_stablehands",
  "text": "Ask the stablehands what happened to the horses.",
  "showIf": { "type": "flag", "flag": "met_stablehand", "value": true }
}
```

- `id` — stable, unique **within the stage**. Validator and diff only; never rendered.
- `text` — the protagonist-voice intention line.
- `showIf` — optional gate; omitted means always visible. Gates on **knowledge
  and acquaintance** (have they met this character, do they know this place), so
  an objective only shows if the protagonist could actually name that route.
  Skill-gated objectives are out of scope.

Array order is authoring order, and the journal renders in that order.

**Objectives are display-only.** No effects, no `goto`, no per-objective
completion state — the runtime never reads them. Whichever route the player
actually followed, `completeWhen` alone decides when the stage is done. See
`tooling/RUNTIME_CONTRACT.md` § Quest journal.

### Quest-level journal fields

| Field | Meaning |
|---|---|
| `journalName` | player-facing quest title; falls back to `name` when absent (`name` stays the authoring-facing label) |
| `tags` | drives the journal's grouping and prioritisation |

Main-vs-side is a **tag**, not a boolean field — prioritisation and grouping are
journal-UI concerns driven off `Quest.tags`. If the project declares
`rules.quest.tagVocabulary`, tags are linted against it; an off-vocabulary tag is an
`OBJ` **warning**, not an
error, so authors can stage a tag ahead of the vocabulary being extended. With no
vocabulary declared, any tag is accepted. A project declares one like this, in
`data/rules.json`:

```json
{
  "quest": {
    "tagVocabulary": ["main", "side", "act1", "act2", "act3"]
  }
}
```

### OBJ validator checks

| Check | Severity |
|---|---|
| duplicate `objective.id` within a stage | error |
| `objective.showIf` naming a nonexistent flag / faction / item / counter | error (via the REF pass) |
| `objective.showIf` gating on a flag no effect anywhere sets | warning (via the FLAG orphan pass) |
| stage has `completeWhen` but zero objectives | warning — empty current stage |
| stage has objectives but every one is gated | warning — can present an empty list at runtime |
| `quest.tags` entry outside the controlled vocabulary | warning |

All journal fields are optional; quests authored before the journal existed stay
valid and round-trip byte-identically with no migration.

## ID conventions

- IDs are lowercase snake_case, globally unique within their type.
- Prefix by type: `npc_`, `dlg_`, `task_`, `faction_`, `loc_`, `ending_`, `codex_`.
  **`NAMING_STANDARDS.md` is the single source of truth** for prefixes and slugging
  rules — this list is a pointer, not a second definition. (Deliberately not a
  relative link: this file and that one sit at different depths in the published
  spec repo than they do here.) (Prefixes are a convention; the validator does not enforce them.)
