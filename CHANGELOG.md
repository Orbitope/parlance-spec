# Changelog

Mirrors the upstream releases. Each entry corresponds to a `vX.Y.Z` tag in
Parlance; breaking changes and their migration recipes are in
[`docs/MIGRATIONS.md`](docs/MIGRATIONS.md).

Pre-1.0, breaking changes land in minor releases with no deprecation window —
see [`docs/VERSIONING.md`](docs/VERSIONING.md). Pin an exact tag and vendor the
conformance vectors at it.

## v0.16.0

**Runtimes have nothing to do; validator ports owe work.** `schema/` and the runtime
conformance vectors are unchanged, so a 0.15 runtime plays every 0.16 project exactly as
before, and this is not a release you cannot skip. The reference playback runtime is now
published under MIT as `@orbitope/parlance-runtime`, and its source is in `runtime/`.

**What a validator port must do.** Eighteen new validator cases, 129 in all.
- **New `FLOW` warning.** Warn on a node that is not `isEnd`, has no `next`, and whose
  non-fallback choices are all `check.mode: "passive"`. The runtime counts unrevealed
  passive choices as visible, so a fallback there is suppressed and a game that hides
  them shows nothing clickable. Cases: `choice-passive-only-*`,
  `choice-passive-beside-plain-clean`.
- **Dice bounds.** More than 100 dice, or a die with more than 1000 sides, is a `RULES`
  error. Cases: `dice-too-many`, `dice-too-many-sides`.
- **`OFFER` ties are bucketed and capped.** Compare only offers of one character with the
  same priority and specificity. Report the first 10 ties, then one summary warning.
  Case: `offer-tie-capped`.
- **ECMA-262 pattern anchoring.** `$` never matches before a trailing newline. In Python,
  use `fullmatch` or `\Z`. Cases: `id-trailing-newline`,
  `engine-command-trailing-newline`.
- **Unknown keys are `SCHEMA` errors** wherever a schema says
  `additionalProperties: false`, except `_comment`. Case: `node-unknown-key`.
- **Reporting is total.** A malformed file is a `SCHEMA` error naming the file, never a
  crash. See the `types-json-array` and `registry-entries-not-array` cases and six more.
- **Case files accept an optional `at` key** (`entityType`, `entityId`, `path`) in
  `must`/`mustNot` entries. A port whose issues carry no location should ignore it.

**Projects.** A project that passed `validate/validate.py` under 0.15.0 still passes,
with two narrow exceptions: a custom-type row id that is not snake_case, and a
pattern-checked string ending in a newline. The editor already refused to write either.
Oversized dice notation is newly an error. The new `FLOW` warning fails only `--strict`.

**For loaders.** Locale files may now carry `@sourceHashes` and `@outdated`. Skip keys that
start with `@`; no real key does. See `docs/INTEGRATION.md`.

Full detail, including the reference-runtime changes that moved no vector, is in
[`docs/MIGRATIONS.md`](docs/MIGRATIONS.md).

## v0.15.0

**No project needs migrating; every port must upgrade.** Every project valid under 0.14.0
stays valid and plays identically: shapes the validator used to reject become legal, and
new fields are optional. But a 0.14 runtime plays the new shapes wrong with no error. It
skips a gated node that carries choices, shows a fallback choice beside the choices it
replaces, and may throw on the new `engine` effect. Runtime vectors go from 182 to 207.

**What a port must do — node shapes and choices.**
- **Line-only gates.** A node whose `showIf` fails is skipped only when it is
  interstitial (no `choices`, not `isEnd`). A gated node with choices or `isEnd` is
  returned; its `onEnter` fires, its choices are offered, and `stepDialogue` returns
  `textHidden: true` with `text: ""`. Judge the gate once, on arrival, before `onEnter`.
- **`text` is optional** on a node with non-empty `choices`.
- **`choice.fallback`.** Offer it only when no non-fallback choice on the node is visible.
- **Locked choices.** `stepDialogue` returns `lockedChoices`: failing choices whose
  `whenLocked` (default `rules.choices.whenLockedDefault`, then `"hide"`) is `"show"`.
  Interpolate `lockedText`. `visibleChoices` keeps its meaning.
- **`chooseChoice` throws** on a hidden choice, a locked choice or an unoffered fallback.
- **Tags.** `node.tags` and `choice.tags` pass through `stepDialogue` unchanged.
- **The `engine` effect** `{ type: "engine", command, args? }` leaves state unchanged and
  is returned in order among the other effects, for the host to dispatch.
- **`resolveQuests`** gains a vector that only a port iterating to the fixpoint passes.

Re-vendor `step_dialogue.json` (24), `choose_choice.json` (17, now with `expectedError`
vectors), `advance.json` (14), `apply_effect.json` (29) and `resolve_quests.json` (7).

**What a validator port must do.** New issue code `ENGINE` (a malformed command is an
error; with `rules.engine.commands` declared, an undeclared command or a wrong argument
count is a warning). New `FLOW` findings: a node with no text and no choices (error), more
than one fallback, a fallback with no gated sibling, and `whenLocked`/`lockedText` without
`showIf`. The `COND` errors for `showIf` with `choices`/`isEnd` are gone. `FLAG` reports two
flags of one `rules.flag.exclusiveGroups` group set true in one effect list. Custom entity
types in `data/types.json` are loaded and checked (`SCHEMA`, `REF`, `DUP`). Optional
`data/bindings/*.json` (`schema/binding.schema.json`) is checked and warns `BIND`. Strip a
leading UTF-8 byte-order mark before parsing, and match a `loreRef` in either Unicode
normalization form. 39 new validator cases.

**Also published:** four new format importers (SugarCube, ChoiceScript, Arcweave, Ren'Py),
and the existing importers now use the 0.15 shapes and declare much less loss.

Full recipes, vector names and detection commands are in [`docs/MIGRATIONS.md`](docs/MIGRATIONS.md).

## v0.14.0

**Two contract changes: dialogue offers replace the character ladder (breaking), and
checks gain conditional modifiers (additive, but not safe to skip).** A port must ship
both to claim 0.14.0 conformance; a project only needs the ladder migration, since the
modifier field is opt-in.

**What a port must do — dialogue offers.** `character.dialogues` and
`dialogue.availableWhen` are gone. Each dialogue now self-declares candidacy with an
`offer` object `{ character?, when?, priority? }`. Reimplement `resolveCharacterDialogue`
against offers — gather a character's offers, drop those whose `when` fails (and visited
non-`replayable` ones), and pick by **priority tier, then condition specificity, then
lowest id** — and delete any ladder/`selectDialogue` code path. If you implement
`nextContinuations`, a routed character's winner counts as forced only when its gate reads
`active_dialogue__<character>` (feed model). Re-vendor the vectors: `resolveCharacterDialogue.json`
is rewritten, `nextContinuations.json` is new, and the validator gains an `OFFER` family
plus a `MIGRATE` error; the `LADDER` cases are gone. Selection is now order-independent —
the arrangement of dialogues in a project no longer affects which one plays.

**What a project must do — dialogue offers.** A project still carrying `character.dialogues`
fails to load with a `MIGRATE` error. Convert it with `validate/migrate_ladders.py --root
<project>` (run `--check` first for the report). It preserves each ladder's winner in
every state, assigning priority tiers where specificity alone would reorder a rung; the
`INVERSION`, `SHADOWED`, and `CONFLICT` notes are the few places to eyeball.

**What a port must do — check modifiers.** `Check` gains an optional `modifiers: { when,
bonus, label? }[]`. Every modifier whose `when` holds adds its `bonus` to the check total
(active: `roll + skill + Σbonus ≥ difficulty`; passive reveal: `skill + Σbonus ≥
difficulty`). Implement the modifier sum, thread a `project` into `resolveCheck` (a
`quest`/`questOutcome` gate needs it), and add the passive-reveal threshold. `CheckResult`
gains `bonus` and `appliedModifiers`, present iff the check declares at least one modifier —
so a check without modifiers is byte-identical to before. Re-vendor `resolve_check.json`
and `choose_choice.json`. This is additive to the schema but **not safe to skip**: a
runtime that ignores modifiers rolls the wrong odds on any check that uses them — silently
wrong, not merely behind. `check.modifiers[].when` is a new condition site; walk it
wherever you walk conditions.

Full migration recipes and detection commands are in [`docs/MIGRATIONS.md`](docs/MIGRATIONS.md).

## v0.13.0

**No new rule; one conformance vector added.**

`schema/`, `validate/` and `docs/RUNTIME_CONTRACT.md` are byte-identical to `v0.12.0`. The
only change to the contract surface is in `conformance/`: a new regression-guard case,
`npc-interactable-dialogue-places`, that pins existing `LOC` and `LADDER` behaviour. It was
added while the editor's validator was refactored internally, to prove the refactor produced
identical results — not to introduce a rule.

**What a port must do:** if you vendor the conformance vectors and run them in CI, re-vendor at
this tag to pick up the new case — a conformant validator already emits its expected output, so
it passes as-is. Nothing else: no rule to implement, no schema field, no runtime change. A port
pinned to `v0.12.0` that does not run the vectors needs no action at all.

Upstream, 0.13.0's headline is git-native collaboration in the desktop editor (draft, review,
and publish narrative against a studio's own GitHub/GitLab/Bitbucket repo), plus a command-line
CLI and CI action. None of it touches the format or how a runtime reads it, which is why none of
it is here.

## v0.12.0

**No contract change.**

`schema/`, `conformance/` and `validate/` are byte-identical to `v0.11.0`. In `docs/`,
only `MIGRATIONS.md` (this release's entry) and `VERSIONING.md` (whose pinning example
advances with every tag) differ — no runtime semantics, no schema, no vectors. A port
pinned to `v0.11.0` needs no action: no re-vendoring, no suite re-run, nothing to read
beyond this paragraph.

The tag exists so that a port tracking upstream releases has an exact tag to pin, as
[`docs/INTEGRATION.md`](docs/INTEGRATION.md) requires. It is a lockstep marker, not a
change.

Upstream, 0.12.0 is a durability release for the editor application — one write path with
per-write temp names, a cross-process lock on registry read-modify-writes, a total
`validate()`, and desktop session restore. None of it touches the format, which is why
none of it is here.

## v0.11.0

**Additive to the schema, and NOT safe for an unimplementing runtime to ignore.**

### `DialogueNode.showIf` — conditional narration

A node may now carry the same condition type `choice.showIf` already used. When
the condition fails the node is **skipped**: its text is not shown, its `onEnter`
does **not** fire — a skipped node did not happen — and resolution continues at
`next`.

Every existing project loads unchanged, so there is nothing to migrate in your
data. The hazard runs the other way: **a runtime pinned below `v0.11.0`, handed a
project that uses the field, will render conditionally-hidden narration
unconditionally.** No parse error, no warning — silent wrong output. Do not treat
this the way you treated `snapshot.visitedDialogueIds` in 0.10.0.

`docs/MIGRATIONS.md` carries an exposure check: a script that answers whether a
project actually uses node-level `showIf`. A plain grep cannot, because `"showIf"`
matches every gated choice.

**If you implement a runtime**, add `resolveNode` from
[`docs/RUNTIME_CONTRACT.md`](docs/RUNTIME_CONTRACT.md) and route *every* arrival
through it: `entry`, `next`, a choice's `goto`, and a check's
`onSuccess`/`onFailure`. Six new validator conformance cases plus the reworked
`advance` and `step_dialogue` vectors pin the semantics, including the cycle case.

### New in this repo: `audits/` and `importers/`

Two bundles published here for the first time, both MIT:

- **`audits/`** — five review-only editorial audits: dialogue ladder ordering,
  character voice, character presence, quest journal, state reachability. They
  read a project and report on it.
- **`importers/`** — Yarn and Ink importers, with worked fixtures for each.

One rule governs both, and it is enforced rather than promised: **nothing in
either bundle writes prose.** The audits report and never draft. The importers
convert and never paraphrase — every emitted string is checked against the source
byte for byte. Loss is declared, never silent. See
[`PUBLISHED_SKILLS.md`](PUBLISHED_SKILLS.md).

## v0.10.0

**Additive. Nothing to migrate.** Data written for `v0.9.0` loads unchanged.

- **`snapshot.visitedDialogueIds`** — optional array of dialogue ids, sorted,
  omitted when empty. The runtime has always taken a visited set (it is what
  hides a non-`replayable` dialogue once seen), but serialized state had nowhere
  to keep one, so snapshots captured mid-playthrough came back with the set
  empty. A route starting from such a snapshot was offered one-shots the
  playthrough had already spent.

  **If you write a route runner**, seed its visited set from the start snapshot's
  `visitedDialogueIds`. Otherwise a route beginning from a captured baseline walks
  content that baseline had already consumed, and *passes* on a path no player can
  reach.

- **One behaviour correction.** A route starting from a snapshot now inherits that
  snapshot's `texts` and `questFired` ledger. `RouteRunner.cs` was already correct;
  this affects ports written from the TypeScript source, where a route whose
  baseline had already fired a once-only quest effect could fire it again.

## v0.9.0

**Breaking — one batched break.** Twelve changes shipped together so a downstream
project migrates once rather than twelve times. Every item was project-specific
vocabulary sitting in a normative position: a required field, a closed enum, or a
hardcoded constant. Any project adopting Parlance inherited one particular game's
taxonomy as a hard requirement.

| # | Change | Auto-migratable |
|---|---|---|
| 1 | `character.class` → `character.archetype`, no longer required | yes |
| 2 | `location.exits[].gateType` enum → free-form string | yes (no-op) |
| 3 | Quest tag vocabulary moves to `rules.quest.tagVocabulary` | yes |
| 4 | `location.connectsTo` removed | **no** — each link needs a spawn chosen |
| 5 | `location.region` removed, folded into `zone` | yes |
| 6 | `dialogueNode.acceptsInjections` removed | yes |
| 7 | `skill.cluster` no longer required | yes (no-op) |
| 8 | The `sp_main` spawn exemption becomes an explicit `"isDefault": true` | **no** — you name the default |
| 9 | Validator issue code `TASK` renamed `QUEST` | yes, if you parse codes |
| 10 | `dialogue.isDefault` removed; the ladder is the canonical discovery path | yes |
| 11 | `variable.kind: "item"` becomes a first-class `item` entity | yes |
| 12 | `data/routes` and `data/snapshots` move to `tests/` | yes |

Changes 2, 7 and 9 cannot break existing data — 2 and 7 only widen what validates,
and 9 touches validator output rather than files.

**Full recipes, including the scripts for 1, 5 and 6, are in
[`docs/MIGRATIONS.md`](docs/MIGRATIONS.md).** Read it before upgrading; items 4
and 8 need decisions, not a script.

---

_Publication of this repo begins at `v0.9.0`. Upstream tags `v0.6.0`–`v0.8.0`
exist and are valid contract points, but predate this repo and shipped no
binaries; `v0.1.0`–`v0.5.0` predate the MIT carve-out._
