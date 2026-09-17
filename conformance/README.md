# Parlance Conformance Suite

Language-agnostic test vectors for the Parlance runtime. Any implementation — C#, GDScript,
Lua, or another TypeScript port — can run these vectors to prove behavioral parity with the
reference implementation (`editor/core/src/runtime.ts`, which lives in Parlance's private
repository and is not published — these vectors exist precisely so a port never needs it).

> **License: MIT** (see `LICENSE-SPEC`). These files are meant to be copied —
> vendor them into your port and republish freely. The Parlance *editor* is
> licensed separately and is not covered by that grant.

## Files

Counts below drift every time vectors are added, so treat them as indicative and
`jq 'length' tooling/conformance/<file>.json` as authoritative.

| File | Function | Vectors |
|---|---|---|
| `evaluate.json` | `evaluate(condition, state, project)` | 53 |
| `apply_effect.json` | `applyEffect(effect, state, project)` | 27 |
| `resolve_check.json` | `resolveCheck(check, state, rng, defaultDice?, criticals?, project?)` | 24 |
| `step_dialogue.json` | `stepDialogue(dialogue, nodeId, state, project)` | 11 |
| `choose_choice.json` | `chooseChoice(dialogue, nodeId, choiceId, state, project, rng)` | 10 |
| `advance.json` | `advanceNode(dialogue, nodeId, state, project)` | 12 |
| `resolveCharacterDialogue.json` | `resolveCharacterDialogue(state, character, project, visited?)` | 16 |
| `nextContinuations.json` | `nextContinuations(state, project, visited, currentDialogueId)` — forced routing vs discovery | 4 |
| `progression.json` | `levelForXp` / `pointsEarned` / `availablePoints` / `investSkillPoint` / `recomputeSkills` | 13 |
| `resolve_quests.json` | `resolveQuests(state, project)` | 6 |
| `rng.json` | mulberry32(seed) output stream — the seeded PRNG ports must reproduce exactly | 6 |

### `migrate_ladders/` — vectors for the 0.13 → 0.14 ladder migration

`migrate_ladders/vectors.json` holds input projects (characters with the retired
`dialogues` ladder, dialogues with the retired `availableWhen`) beside the exact
`offer` objects the reference migration writes and the report lines it prints.
`tooling/scripts/migrate_ladders.py` (published beside the validator as
`validate/migrate_ladders.py`) is the reference; `editor/core/src/migrateLadders.ts`
is held to the same vectors. A port that converts 0.13 projects can replay them;
one that only reads 0.14 projects can ignore this directory.

### `validator/` — cases for the validator, not the runtime

The JSON files above pin *runtime* behavior. `validator/cases/` pins the
**validation rules** instead: each case is a small complete project with one
seeded defect and an `expected.json` saying which issue codes must (and must
not) be reported. They exist because this repo has two validators — the
reference one in `tooling/validate.py` and the one inside the editor — and two
implementations of one rule set drift silently: a rule that stops firing looks
exactly like data with no defects.

A port that ships its own validator can vendor these the same way, and check it
agrees. See `validator/README.md` for the case format.

Any runtime file may carry failure cases: a vector with `expectedError` (a substring
the thrown error's message must contain) instead of `expected` means the call must
throw. `advance.json` carries them for a missing `next` and for a ring of conditional
nodes whose gates all fail — both validator-guaranteed impossibilities, thrown rather
than absorbed because reaching them means the data never passed validation.

## Vector format

Each file is a JSON array. Each element is a self-contained test vector with these fields:

```
{
  "fn":          string          // which function to call
  "description": string          // human-readable label

  // Inputs — always present:
  "state":       SerializedGameState
  "dialogue":    Dialogue        // only for stepDialogue / chooseChoice / advanceNode
  "project":     MinimalProject  // any fn that takes one — evaluate, applyEffect,
                                 // stepDialogue, chooseChoice, resolveCharacterDialogue,
                                 // resolveQuests. Omit ⇒ treat as empty.

  // Function-specific inputs:
  "condition":   Condition       // evaluate only
  "effect":      Effect          // applyEffect only
  "check":       Check           // resolveCheck only
  "nodeId":      string          // stepDialogue / chooseChoice / advanceNode
  "choiceId":    string          // chooseChoice only
  "rng":         number | number[]  // resolveCheck and chooseChoice (active checks). Array = one value per die, in order
  "defaultDice": string          // resolveCheck only, optional — project rules.check.dice (absent ⇒ 1d20)
                                 // resolveCheck also takes "project" (optional) — required only when the
                                 // check declares modifiers whose `when` reads quest/questOutcome state

  // Expected output — exactly ONE of these two is present:
  "expected":      varies by fn  // see per-function sections below
  "expectedError": string        // advanceNode only — see Error cases below
}
```

## SerializedGameState

`GameState.inventory` is a `Set<string>` in the reference implementation, which is not
JSON-serializable. Serialized states use a sorted `string[]` instead:

```json
{
  "flags":           { "met_guard": true },
  "reputation":      { "guild": 3 },
  "skills":          { "wit": 5 },
  "counters":        { "stamina": 10 },
  "inventory":       ["key_card"],
  "questStages":     { "quest_main": "stg_enter" }
}
```

**Missing key defaults** (do NOT throw on absent keys — use these values):
- `flags[x]` → `false`
- `reputation[x]` → `0`
- `skills[x]` → `0`
- `counters[x]` → `0`
- `inventory.has(x)` → `false`
- `questStages[x]` → key absent (quest not yet advanced; treat as "not started")
- `relationships[x]` → `0`

**Older serialized states** that lack `questStages` should be treated as `questStages: {}`.

**State comparison:** when comparing output states, sort both `inventory` arrays before
comparing. The reference implementation emits a sorted inventory in `serializeState`.

## MinimalProject

Vectors include a `project` field wherever the function takes one. Which sub-object
matters depends on the call: `factions` for clamping reputation, `quests` for the `quest`
and `questOutcome` conditions and for `resolveQuests`. Treat a missing faction as having
no range limit (raw delta applied without clamping), and a missing quest/outcome as
false:

```json
{ "factions": { "guild": { "id": "guild", "name": "Guild", "summary": "s", "reputationRange": { "min": -10, "max": 10 } } } }
```

## Roll model (`resolveCheck`)

```
spec       = check.dice ? parseDice(check.dice) : (defaultDice ?? 1d20)   // "NdM"
faces      = [floor(rng() * spec.m) + 1, ...]      // spec.n of them, one rng() each, in order
roll       = sum(faces)
skillValue = state.skills[check.skill] ?? 0
total      = roll + skillValue
passed     = total >= check.difficulty
```

Precedence: per-check `check.dice` > the vector's `defaultDice` (the project's
`rules.check.dice`) > `1d20`. A vector's `rng` field is a single float for a one-die
roll, or an array with **one value per die, consumed in order** — the RNG call order is
part of the contract.

**Criticals** (`criticals: true` on a vector): a roll where every face shows the die
minimum ALWAYS fails, and one where every face shows the maximum ALWAYS succeeds,
overriding the total. Judged on individual faces, never the sum — 7 on 2d6 is 1+6 or
3+4, and neither is critical. `CheckResult.critical` is `"success" | "failure"` and is
absent on an ordinary roll.

## Expected output by function

### evaluate
```json
{ "expected": true }   // or false
```

### applyEffect
```json
{ "expected": SerializedGameState }
```
The expected state is the full post-effect state. Fields not touched by the effect are
carried through unchanged from the input state.

### resolveCheck
```json
{ "expected": { "passed": true, "roll": 5, "total": 10, "skillValue": 5, "dice": "1d20" } }
```
`bonus` and `appliedModifiers` are present **iff the check declares at least one
modifier** (0 / `[]` when none applied), so a check without modifiers produces the
same result it did before the feature existed. `total = roll + skillValue + Σbonus`
over every modifier whose `when` holds; a check with modifiers must be resolved with
a `project`. `critical` is present only on a critical roll (see the roll model).

### stepDialogue
```json
{ "expected": {
    "nodeId": "n_real",
    "visibleChoiceIds": ["ch_goto", "ch_check"],
    "onEnterEffectCount": 1,
    "onEnterEffects": [{ "type": "set_flag", "flag": "visited_start", "value": true }]
} }
```
`nodeId` is the **resolved** node's id — `stepDialogue` walks past nodes whose own
`showIf` fails (see `resolveNode` in `RUNTIME_CONTRACT.md`), so the node returned may not
be the one requested. **Check it when present**, by the same reasoning as the effects note
below: without it, a runtime that never implements the skip walk still passes every vector
whose skipped node carries no `onEnter` — the *typical* gated narration line, since a
conditional node is choiceless by construction. Older vectors omit the field.

`visibleChoiceIds` is the ordered list of choice ids that pass `showIf` filtering.
`onEnterEffects` is `node.onEnter` in order — the effects are returned but **not
applied**, which is the caller's responsibility.

`onEnterEffectCount` is that list's length, kept for ports already checking it.
**Check `onEnterEffects`, not the count.** The count alone is satisfied by
returning the *choice's* effects instead of the node's, by returning them in
reverse, or by returning the right number of nulls — all of which apply the
wrong thing to the player's state while reporting conformance.

### chooseChoice
```json
{
  "expected": {
    "nextNodeId": "node_win",
    "newState": SerializedGameState,
    "checkResult": { "passed": true, "roll": 5, "total": 10, "skillValue": 5 }
  }
}
```
`checkResult` is only present for active check vectors. `nextNodeId` is `null` for
terminal choices (no `goto`, no `check`).

### advanceNode
```json
{ "expected": { "nextNodeId": "node_end", "newState": SerializedGameState } }
```
Resolves `node.next` — the choiceless counterpart of `chooseChoice`, for listen-only beats
(ambient chatter, narration) that advance with no player choice. Unlike `chooseChoice`,
**no effects are applied and no check is resolved** — `next` carries neither — so
`newState` always equals the input `state`, byte-for-byte, even when the TARGET node has
`onEnter` effects: those are the caller's responsibility on arrival, exactly as with
`stepDialogue`'s `onEnterEffects` / a `goto` arrival, never `advanceNode`'s own job. The
returned `nextNodeId` is **post-skip**: the target is resolved through any failing node
`showIf` gates, so it names the node the player will actually see. One call still reveals
exactly one *shown* beat — skipped nodes are inert, not beats.

**Error cases.** A vector with `expectedError` instead of `expected` means the call must
throw; `expectedError` is a substring the thrown error's message must contain. This is the
one function in the suite with a failure contract — call it only on a node that declares
`next` (the validator's FLOW checks and the client both prevent constructing the call
otherwise); reaching it anyway is a bug upstream, not a `Problem`/result-object case.

### resolveCharacterDialogue
```json
{ "character": Character, "project": { "dialogues": {…} }, "visited": ["d_x"], "expected": "d_confront" }  // or null
```
Saliency model (ws 17). Gather the dialogues whose `offer.character ?? speakerId` equals
`character.id`; the presence of `offer` is the opt-in (a dialogue without it is never a
candidate). Keep the ones whose `offer.when` passes (absent = always); when a `visited` set
is given, drop the non-replayable ones already in it. Pick the winner by:

1. `offer.priority ?? 0` — descending (tier)
2. condition specificity of `offer.when` — descending (leaf 1, `all` sum, `any` **min**, `not` operand, absent 0)
3. `id` — ascending, ordinal / UTF-16 code-unit compare (NOT locale collation)

Return `null` if no offer is eligible. The vector carries the offered dialogues under
`project.dialogues` and an optional `visited` list; array order is NOT significant anywhere.

> **Feed model.** `set_active_dialogue` sets the flag `active_dialogue__{character}` (see
> `apply_effect.json`); a forced dialogue is a tier-1 offer whose `when` reads that flag.
> There is no `activeDialogues` map in `SerializedGameState`; states carrying one ignore it.

### progression
Each vector carries a `config` (the `progression.json` shape) and dispatches on `fn`:
```json
{ "fn": "levelForXp",       "config": {…}, "xp": 450,              "expected": 3 }
{ "fn": "pointsEarned",     "config": {…}, "xp": 450,              "expected": 3 }
{ "fn": "availablePoints",  "config": {…}, "state": {…},           "expected": 2 }
{ "fn": "investSkillPoint", "config": {…}, "state": {…}, "skillId": "wit", "expected": SerializedGameState }
{ "fn": "recomputeSkills",  "config": {…}, "state": {…},           "expected": SerializedGameState }
```
`investSkillPoint` is a guarded no-op (returns the input state unchanged) when no point is
available or the skill is already at `maxSkill`. `recomputeSkills` sets each skill to
`min(startingSkills + skillPointsSpent, maxSkill)`.

### resolveQuests
```json
{ "project": { "quests": {…} }, "expected": { "state": SerializedGameState, "firings": [{ "quest": "q", "kind": "outcome", "id": "out_x" }] } }
```
Fires condition-gated stage/outcome effects once each (recorded in `questFired`), to a
fixpoint, in deterministic order (quests sorted by id; stages then outcomes in array
order). Items with effects but no condition never fire. `firings` lists what fired, in
order; `expected.state.questFired` is the sorted record.

> **Contract change.** `SerializedGameState` gained `xp` (integer) and `skillPointsSpent`
> (`skillId → integer`). `grant_xp` (see `apply_effect.json`) adds to `xp`. Older serialized
> states lacking these fields are treated as `xp: 0` / `skillPointsSpent: {}`.
> `questFired` (sorted `string[]`) records fired quest items; omitted when empty.

## Running in your language

1. Parse the JSON array.
2. For each vector, deserialize `state` by converting `inventory: string[]` to your
   language's equivalent of `Set<string>`.
3. Call your implementation of the named function with the provided inputs.
4. If the vector carries `expectedError` (advanceNode only): assert the call throws /
   returns an error whose message contains that substring, and stop — there is no output
   state to compare.
5. Otherwise, serialize the output state (if any) back to `{ ..., inventory: string[] }`
   with the inventory array sorted.
6. Assert the result matches `expected` using deep equality.

The reference runner (TypeScript/Vitest) lives in Parlance's private repository; it is
named here only for provenance. These vectors are self-describing precisely so a port
never needs to read it.
