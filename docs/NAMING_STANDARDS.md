# Parlance Naming & ID Standards

This document defines the conventions for all auto-generated and hand-written IDs in a Parlance project. Following these conventions makes IDs predictable, searchable, and stable across tools.

---

## Quick Reference

| Entity type     | Prefix      | Example                       |
|-----------------|-------------|-------------------------------|
| Character       | `npc_`      | `npc_mira_voss`               |
| Dialogue        | `dlg_`      | `dlg_mira_intro`              |
| Quest           | `task_`     | `task_find_the_contact`       |
| Quest stage     | `stg_`      | `stg_enter_district`          |
| Faction         | `faction_`  | `faction_merchant_guild`      |
| Location        | `loc_`      | `loc_inner_district`          |
| Ending          | `ending_`   | `ending_the_long_road`        |
| Codex entry     | `codex_`    | `codex_the_harbour_accord`    |
| Dialogue node   | `node_`     | `node_greeting`               |
| Choice          | `ch_`       | `ch_honest`, `ch_wit_bluff`   |
| Skill           | *(none)*    | `strength`, `wit`             |
| Variable / flag | *(none)*    | `met_mira`, `completed_intro` |

---

## General Rules

### Slugification

When generating an ID from a human-readable name, apply these transforms in order:

1. Lowercase everything.
2. Normalize accented/special characters to their ASCII equivalents (é → e, ñ → n, etc.).
3. Replace all non-alphanumeric characters (spaces, hyphens, punctuation) with underscores.
4. Collapse consecutive underscores to one.
5. Strip leading and trailing underscores.
6. Prepend the entity prefix.

Example: "Mira Voss" → `mira_voss` → **`npc_mira_voss`**
Example: "The Merchant's Guild" → `the_merchants_guild` → **`faction_the_merchants_guild`**

For very long names, drop filler words (the, a, an, of) before slugifying to keep IDs short.

### Length limit

Keep IDs at **40 characters or fewer** (excluding the prefix). IDs that exceed this are harder to read in logs, JSON diffs, and UI labels. Abbreviate the slugified portion when necessary:

`task_find_the_smuggled_shipment_in_the_warehouse` → `task_find_smuggled_shipment` (28 chars ✓)

### Collision handling

If a generated ID already exists, append `_2`, `_3`, etc.:

`npc_mira_voss` → `npc_mira_voss_2`

Do not use random suffixes. Numeric suffixes preserve alphabetic sort order and are easy to spot in diffs.

---

## Entity-specific conventions

### Characters (`npc_`)

Use `npc_<first>_<last>` or `npc_<role>` for unnamed characters.

```
npc_mira_voss       # named character
npc_gatekeeper      # role-based, no proper name
npc_merchant        # role-based
```

**Special case — the player character:** always use the literal id `player`. No prefix.

### Dialogues (`dlg_`)

Use `dlg_<character>_<scene>` where the character is the NPC slug (without the `npc_` prefix) and the scene is a brief descriptor:

```
dlg_mira_intro          # first conversation with Mira
dlg_mira_post_quest     # follow-up after quest completion
dlg_gatekeeper_intro    # gatekeeper's intro scene
```

If a dialogue doesn't belong to a specific character (e.g. a cutscene), use `dlg_<scene>`:

```
dlg_opening_cutscene
dlg_district_reveal
```

### Quests (`task_`)

Use `task_<verb>_<object>`. Prefer an action verb that describes what the player does:

```
task_find_contact
task_deliver_package
task_clear_checkpoint
```

Avoid encoding the NPC name into the quest ID unless the quest is specifically about that character — quests outlive individual NPC assignments.

### Quest stages (`stg_`)

Use `stg_<descriptor>` within the quest's `stages` array. Stages should read as a sequence:

```
stg_enter           # player enters the area
stg_meet_contact    # player meets the NPC
stg_deliver         # player delivers the item
stg_complete        # quest resolved
```

### Factions (`faction_`)

Use `faction_<name>`. Keep it concise — factions appear in effect labels and state inspector output.

```
faction_merchant_guild
faction_city_watch
faction_neutral
```

### Locations (`loc_`)

Use `loc_<descriptor>`. Descriptors should match the in-world area name, slugified.

```
loc_checkpoint
loc_inner_district
loc_merchant_quarter
```

### Dialogue nodes (`node_`)

Use `node_<scene_description>`. The descriptor should describe what happens at the node, not who speaks it (the speaker is captured in `speakerId`):

```
node_greeting           # opening beat
node_player_inquiry     # player asks a question
node_npc_refuses        # NPC declines to help
node_suspicious         # NPC is wary
node_cleared            # player is let through
```

For isEnd nodes, the descriptor often names the outcome:

```
node_granted_access
node_turned_away
node_combat_triggered
```

### Choices (`ch_`)

Use `ch_<action>` for simple choices, or `ch_<skill>_<action>` when the choice involves a skill check:

```
ch_honest               # truthful response
ch_vague                # evasive response
ch_wait                 # passive option
ch_wit_bluff            # Wit check, bluffing
ch_press_check          # active check to press further
ch_empathy_appeal       # Empathy check appeal
```

Avoid embedding the difficulty or node name in the choice ID — those belong in the data, not the ID.

### Skills *(no prefix)*

Skills use plain descriptive `snake_case`. These are player attributes and should read as nouns:

```
strength
endurance
wit
empathy
```

Multi-word skills: `arcane_knowledge`, `social_grace`, `street_sense`.

### Variables and flags *(no prefix)*

Variables use descriptive `snake_case`. Choose a naming pattern based on what the variable tracks:

| Pattern       | Use case                                       | Examples                                        |
|---------------|------------------------------------------------|-------------------------------------------------|
| `met_<npc>`   | Player has encountered this NPC                | `met_mira`, `met_faction_a`                     |
| `completed_<thing>` | A task or event has concluded           | `completed_intro_task`, `completed_character_creation` |
| `chose_<action>` | Player made a specific narrative choice    | `chose_cooperation`, `chose_deception`          |
| ~~`has_<item>`~~ | **Superseded.** Items are a first-class entity (`data/items.json`); ask `{ "type": "item", "item": "item_badge", "has": true }` against `GameState.inventory` rather than mirroring possession into a flag | — |
| `is_<state>`  | A boolean world/NPC state                      | `is_district_locked`, `is_gatekeeper_suspicious` |
| `<noun>_delta` / `<noun>_count` | Numeric counter              | `reputation_delta`, `bribe_count`               |

Flags should be past-tense or state-describing, **not** future-tense or imperative. `met_mira` ✓ vs `meet_mira` ✗.

---

## Importing from an external tool

When entities come from an external source (a wiki, a spreadsheet, a database):

1. Use the source record's human-readable title as the name to slugify.
2. Apply the prefix for the entity type being imported.
3. If the record already carries a Parlance id, use it verbatim — skip slugification.
4. Check the project for an existing entity with that id before creating: found ⇒ update,
   absent ⇒ create.
5. Write the generated id back to the source record so future syncs are stable.

That write-back is what keeps the id stable when someone later renames the source record.

---

## Summary of what auto-generation should produce

Given an entity type and a human-readable name, the auto-generator should:

```
input:  type=character, name="Mira Voss"
output: npc_mira_voss

input:  type=dialogue, npc="mira_voss", scene="Introduction"
output: dlg_mira_voss_introduction

input:  type=quest, name="Find the Smuggled Shipment"
output: task_find_smuggled_shipment

input:  type=flag, description="met Mira"
output: met_mira
```

These standards apply equally to ids written by hand in JSON files and those generated by tooling.
