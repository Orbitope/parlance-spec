# Changelog

Mirrors the upstream releases. Each entry corresponds to a `vX.Y.Z` tag in
Parlance; breaking changes and their migration recipes are in
[`docs/MIGRATIONS.md`](docs/MIGRATIONS.md).

Pre-1.0, breaking changes land in minor releases with no deprecation window —
see [`docs/VERSIONING.md`](docs/VERSIONING.md). Pin an exact tag and vendor the
conformance vectors at it.

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
