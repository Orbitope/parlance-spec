# Parlance Runtime Contract

This document defines the **authoritative runtime behavior** of Parlance narrative data —
what the data *means when executed*. The playtest surface, engine ports, and all conformance
tests derive from these decisions. Where this document conflicts with intuition, this
document wins.

> **On `editor/core/src/...` paths.** They name Parlance's own reference
> implementation, which is **not** part of the published spec and is not
> something you can open from this repository. They are cited so a behaviour can
> be traced to where it is decided; nothing here depends on reading them. For a
> port, `conformance/` is the executable contract — if the vectors pass, the port
> is correct regardless of how the reference does it.

---

## GameState

```ts
type GameState = {
  flags:           Record<string, boolean>;   // variable kind:"flag"
  reputation:      Record<string, number>;    // factionId → value, clamped
  skills:          Record<string, number>;    // skillId → value
  counters:        Record<string, number>;    // variable kind:"counter"
  inventory:       Set<string>;              // item ids held (data/items.json)
  questStages:     Record<string, string>;   // questId → current stage id
  relationships:   Record<string, number>;   // characterId → standing, unclamped
  xp:              number;                    // total XP earned this playthrough (monotonic)
  skillPointsSpent: Record<string, number>;  // skillId → points invested
  texts:           Record<string, string>;   // variable kind:"text" → value substituted into {placeholders}
  questFired?:     Set<string>;              // quest stage/outcome effects already fired (once-only); absent when none
  pendingCutscene?: string;                  // cutscene id requested via play_cutscene; absent when none pending
};
```

**Missing key defaults:**
- `flags[x]` → `false`
- `reputation[x]` → `0`
- `skills[x]` → `0`
- `counters[x]` → `0`
- `inventory.has(x)` → `false`
- `questStages[x]` → key absent (quest has not been advanced)
- `relationships[x]` → `0`
- `xp` → `0` (no XP earned yet)
- `skillPointsSpent[x]` → `0` (no points invested in that skill)
- `texts[x]` → key ABSENT (deliberately not `""` — see Text interpolation)
- `questFired` → empty (no quest effects fired yet)
- `pendingCutscene` → `undefined` (no cutscene requested / already cleared)

**Initial state** (`createDefaultState`):
- Flags initialised from `variables.json` `default` field; missing `default` → `false`.
- Counters initialised from `default` field; missing → `0`.
- Items: not in inventory by default (no default value).
- Reputation: starts at `floor((min + max) / 2)` of the faction's `reputationRange`.
- Skills: empty (caller sets from character stats for a real session).
- `questStages`: empty object `{}` — no quests have been advanced.
- `texts`: seeded from each `kind:"text"` variable's `default`. A text variable
  with **no** default is OMITTED, not set to `""`.
- `pendingCutscene`: absent — no cutscene queued.

---

## evaluate(condition, state, project): boolean

`project` is passed for the same reason `applyEffect` takes it: some conditions are
not answerable from state alone. Both entry points therefore share one calling
convention, so a port implements one, not two.

| Condition type | Semantic |
|---|---|
| `flag` | `(state.flags[id] ?? false) === condition.value` (exact boolean equality) |
| `reputation` | `compareOp(state.reputation[id] ?? 0, op, value)` |
| `skill` | `compareOp(state.skills[id] ?? 0, op, value)` |
| `item` | `state.inventory.has(id) === condition.has` |
| `counter` | `compareOp(state.counters[id] ?? 0, op, value)` |
| `relationship` | `compareOp(state.relationships[characterId] ?? 0, op, value)` — the per-character counterpart of `reputation` |
| `quest` | `compareOp(order(state.questStages[quest]), op, order(condition.stage))` — compares stage ORDER, not id equality, so `>= stg_x` means "at or past". An unadvanced quest is before every stage; an unknown quest or stage is false for every op. See §Decisions. |
| `questOutcome` | True when the named outcome's own `reachedWhen` evaluates true against current state. Deliberately **not** a `questFired` lookup — see §Decisions. An outcome with no `reachedWhen` is never reached; an unknown quest/outcome, or a reference cycle, is false. |
| `all` | Left-to-right short-circuit AND (`every`) |
| `any` | Left-to-right short-circuit OR (`some`) |
| `not` | Logical NOT of inner condition |

**Op semantics:** `>=`, `<=`, `==`, `>`, `<` are strict numeric comparisons.

---

## applyEffect(effect, state, project): GameState

All calls return a **new** immutable `GameState`; the input is never mutated.

| Effect type | Semantic |
|---|---|
| `set_flag` | `flags[flag] = value` |
| `adjust_reputation` | `reputation[faction] += delta`, then clamp to `[faction.reputationRange.min, faction.reputationRange.max]`. No clamp if faction not found. |
| `adjust_counter` | `counters[counter] += delta`. No clamping. |
| `give_item` | `inventory.add(item)` |
| `take_item` | `inventory.delete(item)` (no-op if not held) |
| `advance_quest` | `questStages[quest] = toStage`. Records the quest's current stage in `GameState`. Stage evaluation (e.g. `completeWhen`) is the caller's responsibility — the runtime only stores the stage id. |
| `grant_xp` | `xp += amount`. Monotonic total-earned XP; levels/points are DERIVED from it (never a spendable balance). `amount` should be positive (validator warns on ≤ 0). Authored on quest outcomes by convention. |
| `set_active_dialogue` | `flags["active_dialogue__" + character] = true` (feed model — no separate `activeDialogues` map). The character's ladder carries a high-priority rung gated on this flag; the effect's `dialogue` field is metadata for tooling/validation. Clear it with a normal `set_flag … false` (or `clearActiveDialogue`) to fall through again. |
| `play_cutscene` | `pendingCutscene = cutscene`. The runtime only records the request — it never plays a cutscene. See "Cutscene playback" below. |
| `set_text` | `texts[variable] = value`, last-write-wins. `value` is always a literal — capturing free-text player input is the engine's job, which calls this effect with whatever string it collected. See "Text interpolation" below. |

**Multiple effects** are applied left-to-right, threading state through each call.

---

## resolveCheck(check, state, rng, defaultDice?): CheckResult

Active checks only. Passive checks are display-only and use a plain `goto`.

```
spec       = check.dice ? parseDice(check.dice) : (defaultDice ?? 1d20)   // "NdM"
roll       = sum over spec.n of (floor(rng() * spec.m) + 1)   // consumes spec.n rng() calls, in order
skillValue = state.skills[check.skill] ?? 0
total      = roll + skillValue
passed     = total >= check.difficulty
CheckResult = { passed, roll, total, skillValue, dice: "NdM" }
```

**Dice.** Notation is `NdM` (N dice of M sides, summed; N ≥ 1, M ≥ 2). The skill value is
the modifier, not part of the notation. Precedence: per-check `check.dice` > project
`rules.check.dice` (passed as `defaultDice`) > engine default `1d20`. Absent config
reproduces the historical d20 behaviour exactly.

**Criticals (`rules.check.criticals`, default OFF).** When enabled, a roll where
**every die shows its minimum** ALWAYS fails and one where **every die shows its
maximum** ALWAYS succeeds — regardless of skill or difficulty. This is the familiar
snake-eyes / boxcars rule, and it is what keeps a tight bell curve (2d6)
playable: without it a specialist auto-passes and a novice cannot attempt.

```
faces      = [floor(rng() * m) + 1, ...]   // n of them, in order
roll       = sum(faces)
passed     = total >= difficulty
if criticals and every face == m:  passed = true,  critical = "success"
if criticals and every face == 1:  passed = false, critical = "failure"
```

Decided on **faces, not the total** — 7 on 2d6 is 1+6 or 3+4, and only one of
those is a critical. `CheckResult.critical` is `"success" | "failure"`, and is
**absent** on an ordinary roll. Criticals default off because enabling them
changes every check outcome; it is a per-project opt-in, not a silent change.

**RNG ordering is part of the contract.** Each die consumes one `rng()` call, left to right;
a port that rolls `2d6` must call `rng()` twice in that order. `rng()` must return `[0, 1)`.
Inject a seeded RNG for deterministic tests. See `tooling/conformance/resolve_check.json`
(now carries a `dice` field and array-valued `rng` sequences for multi-die vectors).

---

## stepDialogue(dialogue, nodeId, state, project): StepResult

1. Locate the `DialogueNode` by `nodeId`; throw if not found.
2. Filter `node.choices` to those where `!choice.showIf || evaluate(choice.showIf, state, project)`.
3. Interpolate `node.text` and each visible choice's `text` (see "Text interpolation").
4. Return `{ node, visibleChoices, onEnterEffects: node.onEnter ?? [] }`.

**The returned node and choices are copies when — and only when — a placeholder was
actually substituted.** The authored entity objects are never mutated; when a string
contains no placeholder the original object is returned by reference, so callers that
compare node identity to detect edits keep working.

**Caller responsibility:** `onEnterEffects` are returned but NOT applied. The caller decides
when to apply them (on first arrival; not on replay). Call `applyEffects(onEnterEffects, state, project)` to advance state.

---

## chooseChoice(dialogue, nodeId, choiceId, state, project, rng): ChoiceOutcome

1. Apply `choice.effects` to state via `applyEffects`.
2. If `choice.check.mode === "active"`: call `resolveCheck`, advance to `onSuccess` / `onFailure`.
3. If `choice.goto` present (including passive check choices): advance to `goto` node.
4. Neither: `nextNodeId = null` (terminal choice on an `isEnd` node).

Passive checks (`mode: "passive"`) are treated as a plain `goto` — no roll, just the reveal
effect. They never produce a `checkResult` in the return value.

`ChoiceOutcome` carries no player-facing strings, so there is nothing to interpolate here —
text reaches the UI through `stepDialogue`, which does interpolate.

---

## advanceNode(dialogue, nodeId, state): AdvanceOutcome

Resolves `DialogueNode.next` (N2) — the choiceless counterpart of `chooseChoice`, for
listen-only beats (ambient chatter, narration) that advance with no player choice.

1. Locate the node by `nodeId`; **throw** if not found.
2. **Throw** if the node has no `next` — the validator's FLOW checks and the client both
   prevent constructing this call otherwise, so reaching it anyway is a bug upstream, and
   silence would hide it. This is the one function in the runtime contract with a throw-only
   failure mode instead of a `Problem`/result-object encoding — see the conformance suite's
   `expectedError` convention for `advance.json`.
3. Locate `next`'s target node in the same dialogue; **throw** if it doesn't exist.
4. Return `{ nextNodeId: target.id, newState: state }` — unchanged.

**No effects are applied and no check is resolved.** `next` carries neither (unlike a choice,
which may carry both) — effects live on the TARGET's `onEnter`, exactly as they do for a
`goto` arrival. `advanceNode` does not apply that `onEnter` either: **caller responsibility**
applies here identically to `stepDialogue`/`chooseChoice` — call
`applyEffects(target.onEnterEffects, state, project)` after arriving, on first arrival only.
This is what makes an advance-arrival and a goto-arrival at the same node produce identical
state — the single most important property this function has, and the one the conformance
suite's parity vectors exist to lock down.

**Does not chase further `next` pointers.** One call resolves exactly one hop; a chain of N
`next`-linked nodes takes N calls. Every beat stays individually revealable, skippable,
savable, and rewindable — a runtime that auto-chased would collapse a whole ambient run into
one uninterruptible jump and make mid-run rewind meaningless.

**Structural invariant, enforced by the validator (FLOW), not by this function:** a node has
`next` XOR a non-empty `choices` XOR `isEnd`. `advanceNode` does not re-check this — it only
requires that `next` itself resolves. A node with both `next` and `choices` populated (an
invalid transient authoring state) still resolves `next` correctly if called; the FLOW error
is what tells the author to fix the data, not a runtime guard.

**GameState is unchanged by N2.** No field was added to support `next`/`advanceNode` — see
the GameState section above.

**Editor-only session note:** `editor/core/src/playSession.ts`'s `advance()` action is the
one call site that wraps `advanceNode` for the interactive Play surface, mirroring `choose()`.
It is NOT part of this contract (playSession is editor tooling, not something a port
implements) but is worth knowing about for one reason: because its RNG stream is keyed on
`steps.length` (`rngForStep(seed, stepIndex)`), inserting an advance step shifts every
downstream roll's index. Adding a `next` chain into NEW content is fine; adding one into the
MIDDLE of existing content that has recorded routes/goldens renumbers their rolls.

---

## Node speaker resolution — resolveSpeaker / effectiveSpeakerId / resolvePortrait (N1)

A dialogue has a default speaker; a node MAY override it for that one line — the multi-speaker
feature that lets a single dialogue interleave NPCs, narration, and skill-voiced beats (a
skill speaking as an inner voice). All three functions live in `editor/core/src/speaker.ts` and are the ONE place
this logic exists — every consumer (validator, reference index, transcript, client canvas,
`PlayPanel`, host draft context) calls through them rather than re-deriving any of it.

**`effectiveSpeakerId(dialogue, node): Id | undefined`** — `node.speakerId ?? dialogue.speakerId`.
Named so nothing else re-implements this one `??`.

**`resolveSpeaker(project, dialogue, node): ResolvedSpeaker`** — resolves the effective id to
a concrete entity:

```
1. effectiveSpeakerId(dialogue, node)
2. undefined                          → { kind: "narration" }   (no speakerId set anywhere)
3. id matches a character             → { kind: "character", character }
4. else id matches a skill            → { kind: "skill", skill }   (skill-voiced beat)
5. else (id matches neither)          → { kind: "narration" }
```

"No speakerId" and "a dangling speakerId" both resolve to narration here — this function does
not distinguish them. The validator is what turns a dangling id into an error (REF); an id
present in BOTH the character and skill maps is also a validator error (ambiguous), which
`resolveSpeaker` doesn't detect either — it simply prefers character in that unreachable-in-
valid-data case. Dialogue-level `speakerId` stays character-only (it doubles as dialogue
ownership for `selectDialogue`/ladder resolution); only the NODE level may name a skill.

**`resolvePortrait(project, dialogue, node): Id | null`** (D10) — the portrait to render:

```
1. node.portrait                              (per-line expression override) — return if set
2. resolveSpeaker(...).character.portrait     (only when the speaker is a character) — return if set
3. null                                       — legal and expected for a skill or narration
                                                 speaker; the presentation layer decides whether
                                                 to hold the last character portrait or clear it.
```

This supersedes `getPortrait` below for anything that has gone through N1 — `getPortrait`
takes an already-resolved `Character` and never itself performs the node/dialogue speaker
fallback, so it cannot express "the speaker is a skill, therefore no portrait." `getPortrait`
is kept for backward compatibility; new code should call `resolvePortrait`.

---

## getPortrait(node, character): string | null

Resolves which portrait registry id (`data/portraits.json`) to render for a dialogue node,
GIVEN an already-resolved `Character` — it does not itself compute
`node.speakerId ?? dialogue.speakerId` or handle a skill/narration speaker. Prefer
`resolvePortrait` (above), which does the full resolution end to end.

```
1. node.portrait        (per-line expression override) — return if set
2. character.portrait   (the character's default)       — return if set
3. null                 — no portrait resolved (OK; not every character has one authored yet)
```

Named characters must have `character.portrait` set once portraits are in play — validation
does not fall back to a shared base portrait (explicit is better; see PORT validator, below).
A project that authors only one portrait per character never sets `node.portrait`; the
field exists so per-line expressions can be introduced later without a schema change.

**PORT validator family** (`editor/core/src/validator.ts`, mirrored in `tooling/validate.py`):

| Check | Severity |
|---|---|
| `character.portrait` references an id not in the registry | error |
| `node.portrait` references an id not in the registry | error |
| Portrait registry entry's `character` field references an unknown character | error |
| Portrait registered but never referenced by any character or node | warning |
| `node.portrait`'s registry entry's `character` differs from the node's RESOLVED speaker (N1: compares against `resolveSpeaker`'s character, not the raw speakerId string — a skill or narration speaker with a portrait override is not a mismatch) | warning |

**REF validator family — node speaker** (new in N1, alongside the existing dialogue-level check):

| Check | Severity |
|---|---|
| node `speakerId` matches neither a character nor a skill | error |
| node `speakerId` matches BOTH a character and a skill (ambiguous) | error |

---

## Cutscene playback (Manifest v2)

A cutscene (`data/cutscenes/{id}.json`) is a **manifest, not a script**:

```jsonc
{
  "id": "cs_district_blackout",
  "name": "The Blackout",
  "asset": "Cutscenes/HarbourArrival",    // opaque engine asset key
  "skippable": false,
  "effectsOnComplete": [ /* standard Effect[] */ ],
  "entersDialogue": "dlg_gatekeeper_intro", // optional chain
  "arrivesAt": { "location": "loc_inner_district", "spawn": "sp_courtyard" } // optional move
}
```

Motion, camera, and timing live in the **engine's own timeline tooling** (the
`asset`), never in JSON. Parlance never interprets or resolves `asset` — a mismatch
is the engine loader's error to report. There is **no dialogue inside a cutscene**: staging → talk → staging is
authored as a *chain* (cutscene ends into a dialogue via `entersDialogue`; a node there
can queue the next cutscene via `play_cutscene`). If a scene needs mid-playback
conditionality, it isn't a cutscene — it's a dialogue with staging.

The runtime **never plays a cutscene** — playback belongs to the host/engine
(the Parlance playtest UI, or your engine). The runtime's only responsibility is `play_cutscene`'s
effect on `GameState`, exactly like `set_active_dialogue`:

1. A `play_cutscene` effect fires (dialogue `onEnter`/choice effect, or quest stage
   `onComplete`) → `applyEffect` sets `state.pendingCutscene = effect.cutscene`.
2. The host/UI controller consumes `pendingCutscene` (it is also surfaced first by
   `nextContinuations` as a `{ kind: "cutscene" }` continuation); it plays the manifest's
   `asset`.
3. When the cutscene ends, the controller applies `effectsOnComplete`, clears the field
   with `clearPendingCutscene(state)`, moves the player to `arrivesAt` if the manifest
   names one, and enters `entersDialogue` if the manifest chains into one. That order is
   the contract, and `arrivesAt` sits inside it deliberately: the destination is data, so
   a skipped cutscene and a fully watched one put the player in the same place. Any
   travel animated inside the `asset` is choreography with no authority over position.
   The runtime does not clear `pendingCutscene` automatically; nothing else does either.
4. Setting `play_cutscene` again while one is already pending **overwrites** the previous
   id (last write wins — see `apply_effect.json` vector "overwrites an already-pending
   cutscene").

**Cutscenes are atomic.** Either unplayed (`pendingCutscene` set, nothing applied) or
played (`effectsOnComplete` applied, field cleared). No partial state is ever serialized —
saving mid-cutscene just replays it on load. If `skippable`, a skip applies
`effectsOnComplete` immediately.

**Route-walker support:** `RouteAssertEnd.pendingCutscene` asserts the final state's
`pendingCutscene` (`null` asserts none pending), and a `{ "cutscene": "cs_id" }` step
consumes it: applies `effectsOnComplete`, clears the field, and enters `entersDialogue`
if present. Only legal once the current dialogue has ended (atomicity), and the id must
match what's pending.

**CUT validator family** (`editor/core/src/validator.ts`, mirrored in `tooling/validate.py`):

| Check | Severity |
|---|---|
| `entersDialogue` references a nonexistent dialogue | error |
| `effectsOnComplete` entries reference nonexistent flags/factions/items/quests (existing effect REF pass) | error |
| `play_cutscene` effect points at a nonexistent cutscene | error |
| `asset` empty/missing | error (schema) |
| `arrivesAt.location` is not a known location | error |
| `arrivesAt.spawn` is not a spawn of that location | error |
| Cutscene never referenced by any `play_cutscene` effect | warning |
| Two `play_cutscene` effects fire from the same dialogue node (last-write-wins, ambiguous ordering) | warning |

`asset` is deliberately **not** validated against the engine project — Parlance has no
view into it.

---

## Decisions not in the schema

These are choices made here that a runtime must implement consistently:

| Decision | Value |
|---|---|
| Roll model | `NdM` + skill_value ≥ difficulty; default 1d20. Precedence: check.dice > rules.check.dice > 1d20. One rng() call per die, in order |
| Criticals | `rules.check.criticals`, default OFF. All-minimum always fails, all-maximum always succeeds, overriding the total. Judged on individual faces, never the sum |
| Reputation clamp | Faction `reputationRange.min` / `.max`; strict clamp after every delta |
| Counter range | Unbounded (no clamping) |
| `all` / `any` evaluation order | Left-to-right, short-circuit |
| Missing state keys | Defined defaults above; never throw on missing key |
| `advance_quest` | Writes `questStages[quest] = toStage`; does not evaluate `completeWhen` or outcomes |
| `adjust_relationship` | Writes `relationships[character] += delta`, unclamped (absent = 0) |
| `questOutcome` resolution | Re-evaluates the outcome's `reachedWhen` against current state; **never** reads `questFired`. Quest resolution only records items that carry **effects**, so a fired-record read would be permanently false for every effect-free outcome — a silent trap. Re-evaluation also keeps the condition independent of whether the host has called `resolveQuests` yet |
| `questOutcome` with no `reachedWhen` | Never reached (false), matching the resolution rule that an item with no condition never fires |
| `questOutcome` reference cycles | False at the point the cycle closes, via a DFS visited-set of `{quest}/{outcome}` pairs removed on exit — so two siblings may reference the same outcome, but a loop terminates. The validator reports the cycle as a `QUEST` error so it is not silently false |
| Endings fire no effects | An ending is only ever *evaluated*, never *fired*: there is no `resolveEndings`. Reaching an ending writes no state. Deliberate — revisit if a real need (NG+ unlock, seen-ending gallery) appears |
| Relationship clamping | **None.** `adjust_relationship` is unclamped, like `adjust_counter` and unlike `adjust_reputation` — a character declares no range the way a faction's `reputationRange` does. A per-character or project-level range can be added additively later without breaking data. |
| Unadvanced quest in a `quest` condition | Sits **before every stage**: `<` / `<=` true, `>=` / `>` / `==` false. So "not started yet" is `< <firstStage>` and "started" is `>= <firstStage>`. |
| Unknown quest or stage in a `quest` condition | **False for every op**, never throws. The validator reports both as REF errors at author time; the runtime stays total so a save naming a since-deleted stage degrades to unstarted rather than crashing. |
| Passive check destination | Uses `choice.goto`, never `onSuccess`/`onFailure` |
| `onEnter` application timing | First arrival only; caller responsibility |
| Portrait resolution | `node.portrait` > `character.portrait` > `null`; no shared-base fallback |
| Character dialogue resolution | `resolveCharacterDialogue`: first ladder rung whose `showIf` passes (absent `showIf` = always); `null` if none. Array order significant (first-match-wins) |
| `set_active_dialogue` | Feed model: sets flag `active_dialogue__{character}` (no `activeDialogues` map); resolution is always the ladder |
| Progression | `xp` monotonic total-earned; levels/points derived via `xpThresholds`; effective skill = `min(preset + invested, maxSkill)`; investing is a guarded player action, not an effect |
| Quest resolution | `resolveQuests`: condition-gated stage/outcome effects fire once when true, recorded in `questFired`; fixpoint; deterministic order; never writes `questStages` |
| `Check.kind` | Authoring/validation tag only — runtime does not branch on it; both `priced` and `oneshot` resolve through the same `resolveCheck` |
| `play_cutscene` | Writes `pendingCutscene = cutscene`; does not play anything. Re-firing overwrites (last write wins). Never auto-cleared by the runtime — the host/UI must call `clearPendingCutscene` |

---

## Character dialogue ladder — `resolveCharacterDialogue(state, character, project)`

**This is the canonical answer to "which dialogue plays next."** It is the ordered,
first-match-wins mechanism, and the only one with conformance vectors
(`conformance/resolveCharacterDialogue.json`) — which, under this contract's own rule
that the vectors are the truth, is what makes it canonical rather than merely
preferred. A project should express a character's arc as their ladder.

`selectDialogue` is the **escape hatch**: it returns dialogues owned by a character
whose own `availableWhen` passes, for the case where availability is a property of the
dialogue rather than of the character's arc. It has no vectors and no ordering
guarantee beyond that filter. Prefer the ladder; reach for this only when the ladder
genuinely cannot express the thing.

A character owns an ordered `dialogues` ladder (`DialogueCandidate[]`, each
`{ dialogue, showIf? }`). To decide what a character presents, walk the ladder
top-to-bottom and return the first rung whose `showIf` `evaluate`s true; an
absent `showIf` always matches (unconditional **fallthrough**). Return `null`
if the ladder is empty/absent or nothing matches.

```
resolveCharacterDialogue(state, character, project):
  for rung in character.dialogues ?? []:
    if rung.showIf is absent or evaluate(rung.showIf, state, project): return rung.dialogue
  return null
```

- **Array order is significant** — first match wins. This is the single source
  of truth used by the runtime, the resolution preview, and the stuck-rung
  static check. Re-entry needs no special code: walking the ladder again
  re-runs resolution against current state, so a different rung wins once flags
  change.
- **Feed model.** `set_active_dialogue` does not write a resolution override; it
  sets the flag `active_dialogue__{character}`, and the character's ladder is
  expected to carry a high-priority rung gated on that flag. There is no
  `activeDialogues` map in `GameState`.
- **NPC interactable resolution** is exactly one `resolveCharacterDialogue` call
  (the forced dialogue is just a high-priority rung).
- **`trigger` is host-only.** An interactable's optional `trigger` (`"walk_up"`,
  the default, or `"on_enter"`) says how the player reaches it: something they
  approach in space, or a scene that starts by itself on entering the location
  once `showIf` passes. The runtime never reads it — it exists so the host can
  tell a hotspot from an automatic scene without guessing from ids, which is a
  distinction naming conventions get wrong (a bedroom holds both the day's
  opening scene and the player's choice to go to sleep). Barks stay `walk_up`:
  they are embodied by an unnamed extra at a marker, not fired at the door.
  An `npc` interactable marked `on_enter` earns a warning: a character who talks
  at you unprompted is a scene in a costume.

## Quest resolution — `resolveQuests(state, project)`

`advance_quest` only RECORDS a stage id. The effects authored on quest stages
(`onComplete`) and outcomes (`effects`) fire through **quest resolution**, which the
**host** runs after every state transition it causes (choice effects, onEnter, cutscene
completion, skill invest). The play session does not run it: the stepper is pure and
knows nothing about quests. A host that never calls `resolveQuests` will find that stage
`onComplete` effects, and therefore most quest XP, simply never happen. The route walker
runs it after cutscene effects for the same reason. Rules — deliberately shape-simple:

- An item fires when it **has effects**, **has a condition** (`completeWhen` for
  stages, `reachedWhen` for outcomes), the condition evaluates **true**, and it has
  **not fired before**.
- Firing is **once-only per playthrough**, recorded in `state.questFired` as
  `{questId}/stage/{id}` / `{questId}/outcome/{id}` keys.
- An item with effects but **no condition never fires** (the QUEST validator warns).
- Resolution runs to a **fixpoint** — one firing's effects may satisfy another
  item's condition. Termination is guaranteed: each item fires at most once.
- **Deterministic order**: quests by id (sorted), each quest's stages then outcomes
  in array order, repeated passes until nothing new fires.
- Resolution does **not** write `questStages` — stage progression stays explicit
  via `advance_quest`; resolution only applies effects.

This is where quest XP (`grant_xp` on outcomes) actually enters play.

## Text interpolation — `interpolate(text, state): string`

A project may let the player name the protagonist. Any authored string that addresses
or refers to them substitutes that value at render time.

This is a **string substitution layer, not an expression language**: no conditionals,
no formatting, no nesting, no arithmetic. If you want those, author branching.

**Syntax.** `{var_id}` — single braces, a bare variable id, no spaces, no filters, no
modifiers. The id must match the usual `^[a-z][a-z0-9_]*$` pattern, so `{Not An Id}`
and `{}` are ordinary text and pass through untouched.

**Timing — render, never save.** Authored JSON always contains the placeholder. A value
is *never* baked into content: saving a dialogue containing `{player_name}` round-trips
byte-identically. `stepDialogue` interpolates on the way out; the entity objects it read
from are not mutated.

**Which fields.** Interpolation applies to **player-facing strings only**:

| Interpolated | Not interpolated |
|---|---|
| `DialogueNode.text` | ids of any kind |
| `Choice.text` | `name`, `title`, `summary`, `description` on entities |
| `Objective.text` | `notes` and other author-only annotations |
| `Stage.description` | anything else |
| `Quest.journalName` | |

A brace in an authoring-facing field is just a brace — the TEXT validator does not scan
those fields, and nothing substitutes them.

**Missing values never throw.** Resolution order:

1. `state.texts[id]` is set → substitute it (including when it is the empty string).
2. Otherwise the placeholder is left **exactly as written**, and a warning is logged
   once per unique id.

The default is not a separate step at render time: `createDefaultState` seeds
`state.texts` from each text variable's `default`, so by the time a state exists the
default is already in it. A key is absent only when the variable has no default and no
`set_text` has run — which is precisely the case that should be loudly visible in-game
rather than silently rendering an empty string. **A missing value must never take a
dialogue down.**

**No recursion.** A substituted value containing `{another_id}` is left alone. One pass.

**Limitation — no escaping (v1).** There is no way to write a literal `{player_name}`
in authored text: a `{` followed by a valid id pattern and `}` IS a placeholder. This
is documented rather than solved; if it ever bites, the fix is a syntax change, not a
special case.

**Condition semantics: none.** Text variables are a substitution slot, not a gate.
`evaluate` has no `text` condition type and will not gain one — branch on a flag set
alongside the `set_text`.

**Engine-written values — `writtenBy: "engine"`.** Parlance has no input-capture concept:
`set_text.value` is always a literal, and collecting free text the player typed is the
engine's job. The same is true of state the game computes rather than authors. Because the
hygiene passes look for an authored writer, such variables would otherwise warn forever
(`TEXT` "never written", `FLAG` "read but never set"). Marking the variable
`writtenBy: "engine"` declares that boundary and suppresses exactly those warnings — every
other check still applies. It has no runtime meaning.

Use it rather than inventing a placeholder `set_text` literal to silence the warning: a fake
literal is indistinguishable from a real authored value, and it ships as one.

## Quest journal — `Stage.objectives` are display-only

`Stage.objectives` exist **solely to be rendered**. The runtime never reads them.

- They carry **no effects**, **no `goto`**, and **no per-objective completion
  state**, and none of those may be added later without changing this contract.
- `Stage.completeWhen` remains the **sole authority** on stage completion,
  regardless of which objective (if any) the player actually followed. There is
  no notion of "the objective the player picked" anywhere in the state.
- Nothing in `GameState` tracks objectives. Do not add a field for it: an
  objective's visibility is recomputed from `showIf` against current state every
  time the journal renders, exactly like `Choice.showIf`.
- `objective.id` is for the validator and for diffs. It is never rendered and
  never persisted in a save.

The only runtime-adjacent rule is visibility: an objective is shown when it has
no `showIf`, or when `evaluate(showIf, state)` is true. The journal shows
completed stages (their `description`, a retrospective line) plus the current
stage's visible objectives — never a future stage.

If a future feature needs per-route consequences, author them as ordinary
effects on the dialogue or quest stage the route leads through — not on the
objective.

## Progression — XP / levels / skill points (`data/progression.json`)

Progression is a first-class registered singleton (`data/progression.json`, loaded
like `rules.json`). Absent ⇒ progression disabled. Config:

```jsonc
{
  "xpThresholds": [0, 100, 250, 450, 700, 1000],  // xp to reach each level; strictly increasing
  "pointsPerLevel": 1,                             // skill points granted per level
  "startingSkills": { "wit": 1, "empathy": 1 },    // character-creation preset loadout
  "maxSkill": 6                                     // global ceiling; a skill's own `max` overrides it
}
```

All progression functions are pure (`runtime.ts`):

| Function | Semantics |
|---|---|
| `levelForXp(xp, config)` | Highest `xpThresholds` index ≤ xp (thresholds strictly increasing). |
| `pointsEarned(xp, config)` | `levelForXp(xp) * pointsPerLevel`. |
| `effectiveSkill(skillId, state, config, skills?)` | `min(startingSkills[skillId] + skillPointsSpent[skillId], cap)` where `cap` is the skill's own `max` when it declares one, else the global `maxSkill`. This is what checks compare against. |
| `availablePoints(state, config)` | `pointsEarned(xp) − Σ skillPointsSpent`. Derived, never stored — can't drift. |
| `investSkillPoint(state, skillId, config)` | Spend one point. **Guarded no-op** unless a point is available AND `effectiveSkill < maxSkill` — never wastes a point on a capped skill. Player-driven (level-up UI), **not** an effect. |
| `recomputeSkills(state, config)` | `skills[id] = effectiveSkill(id)` for every preset/invested skill. Called on load + after each invest so the existing check machinery (which reads `state.skills`) needs no changes. |

- **`xp` is total-earned, not spendable.** Levels/points derive from it; investing a point
  increments `skillPointsSpent` (and bumps `skills`), never decrements `xp`.
- **Two caps, both intended:** the finite XP pool (soft, global — sum of quest rewards < cost
  to max everything) forces specialization; `maxSkill` (hard, local) stops dumping the whole
  pool into one skill. The soft cap is a content/budget rule (validator `PROG` sanity warning);
  the hard cap is enforced in `effectiveSkill` + `investSkillPoint`.

## Priced vs. oneshot checks

`Check.kind` is an optional authoring-intent tag on active checks — **validation and
presentation only; the runtime does not branch on it** (both kinds resolve through the same
`resolveCheck`).

- `kind: "priced"` (default for active checks): failure must **proceed at a cost** — its
  `onFailure` branch advances rather than dead-ending. The validator (`CHECK`) warns if a
  priced check has no `onFailure` branch.
- `kind: "oneshot"`: pass-or-not-forever identity moment; exempt from the proceed requirement.
  The `REACH` pass warns if a node is reachable *only* by succeeding oneshot checks.
- `acknowledgedLockout: true` (oneshot only): declares that lockout **intended** — the player
  meets the moment as whoever they are right now, and not seeing the content behind it is the
  design rather than a bug. Suppresses that `REACH` warning, so a project with a legitimate
  one-shot fork can still run `--strict`. Validation-only; the runtime never reads it.

The validator additionally warns when `kind` appears on a **passive** check (passive checks
never roll, so there is no pass/fail to price and the runtime ignores the tag), and when a
`oneshot`'s `onFailure` branch *continues the conversation* — that is a priced check wearing
the wrong tag, and it silently escapes the priced discipline.

There is **no retry mechanism** — priced failure removes the lockout retry existed to patch,
and skill investment is character authorship, not a between-attempts loop.

## SerializedGameState

`GameState.inventory` is a `Set<string>` which is not JSON-serializable. Use
`serializeState` / `deserializeState` from `@parlance/core` to convert for storage
or transport. The serialized form:

```json
{
  "flags":           { "met_guard": true },
  "reputation":      { "guild": 3 },
  "skills":          { "wit": 5 },
  "counters":        { "stamina": 10 },
  "inventory":       ["key_card"],
  "questStages":     { "quest_main": "stg_enter" },
  "xp":              450,
  "skillPointsSpent": { "wit": 2 },
  "relationships":   { "npc_wren": 2 },
  "texts":           { "player_name": "Wren" },
  "questFired":      ["task_find_contact/outcome/out_found"],
  "pendingCutscene": "cs_watchtower_signal"
}
```

- `inventory`: sorted `string[]` (stable diffs).
- `questStages`: `questId → current stage id`. Empty object `{}` when no quests advanced.
  Absent keys mean the quest has not been advanced yet.
- `xp`: total XP earned (monotonic). `skillPointsSpent`: `skillId → points invested`.
  Older serialized states lacking these are treated as `xp: 0` / `skillPointsSpent: {}`.
- `relationships`: `characterId → standing`; **omitted entirely when empty**, so saves and
  snapshots written before relationships existed stay valid and round-trip unchanged.
  Absent ⇒ `{}` on deserialize; an absent character reads as `0`.
- `texts`: `textVariableId → value`; **omitted entirely when empty** (like `questFired`),
  so saves and snapshots written before text variables existed stay valid and round-trip
  unchanged. Absent ⇒ `{}` on deserialize.
- `questFired`: sorted `string[]` of fired stage/outcome keys; **omitted entirely when
  empty** (like `pendingCutscene`). Absent ⇒ nothing fired yet.
- `pendingCutscene`: present only while a cutscene is queued; omitted entirely (not `null`)
  once cleared or if none was ever requested.
- All other fields: plain JSON objects, no transformation needed.

When deserializing older state that lacks `questStages`, default to `{}`.

---

## Conformance test suite

`editor/core/test/runtime.test.ts` covers all runtime functions, including `getPortrait` and
`clearPendingCutscene`. `editor/core/test/conformance.test.ts` runs the language-agnostic
vectors in `tooling/conformance/`, including `play_cutscene` / `pendingCutscene` vectors in
`apply_effect.json`. Engine ports in other languages must pass equivalent tests against these
same vectors to be considered conformant.

---

## Codex — player-facing knowledge entries

A codex entry is narrative text the **player** reads in-game (codex, bestiary,
glossary). It is distinct from `/lore`, which is authoring canon and never ships.

There is **no unlocked-set in `GameState`**. Unlocking is definitionally
`evaluate(entry.unlockedBy, state, project)`, evaluated on demand:

```
unlockedCodexEntries(project, state):
  every entry where unlockedBy is absent, or evaluate(unlockedBy, state, project)
```

Two consequences a port must match:

- An entry with **no `unlockedBy` is always unlocked**. Unlike `Ending.unlockedBy`,
  the field is optional, because an entry available from the start is ordinary.
- An entry **can re-lock** if the condition it reads stops holding. That falls out
  of having no stored unlocked-set, and is the honest behaviour: the condition is
  the source of truth. Author a monotonic condition (a flag that is only ever set
  true) if an entry must stay unlocked once seen.
