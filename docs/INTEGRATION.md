# Parlance Integration Guide

How to drive Parlance narrative data from your game. The `data/` directory format is the
runtime format — there is no export step. This guide covers loading the data, using the
runtime API, and validating your implementation against the conformance suite.

---

## What you get

Every entity in a Parlance project is a JSON file (or an entry in a flat JSON array for
skills and variables). The same files the editor writes are what the runtime reads.
`@parlance/core` defines the authoritative behavioral contract — what the data *means*
when executed. A port in any language must implement the same semantics; use the
conformance suite in `tooling/conformance/` to verify.

---

## Data layout

```
data/
  skills.json          { "skills": [ { "id": "wit", ... }, ... ] }
  variables.json       { "variables": [ { "id": "seen_intro", "kind": "flag", ... }, ... ] }
  characters/
    npc_gatekeeper.json
    player.json
  dialogues/
    dlg_gatekeeper_intro.json
  factions/
    faction_a.json
  quests/
    quest_main.json
  locations/
    loc_checkpoint.json
  endings/
    ending_success.json
  codex/
    codex_the_accord.json
  items.json           { "items": [ { "id": "item_lantern", "name": "Stable Lantern" }, ... ] }
  portraits.json       { "portraits": [ ... ] }
```

**A shipping game loads `data/` and nothing else.** Route and snapshot fixtures live
in a sibling directory, because they are regression tests rather than story:

```
tests/
  routes/              rt_*.json    — scripted playthroughs with assertions
  snapshots/           snap_*.json  — saved states to resume from
```

Your runtime never needs to read `tests/`; it exists for the editor, `parlance route`,
and CI. Both directory names can be overridden in `parlance.config.json` (`data`,
`tests`) if a project wants a different layout.

**File name = entity id.** `dlg_gatekeeper_intro.json` contains the entity with
`"id": "dlg_gatekeeper_intro"`. Skills and variables are stored as named arrays in flat
files rather than per-entity files.

See [`NAMING_STANDARDS.md`](NAMING_STANDARDS.md) for id conventions. See
[`RUNTIME_CONTRACT.md`](RUNTIME_CONTRACT.md) for the full behavioral spec.

---

## Loading

Parse each JSON file and assemble a `ProjectData` object:

```ts
import type { ProjectData, Skill, Variable, Item, Faction, Character, Dialogue, Quest, Location, Ending, Codex } from "@parlance/core";

const project: ProjectData = {
  skills:     indexById(skillsJson.skills),       // array → Record<id, Skill>
  variables:  indexById(variablesJson.variables), // array → Record<id, Variable>
  items:      indexById(itemsJson.items),         // array → Record<id, Item>
  factions:   loadDir("factions"),
  characters: loadDir("characters"),
  dialogues:  loadDir("dialogues"),
  quests:     loadDir("quests"),
  locations:  loadDir("locations"),
  endings:    loadDir("endings"),
  codex:      loadDir("codex"),
};
```

**`items` is for display, not for execution.** No runtime function reads it: possession
lives entirely in `GameState.inventory`, `give_item` adds an id, and the `item` condition
asks whether that set contains one — none of which consults the registry. You need
`data/items.json` to show a player "Stable Lantern" instead of `item_lantern`, and you can
omit it if your game never renders an inventory. Worth stating because the shape invites
guessing in both directions.

**`loreFiles` field:** omit it from your load — it is a `Set<string>` used by editor
tooling, is not JSON-serializable, and no runtime function reads it.

**`GameState.inventory`** is a `Set<string>` in TypeScript. **`GameState.questStages`**
maps `questId → current stage id` and is updated by `advance_quest` effects. If you
are storing or transmitting state as JSON, use `serializeState` / `deserializeState`
from `@parlance/core` to convert — the serialized form has `inventory: string[]`
(sorted) and `questStages: Record<string, string>`. See
[`tooling/conformance/README.md`](conformance/README.md) for the full serialized format
all ports must match.

---

## Runtime API

All functions are pure — no filesystem, no DOM, no clock. Inject `rng` for deterministic
tests.

```ts
import {
  createDefaultState,
  evaluate,
  applyEffect,
  applyEffects,
  resolveCheck,
  stepDialogue,
  chooseChoice,
  advanceNode,
  resolveCharacterDialogue,
  resolveQuests,
  serializeState,
  deserializeState,
} from "@parlance/core";
```

**`resolveCharacterDialogue` is how you decide what a character says next**, and a port
that omits it has no answer to that question. Walk the character's ordered `dialogues`
ladder and take the first rung whose `showIf` passes; an absent `showIf` always matches.
It is the canonical discovery path and the only one with conformance vectors. See
RUNTIME_CONTRACT's ladder section — `selectDialogue` (dialogue-level `availableWhen`) is
an escape hatch, not a second system to implement first.

### `createDefaultState(project) → GameState`

Build a starting state from project defaults. Flags and counters are initialised from
`variables.json` `default` fields. Reputation starts at the midpoint of each faction's
declared range. Inventory is empty.

### `evaluate(condition, state, project) → boolean`

Test a `Condition` against a `GameState`. Handles all condition types: `flag`,
`reputation`, `relationship`, `skill`, `item`, `counter`, `quest`, `questOutcome`,
`all`, `any`, `not`. Missing keys default to `false` / `0` — never throw. `project` is
required because some condition types are not answerable from state alone (`quest`
needs stage order; `questOutcome` needs the outcome's own `reachedWhen`), matching
`applyEffect`'s signature.

### `applyEffect(effect, state, project) → GameState`

Apply one `Effect`, returning a new immutable `GameState`. The input is never mutated.
Reputation is clamped to the faction's declared `reputationRange` after each adjustment;
`adjust_relationship` is **unclamped** (a character declares no range).

**`advance_quest` writes `questStages[quest] = toStage`.** It records the stage id and
nothing else — it does not evaluate `completeWhen` or fire outcome effects (that is
`resolveQuests`, which the host runs). Your port must perform this write: the `quest`
condition reads `questStages`, so a port that treats `advance_quest` as a no-op will
silently evaluate every quest condition as false.

### `applyEffects(effects, state, project) → GameState`

Apply a list of effects in left-to-right order, threading state through each call.

### Cutscenes: `pendingCutscene` + `clearPendingCutscene(state)`

A `play_cutscene` effect sets `state.pendingCutscene` to the cutscene id (default:
absent; re-firing overwrites — last write wins). The runtime never plays anything —
your engine's cutscene controller consumes it:

1. Detect the pending cutscene — read `state.pendingCutscene` directly, or call
   `nextContinuations(...)`, which surfaces it *first* as a
   `{ kind: "cutscene", cutscene }` continuation ahead of any dialogue offers.
2. Load and play the manifest's `asset` (an opaque engine asset key —
   Parlance never validates it; a mismatch should be a loud engine-side error).
3. On completion (or skip, if `skippable`): apply `cutscene.effectsOnComplete` via
   `applyEffects`, clear the field with `clearPendingCutscene(state)`, then start
   `cutscene.entersDialogue` if the manifest chains into one.

Cutscenes are **atomic**: either unplayed (`pendingCutscene` set, nothing applied) or
played (effects applied, field cleared). Never serialize partial playback — saving
mid-cutscene just replays it on load. `pendingCutscene` round-trips through
`serializeState`/`deserializeState` (present only while queued; omitted once cleared).

### `resolveCheck(check, state, rng) → CheckResult`

Roll an active skill check. Dice are `NdM`, defaulting to `1d20`: each die is
`floor(rng() * M) + 1` and they are summed, so a `2d6` check consumes **two** `rng()`
calls in order — the call order is part of the contract. Precedence is per-check
`check.dice` > project `rules.check.dice` > `1d20`. `total = roll + skillValue`,
`passed = total >= difficulty`. `rng()` must return a value in `[0, 1)`. With
`rules.check.criticals` on, an all-minimum roll always fails and an all-maximum roll
always succeeds, judged per face rather than on the sum. Passive checks are
display-only — pass a plain `goto` through `chooseChoice` instead of calling this.

```ts
type CheckResult = {
  passed: boolean; roll: number; total: number; skillValue: number;
  dice: string; critical?: "success" | "failure";
};
```

### `stepDialogue(dialogue, nodeId, state, project) → StepResult`

Get the current node and filter `node.choices` by `showIf` conditions. Returns
`onEnterEffects` but does **not** apply them — call `applyEffects(onEnterEffects, state,
project)` on first arrival (not on replay).

```ts
type StepResult = { node: DialogueNode; visibleChoices: Choice[]; onEnterEffects: Effect[] };
```

### `chooseChoice(dialogue, nodeId, choiceId, state, project, rng?) → ChoiceOutcome`

Resolve a player's choice: apply `choice.effects`, resolve the check (active checks only),
return the next node id and updated state. Passive checks follow `choice.goto` without
rolling. Terminal choices (no `goto`, no `check`) return `nextNodeId: null`.

```ts
type ChoiceOutcome = {
  nextNodeId: string | null;
  newState: GameState;
  checkResult?: CheckResult;   // only for active checks
};
```

### `advanceNode(dialogue, nodeId, state) → AdvanceOutcome`

Resolve a node's `next` pointer — the choiceless counterpart of `chooseChoice`, for a
listen-only beat (ambient chatter, narration) that advances with no player choice. Unlike
`chooseChoice`, no effects are applied and no check is resolved (`next` carries neither);
`newState` always equals the input `state`. **Throws** if the node has no `next`, or if
`next` targets a node absent from the dialogue — call it only on a node your validator/UI
has already confirmed declares `next`. Does not chase further `next` pointers: one call is
exactly one hop.

```ts
type AdvanceOutcome = { nextNodeId: string; newState: GameState };
```

The target's `onEnter` is the caller's job, exactly as with `chooseChoice` — call
`applyEffects(...)` after arriving. That symmetry is what makes an advance-arrival and a
goto-arrival at the same node produce identical state (see `tooling/conformance/advance.json`
for the vectors that pin this down).

For the full decision table (roll model, clamp ranges, evaluation order, effect
semantics), see [`RUNTIME_CONTRACT.md`](RUNTIME_CONTRACT.md).

---

## Conformance suite

`tooling/conformance/` contains one JSON array per function (`advance.json` is
`advanceNode`'s). Load each file, run your implementation against the vectors, and compare
outputs. Per-file counts live in that directory's README — `jq 'length' <file>.json` is
authoritative. `advance.json` is the one file where some vectors carry `expectedError`
instead of `expected` — see its README section before assuming every vector is an
equality check.

See [`tooling/conformance/README.md`](conformance/README.md) for:
- The vector format
- `SerializedGameState` (inventory as sorted `string[]`)
- The roll model formula
- State comparison rules (sort inventory before comparing)

The TypeScript reference runner lives in Parlance's private repository; the vectors are
self-describing so a port never needs it.

### Pinning and re-pinning a port

An engine port should pin the contract, not track `main`. The convention:

1. Record the pin in the consuming repo — the Parlance tag, the commit sha, and the repo —
   and read it back in a test so the pin is asserted, not just documented.
2. Copy `tooling/conformance/` into the port at that ref. It is a **pinned copy, not a
   fork**: never hand-edit the vectors to make a port pass.
3. Assert that every pinned vector file has a runner. An unexecuted vector looks like
   coverage and is not.
4. To move the pin: re-copy `tooling/conformance/` from the new ref, update the recorded
   tag/sha, run the port's suite, and fix whatever goes red in the port.

Releases are a `chore(release): X.Y.Z` commit plus a `vX.Y.Z` tag; the version of record is
`editor/package.json`. Prefer pinning a tag over a bare sha so the pin is legible.

---

## Hook model

`@parlance/core` is pure: it returns new states but fires no events. Your game engine
is responsible for reacting to state changes. The following events are the natural wiring
points:

| When | What your engine should do |
|---|---|
| After `stepDialogue` | Render `node.text` and `visibleChoices` to the player; call `applyEffects(onEnterEffects, ...)` on first arrival |
| After `resolveCheck` | Show dice-roll UI: display `roll`, `skillValue`, `total`, `passed` |
| After `applyEffect` / `applyEffects` | Sync the changed state back to your game world (update inventory UI, reputation bar, etc.) |
| After `advance_quest` | The runtime has already written `questStages[quest]`; mirror it into your own quest UI if you keep one. Then call `resolveQuests` so stage/outcome effects fire |
| When `chooseChoice` returns `nextNodeId: null` | The dialogue is over; dismiss the dialogue UI |
| When the current node has `next` set | Render no choice list — offer a single "continue" input instead; on activation call `advanceNode`, then apply the target's `onEnter` exactly as you would after a `goto` arrival |

**`resolveQuests` is the one thing the runtime will not do for you.** `advance_quest`
records the stage; the effects authored on stages (`onComplete`) and outcomes (`effects`)
fire only when the host calls `resolveQuests(state, project)` after each state transition
it causes. A host that never calls it will find stage effects — and therefore most quest
XP — simply never happen. See `RUNTIME_CONTRACT.md` § Quest resolution.

---

## Saves: the loop between your engine and the editor

Your engine writes saves. Parlance reads snapshots. They are the same shape on purpose —
an envelope around a `SerializedGameState` — so the two can be traded back and forth
instead of each being a dead end.

**Write your save as an envelope.** Anything your host needs beside the state (where the
player is standing, when the file was written, which of your own subsystems was in what
mode) belongs on the envelope, not inside `state`. Parlance reads what it recognises,
reports what it does not, and never rejects a save for carrying your own bookkeeping.

```json
{
  "schemaVersion": 1,
  "location": "loc_checkpoint",
  "spawn": "sp_main",
  "savedAtUtc": "2026-08-20T11:02:31Z",
  "visitedDialogueIds": ["dlg_gatekeeper_intro"],
  "state": { "...": "SerializedGameState" }
}
```

**Carry `visitedDialogueIds`.** It is the one envelope field the runtime actually reads:
discovery hides a non-`replayable` dialogue that is already in it. A save that omits it
comes back as a player who has heard nothing. See `RUNTIME_CONTRACT.md` § Saves,
snapshots and the visited set.

**Import a save as a snapshot:**

```bash
parlance save import path/to/slot1.json --id snap_bug_41 --name "Bug 41 repro"
```

That writes `tests/snapshots/snap_bug_41.json`, canonically serialized, carrying the
visited set. The editor does the same thing from the playtest panel's **Import save
file…** button.

An import is **refused when the save names content this project does not have** — an
unregistered flag, an unknown item, a dialogue from another build. That rule mirrors the
validator: each of those is a validation error on a snapshot, so importing anyway would
write a fixture that fails validation the moment it lands. A save from a newer build
imports cleanly in the checkout that has the content it refers to. What the validator
does not check (a text variable, a relationship) comes back as a warning and imports
fine.

**Then start a route from it**, which is the point of the whole hop:

```json
{
  "id": "rt_bug_41",
  "dialogueId": "dlg_gatekeeper_intro",
  "startSnapshot": "snap_bug_41",
  "steps": [{ "choiceId": "ch_honest" }]
}
```

```bash
parlance route rt_bug_41
```

A bug found in play is now a file in the repo that fails CI until it is fixed, rather
than twenty minutes of clicking that only one person knows how to repeat.

**The reverse direction — route → save — is yours to implement**, and worth it: walk a
route with your own runtime, take its end state, and write it as a save. "Open the game
standing at the checkpoint having just been screened" becomes exact and repeatable. Carry
the walk's visited set into that save, or the reopened game will offer content the walk
already spent. What is *not* possible in any engine is save → route: a route is a path, a
save is a position, and the steps that produced a state are not recoverable from it.

---

## Quick start (TypeScript / Node)

```ts
import { readFileSync, readdirSync } from "fs";
import { join } from "path";
import { createDefaultState, stepDialogue, chooseChoice, applyEffects } from "@parlance/core";
import type { ProjectData, Dialogue } from "@parlance/core";

// 1. Load project (sketch — adapt to your file layout)
const project = loadProject("./data");

// 2. Initial state with custom skill values
const state = { ...createDefaultState(project), skills: { wit: 7 } };

// 3. Step through a dialogue
const dlg = project.dialogues["dlg_gatekeeper_intro"]!;
let nodeId = dlg.entry;
let currentState = state;

const step = stepDialogue(dlg, nodeId, currentState);
currentState = applyEffects(step.onEnterEffects, currentState, project);

console.log(step.node.text);
for (const c of step.visibleChoices) console.log(`  [${c.id}] ${c.text}`);

// 4. Player picks a choice
const outcome = chooseChoice(dlg, nodeId, "ch_wit_bluff", currentState, project, Math.random);
currentState = outcome.newState;
if (outcome.nextNodeId) nodeId = outcome.nextNodeId;
```

