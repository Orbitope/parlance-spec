<!-- This guide is lint-guarded against private-project vocabulary. A term that
     legitimately must appear here (a field being renamed away from) should be exempted
     on its own line, not by a blanket file directive — the file carried one of those
     until its examples were made generic, and it hid a real leak for two releases. -->

# Parlance — Breaking changes and how to migrate

Pre-1.0, breaking changes land in minor releases with no deprecation window (see
[`VERSIONING.md`](VERSIONING.md)). This file is the running record of every one of them,
newest first, with a mechanical recipe per change.

Each entry answers three questions: **what broke**, **why it was worth breaking**, and
**exactly what to run**.

---

## 0.13.0 — one conformance vector added; no new rule

`tooling/conformance/` gains a regression-guard case, `npc-interactable-dialogue-places`,
that pins existing `LOC` and `LADDER` behaviour. It was added while the editor's validator
was refactored internally (into local + derive phases), to prove the refactor produced
identical results. `schema/`, `tooling/validate.py` and `RUNTIME_CONTRACT.md` are untouched:
there is no new rule and no schema change, and a conformant validator already emits this
case's expected output.

**What a port must do: nothing to its code.** If you vendor the conformance vectors and run
them in your own CI, re-vendor to pick up the new case — it already passes.

Everything else in the release is editor- and tooling-side and touches nothing a runtime
reads. Its headline is git-native collaboration: a non-technical writer and a non-technical
owner can now draft, review, and publish narrative end-to-end inside the desktop app, against
the studio's own GitHub, GitLab, or Bitbucket repository — Parlance hosts nothing. It also
carries incremental, off-thread save validation, the published `@orbitope/parlance-cli` and
its reusable GitHub Action, and starter templates for a new project. None of that changes how
a story is written or how a runtime reads it.

---

## 0.12.0 — no contract change

Nothing in the contract moved. `schema/`, `tooling/conformance/`, `tooling/validate.py`
and `RUNTIME_CONTRACT.md` are byte-identical to `v0.11.0`, and **a port pinned to
`v0.11.0` needs no action of any kind** — not a re-run of its suite, not a re-vendor of
the vectors.

Nothing in the *publish set* moved either, beyond the two documents that record the
release: the spec repo's `v0.12.0` differs from `v0.11.0` only in `PUBLICATION.json`,
this file, and `VERSIONING.md` (whose pinning example moves with every tag). No schema,
no vectors, no runtime semantics. The tag exists so that a port tracking editor releases
has an exact tag to pin, per `INTEGRATION.md` — it is a lockstep marker, not a change.

The release is entirely editor-side, and it is a durability release rather than a feature
one. What it fixes are ways the editor could lose or corrupt an author's work:

| | |
|---|---|
| **Corruption** | One write path, with a temp filename unique per write. A fixed `<target>.tmp` meant two writers shared one buffer and published a blend of both — reachable in normal use, since the editor host and the MCP server are separate processes on one project. |
| **Lost updates** | The array registries (`skills.json`, `variables.json`, `items.json`, `portraits.json`) rewrite the whole file to change one entry, so concurrent saves silently dropped entities. Read-modify-write is now behind a cross-process lock. |
| **A crash that took the host down** | `validate()` is now total: malformed data reports as an issue instead of throwing. |
| **A lock race** | Absent is no longer treated as stale, and stealing a lock verifies identity first. |
| **Serializer** | A `__proto__` key is no longer silently dropped. |
| **WebSocket** | A broadcast survives one dead socket instead of failing the batch. |

The desktop app also gains quit-on-close, session restore, and real File/Edit/View/Window
menus.

If you author with Parlance, none of this needs anything from you — it is the failure
modes getting closed, not a change in how anything is written.

---

## 0.11.0 — conditional narration (NOT safe to skip)

**Unreleased as of this writing — `v0.10.0` is the newest tag, and this entry describes
what the `v0.11.0` tag will contain.** It carries one change, `DialogueNode.showIf`, which
is **additive to the schema but forward-incompatible for consumers**. It is deliberately
kept apart from the `goto`/`default` reserved-word rename, which moves to 0.12.0: that
change is mechanical and touches every conformance vector, this one is semantic and needs
its own conformance attention — and a port whose suite goes red after a combined release
could not tell which change broke it.

### `DialogueNode.showIf` — conditional narration

**Additive to the schema. NOT safe for an unimplementing runtime to ignore.**

Every existing project loads unchanged and stays valid, so there is nothing to migrate in
your data. The hazard runs the other way: a runtime pinned below `v0.11.0` that is handed a
project *using* the new field will show conditionally-hidden text unconditionally, with no
parse error and no warning. Silent wrong output, not a crash.

That inverts the usual reading of "additive". Do not treat this the way you treated
`snapshot.visitedDialogueIds` below.

| Addition | Replaces the workaround of… |
|---|---|
| **`DialogueNode.showIf`** — the same condition type `choice.showIf` already uses | Having no way to express a line of narration that appears only in some world states. There was no workaround: wrapping the line in a choice fabricates a decision the player never made, and a node advances by `next` (one fixed target) or by a player choice, so nothing could branch on state without asking the player something. |

**Am I exposed right now?** Run this against any project your pinned runtime consumes —
a plain grep is useless here, since `"showIf"` hits every gated choice:

```bash
python3 - <<'EOF'
import json, glob
for p in sorted(glob.glob("data/dialogues/*.json")):
    d = json.load(open(p))
    gated = [n["id"] for n in d.get("nodes", []) if "showIf" in n]
    if gated:
        print(f"{d['id']}: node-level showIf on {', '.join(gated)}")
EOF
```

No output = no exposure: your pinned runtime is rendering this project correctly today,
and you can schedule the pin move on your own terms. Any output = every listed node is
being shown unconditionally by a pre-0.11.0 runtime, right now.

**If you implement a runtime**, add the resolve step from
[`RUNTIME_CONTRACT.md`](RUNTIME_CONTRACT.md) — `resolveNode` — and route every arrival
through it: `entry`, `next`, a choice `goto`, and a check's `onSuccess`/`onFailure`. The one
rule that is easy to miss: **a skipped node is inert, and its `onEnter` effects DO NOT
fire.** Take the conformance vectors at this tag; `step_dialogue.json` and `advance.json`
cover a two-skip chain, a conditional `entry`, a skipped node whose effects must not fire,
the resolved id an advance must return, and the conditional-ring throw — and the
`stepDialogue` expected shape now asserts the **resolved node id**, so a runtime that
never skips cannot pass by accident.

**If your writers and your engine move independently** — the usual studio shape — the
invariant to hold is: *data must not acquire node `showIf` before the engine implements
the skip walk.* The cheap enforcement is a CI gate on the data side using the probe above,
failing the build while the recorded engine pin is below this release.

**If your port deserializes strictly**, you get the crash you want for free: configure the
deserializer to reject unknown fields (e.g. .NET's `JsonUnmappedMemberHandling.Disallow`)
and an unimplemented contract addition surfaces as a load error instead of silent wrong
output. This is the single cheapest mitigation available to a pinned consumer, and it
converts every future addition of this class from a lie into a loud failure.

**If you author data**, a node carrying `showIf` must have `next`, and must not have
`choices` or `isEnd` — the validator's new `COND` rules enforce it. That constraint keeps
the feature to interstitial narration, which is what makes skipping unambiguous. An
empty-text gated node is rejected outright: that is a conditional effects block, not
narration. In the editor's Text view the gate rides as a `~ showIf: <condition>` line
under the node header.

**If you already validate**, `COND` is a **new issue code, and it carries errors** — a
pipeline or dashboard that maps codes to severities needs the row (the 0.9.0 `TASK` →
`QUEST` note set the precedent). A project with no node-level `showIf` sees no new
findings at all. The one advisory: a conditional node carrying `onEnter` warns, because
those effects silently do not fire when the node is skipped.

---

## 0.10.0 — visited-set snapshots

**Released** (tagged 2026-08-24). Safe to ignore: your data loads unchanged, and a port
pinned to `v0.9.0` renders it identically until it takes the field up.

### `snapshot.visitedDialogueIds` — additive, nothing to migrate

| Addition | Replaces the workaround of… |
|---|---|
| **`snapshot.visitedDialogueIds`** — optional array of dialogue ids, sorted, omitted when empty | Losing the visited set at every save→snapshot hop. The runtime has always taken a visited set (it is what hides a non-`replayable` dialogue once seen), but `SerializedGameState` has nowhere to keep one — deliberately, since it is what the host has *shown*, not what the story *is*. Snapshots captured mid-playthrough previously came back with the set empty, so a route starting from one was offered one-shots the player had already spent. |

**If you write a route runner**, seed its visited set from the start snapshot's
`visitedDialogueIds` — otherwise a route that begins from a captured baseline
walks content the baseline's own playthrough had already consumed, and *passes*
on a path no player can reach. The reference implementations do this
(`routeRunner.ts`, `RouteRunner.cs`).

**If you write saves**, the field is also the natural thing to put in your own
save envelope, and the editor's save importer reads it from there. Everything
else in your envelope stays yours: Parlance reports unrecognised envelope fields
on import and drops them, rather than interpreting bookkeeping it has no model
for.

**One behaviour correction.** A route starting from a snapshot now inherits that
snapshot's `texts` and `questFired` ledger, which the TypeScript runner was
dropping. `RouteRunner.cs` was already correct, so this is only a fix if your
port was written from the TypeScript source: a route whose baseline had already
fired a once-only quest effect could fire it a second time.

---

## 0.9.0 — de-game the contract

One batched break, deliberately shipped together so a downstream project migrates once
rather than nine times. The additive capabilities that shipped alongside them are listed
after the breaks.

**Why now.** Every item here was project-specific vocabulary sitting in a *normative*
position — a required field, a closed enum, a hardcoded constant. Any project adopting
Parlance inherited one particular game's taxonomy as a hard requirement. That was fine
while this repo was the only consumer; it stops being fine the moment the format is
published or a second project adopts it.

### Summary

| # | Change | Kind | Auto-migratable |
|---|---|---|---|
| 1 | `character.class` → `character.archetype`, no longer required | field rename + relax | yes |
| 2 | `location.exits[].gateType` enum → free-form string | constraint removal | yes (no-op) |
| 3 | Quest tag vocabulary moves to `rules.quest.tagVocabulary` | constant → config | yes |
| 4 | `location.connectsTo` removed | field removal | **no** — each link needs a spawn chosen |
| 5 | `location.region` removed, folded into `zone` | field removal | yes |
| 6 | `dialogueNode.acceptsInjections` removed | field removal | yes |
| 7 | `skill.cluster` no longer required | constraint removal | yes (no-op) |
| 8 | The `sp_main` spawn exemption becomes an explicit `"isDefault": true` | magic id → field | **no** — you name the default |
| 9 | Validator issue code `TASK` renamed `QUEST` | tooling rename | yes, if you parse codes |
| 10 | `dialogue.isDefault` removed; the ladder is the canonical discovery path | field removal | yes |
| 11 | `variable.kind: "item"` becomes a first-class `item` entity | entity split | yes |
| 12 | `data/routes` and `data/snapshots` move to `tests/` | directory move | yes |

Changes 2, 7 and 9 cannot break existing *data* — 2 and 7 only widen what validates, and
9 touches validator output rather than files. Changes 1, 5 and 6 are scripted below.
Change 3 is optional. **Changes 4 and 8 need judgement**: `connectsTo` never recorded
which spawn point to arrive at, and only you know which spawn is a location's default.

---

### 1. `character.class` → `character.archetype`, and now optional

**Before**

```json
{ "id": "npc_wren", "name": "Wren", "class": "operative" }
```

**After**

```json
{ "id": "npc_wren", "name": "Wren", "archetype": "operative" }
```

**Why.** The field was already generic in practice — the values in use were plain role
labels (`official`, `operative`, `newcomer`, `trader`), none of them matching the
narrower taxonomy its own schema description enumerated. Only the description carried the
project's taxonomy. Two things were wrong with it:

- The **name** imposed one project's classification axis as though it were a format concept.
- **`required`** forced the axis on every adopter, including projects that have no such
  axis at all (a two-hander visual novel, a single-narrator interactive fiction).

`archetype` is deliberately vague — it is whatever axis your project sorts its cast by
(role, class, species, rank). It stays free-form and is now optional.

**Breaking because** `character.schema.json` sets `additionalProperties: false`, so a
file still carrying `class` is a hard SCHEMA error. There is no grace period.

**Migrate:**

```bash
# from your project root — rewrites every character file in place, canonically
python3 - <<'PY'
import json, pathlib
for p in pathlib.Path("data/characters").rglob("*.json"):
    if p.name.endswith(".layout.json"): continue
    d = json.loads(p.read_text())
    if "class" in d:
        d["archetype"] = d.pop("class")
        p.write_text(json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
PY
```

**Also update, if your project has them:**

- Any engine-side code reading `character.class`.
- Portrait ids following the `portrait_{class}` convention — the convention is now
  `portrait_{archetype}`. Ids are opaque to Parlance, so renaming them is optional; if
  you do rename, update `character.portrait` references in the same pass.
- Tags of the shape `class:x`, if you use them for portrait or filter grouping.

**Editor note.** The characters list's **Group by → Class** is now **Group by →
Archetype**. Characters with no `archetype` group under "Unknown".

---

### 2. `location.exits[].gateType` is a free-form string

**Before** — a closed enum in the schema:

```json
"gateType": { "enum": ["checkpoint", "locked_door", "guard_post", "escort_gate", "labor_gate", "act_gate"] }
```

**After** — any non-empty string.

**Why.** The enum published one project's gate vocabulary as normative contract, so every
adopter's `gateType` had to be drawn from a list describing a world they were not making.
Gate presentation is inherently per-project: it maps to whatever art represents that kind
of barrier. This now follows the precedent `skill.cluster` already set.

Parlance still enforces the part that *is* general: a `gateType` should be paired with a
`gate` condition, and vice versa (both `LOC` warnings).

**Migrate:** nothing. This only widens what validates — every previously valid value
stays valid. Your existing gate vocabulary keeps working exactly as it did; it is simply
now yours rather than the format's.

**Editor note.** The exit editor's **Gate type** dropdown is now a free-text field, since
the editor no longer has a fixed list to offer.

---

### 3. Quest tag vocabulary moves into `rules.json`

**Before** — hardcoded in both validators:

```python
QUEST_TAG_VOCABULARY = ["main", "side", "act1", "act2", "act3",
                        "group:a", "group:b", ...]
```

**After** — declared per project in `data/rules.json`:

```json
{
  "quest": {
    "tagVocabulary": ["main", "side", "act1", "act2", "act3", "group:a", "group:b"]
  }
}
```

**Why.** This was the worst leak of the three: one project's faction names, hardcoded
inside the *publishable* reference validator. Every adopter got an `OBJ` warning for
every quest tag they invented, and a list of factions from a game they had never heard of
in the warning text.

**Semantics changed:** the check is now **opt-in**. With no `tagVocabulary` declared, any
quest tag is accepted and the check does not run. Declare one to get the old behaviour.

**Migrate:** if you want to keep the vocabulary check, write your project's list into
`data/rules.json`. Create the file if you do not have one — every field in it is
optional, so a rules file containing only `quest.tagVocabulary` is valid.

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("data/rules.json")
d = json.loads(p.read_text()) if p.exists() else {}
d.setdefault("quest", {})["tagVocabulary"] = [
    "main", "side", "act1", "act2", "act3",
    "group:a", "group:b", "group:c",
]
p.write_text(json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
PY
```

If you would rather not maintain a vocabulary, do nothing — the check simply stops
firing.

**Note for port authors:** `QUEST_TAG_VOCABULARY` is no longer exported from
`@parlance/core`. Read `project.rules?.quest?.tagVocabulary` instead.

---

### 4. `location.connectsTo` removed

A flat adjacency list superseded by `exits` long ago, and unused in any data in this
repo. Removed rather than carried as permanent dead weight in a contract about to be
published.

**Migrate:** if you still have `connectsTo` anywhere, each entry becomes an `exits` entry
with a `to.location` and a `to.spawn`. There is no automatic recipe — `connectsTo` did
not record which spawn point to arrive at, which is exactly why it was superseded.

```bash
grep -rl '"connectsTo"' data/locations/    # find them; expect no output
```

---

### 5. `location.region` removed, folded into `zone`

`region` was labelled "Legacy region label; prefer zone for new content" and had been for
some time. Two fields meaning the same thing is a trap for anyone learning the format.

**Migrate:**

```bash
python3 - <<'PY'
import json, pathlib
for p in pathlib.Path("data/locations").rglob("*.json"):
    if p.name.endswith(".layout.json"): continue
    d = json.loads(p.read_text())
    if "region" in d:
        d.setdefault("zone", d.pop("region"))
        p.write_text(json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
PY
```

Note `setdefault`: if a location already had both, `zone` wins and `region` is dropped.
Check that case by hand if your project set both.

### 6. `dialogueNode.acceptsInjections` removed

The field's own description promised that "future `inject_topic` effects will
append choices here". That effect was never built, and nothing read the field —
not the runtime, not either validator, and no data in this repo. Publishing it
would have made every port implement a no-op to satisfy it.

**Migrate:** delete the key wherever it appears. If your dialogue-script text
carries the `[injectable]` node attribute, drop it — it now fails with `unknown
node attribute`.

```bash
python3 - <<'PY'
import json, pathlib
for p in pathlib.Path("data/dialogues").rglob("*.json"):
    if p.name.endswith(".layout.json"): continue
    d = json.loads(p.read_text()); touched = False
    for n in d.get("nodes", []):
        if "acceptsInjections" in n:
            del n["acceptsInjections"]; touched = True
    if touched:
        p.write_text(json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
PY

grep -rl 'acceptsInjections' data/    # expect no output
```

Shared dialogue topics (ink-style tunnels) remain a genuine gap. Removing the
placeholder does not remove the need; it stops the contract implying the need is
half-met.

### 7. `skill.cluster` is no longer required

**Before:** every skill had to declare a `cluster`, even though the schema described it as
"project-defined grouping, free-form" — a required field whose value the format has no
opinion about. Same debt as the old `character.class`.

**After:** optional. Existing data is untouched and still valid; a project that doesn't
group its skills now simply omits it. The editor no longer seeds `cluster: "body"` into
new skills, which was inventing a taxonomy on the author's behalf.

**Migrate:** nothing to do. This only widens what validates.

---

### 8. The `sp_main` spawn exemption becomes an explicit `"isDefault": true`

**Before:** the published validator hardcoded the identifier `sp_main`, silently exempting
it from the "spawn nothing arrives at" check. That convention was documented nowhere in
the schema — an adopter naming their default spawn `spawn_entry` got a warning they could
not explain, and one who happened to name it `sp_main` got an exemption they were never
told about. A magic identifier in a published tool is the same class of leak as a
hardcoded faction list.

**After:** a spawn carries `"isDefault": true`. The id means nothing to the validator any
more, and the concept is visible in the schema where an adopter can find it. A location
may have at most one, now enforced.

**Before**
```json
{ "id": "loc_common_room", "spawns": [{ "id": "sp_main" }, { "id": "sp_yard_door" }] }
```

**After**
```json
{ "id": "loc_common_room", "spawns": [{ "id": "sp_main", "isDefault": true }, { "id": "sp_yard_door" }] }
```

**Migrate:** mark each location's default arrival point — the spawn the engine uses for a
new game, dev entry, or a cutscene arrival with no particular door. It is usually the one
no exit points at:

```bash
# Find spawns nothing arrives at; each is a candidate default.
python tooling/validate.py 2>&1 | grep 'exists but no exit'
```

Renaming `sp_main` is not required — the id is now ordinary. Leaving a location with no
default is legal; its unused spawns simply warn.

---

### 9. Validator issue code `TASK` renamed `QUEST`

**Before:** the entity, the schema, the directory and the API all said `quest`, while the
validator reported `[TASK]` and phrased its messages as "task 'q_x'".

**After:** `[QUEST]`, everywhere. One word for one concept.

**Migrate:** only if you parse validator output. Any CI grep or dashboard filtering on
`TASK` becomes `QUEST`; no data changes.

---

---

### 10. `dialogue.isDefault` removed

**Before:** three mechanisms answered "which dialogue plays next" — the character's
ladder, a dialogue's `availableWhen`, and a dialogue's `isDefault`. Every port had to
implement all three, and an adopter had to guess which to reach for.

**After:** two, with a stated relationship. The **ladder is canonical** — ordered,
first-match-wins, and the only one with conformance vectors, which under this
contract's own "the vectors are the truth" rule is what canonical means.
`availableWhen` is the documented **escape hatch**, for when availability is a
property of the dialogue rather than of the character's arc. `isDefault` is gone: it
was a third path with no vectors, and it was used by exactly zero dialogues across
this repo and the shipped demo.

`selectDialogue` loses its second group; it now returns only dialogues whose
`availableWhen` passes. The dialogue-script text format loses its `~ default`
directive.

**Migrate:** delete the key. If a dialogue relied on `isDefault` to be discoverable,
give it either a ladder rung on its speaker (preferred) or an `availableWhen`:

```bash
grep -rln '"isDefault"' data/dialogues/   # expect no output
```

```python
import json, pathlib
for p in pathlib.Path("data/dialogues").rglob("*.json"):
    if p.name.endswith(".layout.json"): continue
    d = json.loads(p.read_text())
    if d.pop("isDefault", None) is not None:
        p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        print("cleaned", p)
```

A dialogue left with neither a ladder rung nor `availableWhen` is unreachable, and the
LADDER validator says so by name.

---

### 11. `variable.kind: "item"` becomes a first-class `item` entity

**Before:** an item was a variable of `kind: "item"` — a boolean with no name, no
description, and nothing to bind an asset to. It was the only referenced thing in the
format with no human-facing identity, which meant an inventory UI had no text to show
without the engine hardcoding it.

**After:** `data/items.json`, a flat registry beside `skills.json` and `variables.json`:

```json
{ "items": [
  { "id": "item_lantern", "name": "Stable Lantern",
    "description": "Bragg's stable lantern. Without it the yard is unsearchable in the dark." }
] }
```

`name` is required — it is the reason the entity exists. `description`, `tags`, and
`loreRef` are optional.

**The runtime does not change.** Possession already lived in `GameState.inventory`, a
set separate from flags, so `give_item` / `take_item` and the `item` condition behave
exactly as before and no conformance vector moves. This is a change to how items are
*declared*, not to how they *work*.

**Migrate:** move every `kind: "item"` variable into `items.json`, keeping its id so
every existing reference keeps resolving:

```python
import json, pathlib
data = pathlib.Path("data")
vars_file = data / "variables.json"
d = json.loads(vars_file.read_text())
items, keep = [], []
for v in d["variables"]:
    if v.get("kind") == "item":
        it = {"id": v["id"], "name": v.get("name") or v["id"]}
        for k in ("description", "tags", "loreRef"):
            if v.get(k): it[k] = v[k]
        items.append(it)
    else:
        keep.append(v)
d["variables"] = keep
vars_file.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
(data / "items.json").write_text(json.dumps({"items": items}, indent=2, sort_keys=True) + "\n")
```

An item left in `variables.json` now fails as a SCHEMA error (`kind` no longer accepts
`"item"`); an item referenced but not registered fails as
`[REF] … unregistered item 'x' (add to items.json)`.

---

### 12. `data/routes` and `data/snapshots` move to `tests/`

**Before:** route and snapshot fixtures sat inside `data/`, alongside dialogues and
quests, so every loader that walked the narrative directory also walked regression
tests a shipping game never reads.

**After:** they live in a `tests/` sibling:

```
data/     narrative content — what the game plays
tests/
  routes/     rt_*.json    scripted playthroughs with assertions
  snapshots/  snap_*.json  saved states to resume from
```

Both roots are overridable in `parlance.config.json` (`data`, `tests`), the way
`schema` and `lore` already were.

**Why it matters to a port and not just an author:** `data/` is the directory your
runtime loads, and it now contains only things the runtime can use. Nothing about the
route or snapshot *formats* changed — only where they are found.

**Migrate:** move the directories. Ids and file contents are untouched.

```bash
mkdir -p tests
git mv data/routes tests/routes 2>/dev/null || true
git mv data/snapshots tests/snapshots 2>/dev/null || true
```

If your project keeps them somewhere else, point `tests` at it in
`parlance.config.json` instead. A project with no fixtures needs no `tests/` directory
at all — an absent one loads as empty.

---

## 0.9.0 — new capabilities (additive, nothing to migrate)

These need no action. They are listed so the additions are visible next to the
breaks when you plan the refactor — each replaces a workaround you may currently
be carrying.

| Addition | Replaces the workaround of… |
|---|---|
| **`quest` condition** — `{ "type": "quest", "quest": ID, "op": ">=", "stage": STAGE_ID }`, compared by stage **order** | Mirroring quest progress into parallel flags. If you keep `completed_x` flags purely to gate on progress, they can go. |
| **`relationship` condition + `adjust_relationship` effect** | A fake faction per character, or an untyped counter. Standing lives in `GameState.relationships`, unclamped, absent = 0. |
| **`codex` entity** (`data/codex/`, prefix `codex_`) | Player-facing knowledge text living in engine code instead of the project. `unlockedBy` is optional — absent means always unlocked. |
| **`name` on variables** | Overloading an item's `description` as its display name. |
| **`questOutcome` condition** — `{ "type": "questOutcome", "quest": ID, "outcome": OUTCOME_ID }` | Re-testing an outcome's own `reachedWhen` flags a second time somewhere else. An ending gated on "the player accused Wren" can now name the outcome instead of copying its condition. Evaluates the outcome's `reachedWhen` against current state — it does **not** read `questFired`, so effect-free outcomes work. |
| **`kind` on endings** — optional `success` / `failure` / `neutral` | Improvising a tone vocabulary in `tags`. Same values quest outcomes already use. |

One signature change worth knowing if you have written a port:
`evaluate(condition, state)` is now `evaluate(condition, state, project)`,
matching `applyEffect`. Quest conditions need the project to resolve stage order.

**One dependency floor moved.** `tooling/requirements.txt` now asks for
`jsonschema>=4.18` (was `>=4.0`) and declares `referencing>=0.30` directly.
`validate.py` resolved cross-schema `$ref`s through `RefResolver`, which jsonschema
deprecated in 4.18 and has announced for removal; it now uses `referencing`, which needs
the `registry=` argument added in that same release. If you pin jsonschema anywhere
between 4.0 and 4.17, raise it when you take this release — otherwise `validate.py`
fails at import. Your data is unaffected and the validator's output is unchanged.

---

## Running the whole 0.9.0 migration

In order, from your project root:

```bash
# 1. Take a branch. These scripts rewrite data in place.
git checkout -b migrate-parlance-0.9

# 2. Apply the three scripted rewrites — changes 1 (class), 5 (region) and
#    6 (acceptsInjections). Paste each python block above, or run from a file.

# 3. Optionally restore the quest tag check (change 3).

# 4. Change 4 by hand: connectsTo cannot be scripted, because it never recorded
#    which spawn to arrive at. Find them, then author a real exit for each.
grep -rn '"connectsTo"' data/locations/

# 5. Changes 11 and 12 are mechanical — items out of variables, fixtures out of
#    data/. Paste the python block from change 11, then:
mkdir -p tests
git mv data/routes tests/routes 2>/dev/null || true
git mv data/snapshots tests/snapshots 2>/dev/null || true

# 6. Change 8 by hand: mark each location's default arrival spawn. The validator
#    lists the candidates — every spawn no exit points at.
python3 /path/to/parlance/tooling/validate.py --root . 2>&1 | grep 'exists but no exit'

# 7. Verify against the new contract.
python3 /path/to/parlance/tooling/validate.py --root . --strict

# 8. Review the diff. Every change should be a key rename, a key removal, or an
#    added `"isDefault": true` — nothing else. Canonical serialization means the
#    diff is readable.
git diff --stat
git diff
```

**Expected diff shape.** One `class` → `archetype` rename per character file, one
`region` → `zone` rename per affected location, a deleted `acceptsInjections` key per
affected dialogue node, one added `"isDefault": true` per location that has a default
arrival spawn, plus whatever exits you authored by hand for step 4 — and nothing else. If you see reordered
keys or reindented blocks, the canonical serializer disagrees with how the file was
written. Parlance writes sorted-key, 2-space, LF JSON; run any hand-edited or
scripted file back through the editor (or re-serialize it the same way) so later
saves do not produce spurious diffs.

**If validation fails after migrating**, the most likely causes are:

| Symptom | Cause |
|---|---|
| `[SCHEMA] ...: Additional properties are not allowed ('class' was unexpected)` | A character file the rename script missed — check for nested subdirectories. |
| `[SCHEMA] ...: 'archetype' is not of type 'string'` | A `class` value that was not a string (an array or object). Fix by hand. |
| `[OBJ] ... not in the project's quest tag vocabulary` | You declared a `tagVocabulary` that is missing tags your data uses. Add them, or delete the declaration. |
| Engine-side null/undefined where an archetype was expected | `archetype` is optional now. Give the engine a fallback rather than making the field required again. |
| `[LOC] ...: N spawns marked default` | More than one spawn in a location carries `"isDefault": true`. Exactly one can. |
| A CI job or dashboard stopped matching validator output | The `TASK` issue code is now `QUEST` (change 9). |

---

## Format of future entries

Add a new `## X.Y.Z` section at the top of this file for each release carrying a breaking
change. Every entry needs: what broke, why it was worth breaking, a before/after pair, and
a runnable migration recipe (or an explicit statement that the change needs judgement and
cannot be scripted). An entry with no recipe is not finished.
