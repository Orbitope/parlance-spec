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

## 0.16.0 — stricter validation, a passive-only `FLOW` warning; the reference runtime published under MIT

0.16.0 is a validator release. `schema/` is unchanged, the runtime conformance vectors
(`tooling/conformance/*.json`) are unchanged, and `RUNTIME_CONTRACT.md` changed only in
one file path. **Runtimes have nothing to do**: a 0.15 runtime plays every 0.16 project
exactly as before, so this release is not on `VERSIONING.md`'s "Releases you cannot skip"
list. **Validator ports owe work:** one new `FLOW` warning, a bound on dice notation, a
capped `OFFER` tie report, ECMA-262 pattern anchoring, and total reporting over malformed
files. Eighteen new validator cases (129 in all) pin them.

**Does an existing project stay valid?** A project that passed `tooling/validate.py`
under 0.15.0 (what CI, `parlance ci-check` and the `validate` action gate on) still has
no errors, with two narrow exceptions below. Three things can still change what you see:

- **The editor now rejects unknown keys.** Every object schema in the editor's validator
  is strict, as every `schema/*.json` already declared (`additionalProperties: false`).
  An unknown or misspelled key (`isend`, `showif`, `foo`) used to be silently ignored in
  the editor and was a `SCHEMA` error in `tooling/validate.py`, so a project could look
  clean in the editor and fail CI. **The reference validator already enforced this**, so
  a project CI accepted is unaffected. A project only ever checked in the editor may now
  show `SCHEMA` errors there; delete or correct the key. `_comment` is still allowed at
  any depth in both validators, and a leftover `character.dialogues` ladder still
  reports `MIGRATE` alone.
- **Dice notation is bounded (both validators).** A `check.dice` or `rules.check.dice`
  with more than 100 dice or a die with more than 1000 sides is now a `RULES` error
  (`'101d6': at most 100 dice`, `'1d1001': a die has at most 1000 sides`). It used to
  validate, then hang or throw in the editor. The schema's `NdM` pattern did not change.
- **A new `FLOW` warning** (below) can appear on existing nodes. It is a warning, so it
  fails only a `--strict` run.

The two exceptions, both in `tooling/validate.py` only, both shapes the editor already
refused to write:

- **A custom-type row id that is not lowercase snake_case** (`"Fire Ball"`) is a `SCHEMA`
  error at load. Row ids become file names and URL segments. The editor refused to save
  one; its `validate()` still says nothing (layer difference, in
  `known_divergences.json`).
- **A pattern-checked string ending in a newline** (`"npc_keeper\n"`, `"1d20\n"`, an
  engine command `"shake\n"`) is now rejected. Python's `re.search` let `$` match
  before a trailing newline. Every JavaScript engine, and so the editor, already
  rejected these.

Projects that used to crash `tooling/validate.py` with a traceback (valid JSON, wrong
shape: a registry whose array is `null`, `types.json` as an array, a non-numeric
progression threshold, a `null` quest `stages` that other files reference, a bare-string
`loreRef`, and about twenty more) now get `SCHEMA` errors naming the file. They were
never passing.

### For validator ports

- **`FLOW` warning: every non-fallback choice is a passive check.** On a node that is not
  `isEnd`, has no `next`, and whose non-fallback choices are all `check.mode: "passive"`,
  warn: *"every non-fallback choice is a passive check ('a', 'b') — the runtime counts
  them as visible even when unrevealed, so a game that hides unrevealed passive choices
  can show nothing clickable here"*, then *", and fallback 'f' is suppressed
  (chooseChoice refuses it)"* or *", and there is no fallback"*, then *"; give the node a
  choice without a passive check"*. It reads only the node's own choices. It does not
  consult difficulty (no reveal is provable in every state), and `whenLocked: "show"`
  does not clear it. `RUNTIME_CONTRACT.md` is unchanged: a passive choice is visible
  whenever its `showIf` passes, `passiveCheckPasses` is a reveal rule the game applies on
  top, and a fallback is offered only when the visible non-fallback set is empty. Cases:
  `choice-passive-only-fallback-suppressed`, `choice-passive-only-no-fallback`,
  `choice-passive-beside-plain-clean`.
- **Dice bounds.** `N <= 100` dice and `M <= 1000` sides, reported as `RULES` errors with
  the messages above. Cases: `dice-too-many`, `dice-too-many-sides`.
- **`OFFER` ties are bucketed and capped.** Compare only offers of one character with the
  same (priority, specificity). Report the first 10 ties in id order, then **one**
  summary warning: *"character 'c': N more offer pair(s) share a priority and specificity
  and were not checked — the first 10 ties are reported above; …"*. Under the cap the
  output is unchanged. The old pairwise report produced about 500,000 warnings at 1,000
  tied offers. Case: `offer-tie-capped` (six tied offers, 15 pairs: 10 ties and a
  summary).
- **Schema `pattern` uses ECMA-262 anchoring.** `$` matches only at the end of the
  string, never before a trailing newline. A Python port should use `fullmatch` or
  rewrite `$` to `\Z` (`ecma_pattern` in `validate.py`). Cases: `id-trailing-newline`,
  `engine-command-trailing-newline`.
- **Unknown keys are `SCHEMA` errors** everywhere a schema says
  `additionalProperties: false`, except `_comment` and the legacy ladder above. Case:
  `node-unknown-key`.
- **Reporting is total.** A malformed file is a `SCHEMA` error, never a crash, and a
  valid entity that reads a malformed one (a quest's `stages`, a location's spawns, a
  route into a dialogue, a failed dialogue's `offer.when`) reads it through a shape
  check. Cases: `types-json-array`, `registry-entries-not-array`,
  `progression-thresholds-not-numbers`, `custom-row-id-not-snake-case`,
  `quest-stages-null-referenced`, `loreref-not-object`, `route-unknown-dialogue`,
  `route-unknown-choice`. Four of these are `"validators": ["python"]` today, because the
  editor's loader does not report the shape yet. Each is recorded in
  `known_divergences.json` with its widening condition.
- **Existing rule, new case:** `check-priced-failure-sets-offer-flag` pins the `CHECK`
  punishment-spiral advisory, which had no shared case.
- **Case format: an optional `at` key** inside a `must`/`mustNot` entry
  (`{"entityType", "entityId", "path"}`) says where an issue sits. Twelve cases carry it.
  Only the TypeScript harness checks it; the Python reference's issues carry no location.
  A port whose issues carry no location should ignore the key; a strict case-file
  decoder must accept it.

### For runtimes (reference runtime changes; no vector moved)

None of these changes a conformance vector, and a port need not change for any of them.
Matching them keeps a port in step with the editor.

- **State and registry lookups read own keys only.** The id pattern admits
  `constructor`, `toString` and `valueOf`. The reference runtime (JavaScript) used to
  resolve `state.flags["constructor"]` through `Object.prototype`, and `{constructor}` in
  a line interpolated a function's source. Now an absent key reads as its default.
  Ports on plain dictionaries already behaved this way; a JavaScript port should check.
- **`unlockedCodexEntries` is in ordinal (code-unit) id order**, not locale order. The
  contract does not fix the order; the reference now agrees with a plain byte compare,
  as offer resolution already did.
- **`parseDice` throws past the bounds above**, instead of hanging or throwing a
  `RangeError` deep in the probability code.
- The reference implementation moved from `editor/core/src/` to `editor/runtime/src/`
  (the one path change in `RUNTIME_CONTRACT.md`), and is published. See below.

### Not the contract, but worth knowing

- **`@orbitope/parlance-runtime` (MIT, npm).** The reference playback runtime
  (conditions, effects, stepping, checks, offers, quests, dice, interpolation, speakers)
  plus a pure `loadProjectFromFileMap`, zero dependencies, versioned with the release. It
  runs every conformance vector. A JavaScript or TypeScript game can use it instead of
  porting. Ports in other languages still need only the vectors.
- **Locale files carry `@`-prefixed metadata.** `locales/<lang>.json` may now hold
  `@sourceHashes` (key → hash of the source line each translation was made from) and
  `@outdated` (keys to re-translate). A loader that expects every value to be a string
  must skip keys starting with `@`; no real key starts with one. See `INTEGRATION.md`.
- **CLI exit codes.** `parlance init` refuses an existing project or a non-empty folder
  (exit 1) and never overwrites, even with `--force`; a usage mistake (unknown
  `--template`, mistyped flag) exits 2. `parlance ci-check`, `parlance route` and
  `tooling/validate.py` take `--annotations github|none|auto` (default: on under GitHub
  Actions), which prints one `::error`/`::warning` per issue with file and line; stdout is
  otherwise unchanged and exit codes do not move. `parlance explore --json` and
  `parlance witness --json` now print only JSON on stdout; status lines go to stderr.
- **Route `advance`.** A route step `advance: N` above 10,000 is refused
  (`advance_invalid`), and one that returns to a node in a state already seen fails as
  `advance_cycle`.
- **MCP writes.** `create_entity`, `update_entity` and `save_custom_rows` validate first
  and refuse (`written: false`, nothing on disk) when what they would write fails its own
  schema. Reference and cross-entity issues still write and are reported afterwards.

**Exactly what to run.** For a project: `python tooling/validate.py` (or `parlance
ci-check`) and fix any `SCHEMA` or `RULES` error it names. Also open the project in the
editor once if you have only validated in CI. For a runtime port: move the pin; nothing
else is required. For a validator port: add the `FLOW` rule, the dice bounds, the `OFFER`
cap and ECMA anchoring, make malformed files `SCHEMA` errors, accept the `at` key, and
re-run the 129 cases.

---

## 0.15.0 — node shapes, fallback and locked choices, line tags, engine commands; custom entity types, bindings, exclusive flag groups; BOM and Unicode-form loading

0.15.0 is a contract release. **Every project valid under 0.14.0 stays valid and behaves
identically**: shapes the validator used to reject become legal, and new optional fields
appear. Nothing needs migrating in a project. **Runtimes must upgrade**, because a 0.14
runtime handed a 0.15 shape plays it wrong with no error: it skips a guarded node that
carries choices (stranding the player), shows a fallback choice beside the choices it was
meant to replace, and may throw on the new `engine` effect. **Validator ports owe new
rules too:** `ENGINE`, the new `FLOW` findings, the `FLAG` exclusive-group error, the
`types.json` and custom-row checks, and loading a byte-order-marked file and a `loreRef` in
either Unicode form. Each item lists what a port must do.

(Strictly, a 0.14 project stays valid unless it happens to carry a `data/types.json` or
`data/bindings/` that 0.14 ignored and 0.15 now checks.)

### Node shapes and choices

- **`showIf` on a node with `choices` or `isEnd` hides the line, not the node.** Until
  now `COND` refused both shapes. A failed gate on such a node no longer skips it:
  `resolveNode` returns it, its `onEnter` fires (hiding is presentation, effects are
  state), its choices are offered, and an `isEnd` node still ends the dialogue.
  `stepDialogue` returns the new `textHidden: true` and `node.text === ""`. An
  *interstitial* gated node (no choices, not `isEnd`) is skipped exactly as before and
  still needs `next`. The `COND` "showIf together with 'choices'/'isEnd'" errors are
  gone, the onEnter advisory and the ring check apply only to skippable nodes, and a gate
  on a node with no line is still an error on every shape.
  The line gate is judged **once, on arrival, before `onEnter`** — the same moment as the
  skip gate — so a node whose own `onEnter` would fail its own `showIf` still shows its
  line. The editor's play session briefly judged it after `onEnter` (Play, the play
  build and `resumeSession` hid such a line that `stepDialogue` showed); fixed before
  release, and pinned by a new `step_dialogue.json` vector.
  *Port:* return a gated node with choices/isEnd from `resolveNode`, and add `textHidden`,
  evaluated against the arrival state.
- **`text` is optional on a node with non-empty `choices`** (schema `required` is now just
  `id`). A text-less node presents only its options. The validator adds `FLOW` error "no
  text and no choices" for a node that has neither. *Port:* tolerate an absent `text`.
- **`choice.fallback: true`.** Offered only when no non-fallback choice on the node is
  visible; its own `showIf` still applies. A node with an ungated fallback no longer gets
  the `FLOW` "may be stuck" warning. New `FLOW` warnings: more than one fallback on a
  node, and a fallback with no gated sibling. *Port:* apply the partition in
  `stepDialogue`, and reject a fallback in `chooseChoice` while it is not offered.
- **Locked choices, opt-in on both sides.** `choice.whenLocked: "hide" | "show"` (default
  `rules.choices.whenLockedDefault`, then `"hide"`) and `choice.lockedText` (localizable
  under `…/choices/<id>/lockedText`, never voiced; its placeholders are checked by `TEXT`).
  `stepDialogue` returns the new `lockedChoices`: failing choices whose `whenLocked` is
  `"show"`. `visibleChoices` keeps its exact meaning, so an engine that ignores the list
  behaves as before. New `FLOW` warning: `whenLocked`/`lockedText` on a choice with no
  `showIf`. *Port:* return `lockedChoices`. Optionally render them greyed out.
- **`chooseChoice` throws on a choice that is not selectable** — hidden, locked, or an
  unoffered fallback. Previously it applied any choice id it was handed.
- **New rules keys** (across this release): `rules.choices.whenLockedDefault`, `rules.engine.commands` and
  `rules.flag.exclusiveGroups`.
- **Conformance:** `step_dialogue.json` (24 with the tag and self-clearing-gate vectors; every vector now states `lockedChoiceIds`,
  new ones state `textHidden`/`text`), `choose_choice.json` (17, with `expectedError`
  vectors), `advance.json` (14). New validator cases: `cond-showif-with-choices` (now
  clean), `cond-showif-isend-clean`, `cond-empty-text-with-choices`,
  `textless-choices-clean`, `textless-no-choices`, `choice-fallback-*` (4),
  `choice-locked-*` (3) and `choice-when-locked-invalid`. `cond-showif-without-next` now
  seeds an interstitial node.
- **Importers** carry the three positional loss classes (a guarded line before a choice
  list, a guarded last beat, a choice list with no host line) instead of declaring them.
  Declared loss in the worked examples: The Intercept 120 → 67, Cyberharcèlement
  101 → 37, Not Weird. Queer 182 → 145.

### Tags on lines and choices, and engine commands
Additive, but not safe for a runtime to ignore. No project needs migrating: every 0.14 project is valid and behaves
identically. A port must ship both before it can claim 0.15 conformance.

- **`node.tags` / `choice.tags`** (`common.schema.json#/definitions/tags`, the shape
  `dialogue.tags` already has). *What changed:* two new optional fields. *Runtime:* pure
  pass-through. `stepDialogue` must return them unchanged on the node and on each visible
  choice. A port that rebuilds node or choice objects must copy them, and one that uses
  a strict decoder must accept them. *Validators:* no rule reads them, and they are not a
  Condition site. *Text view:* a node-scoped `~ tags: a, b` line under the node header,
  and trailing `#tag` / `#"quoted tag"` tokens on a choice line. *Vectors:*
  `step_dialogue.json` gains `nodeTags` / `visibleChoiceTags`.
- **The `engine` effect** `{ "type": "engine", "command": string, "args"?: (string |
  number | boolean)[] }`. *What changed:* a new member of the effect union. *Runtime:*
  `applyEffect` returns the state **unchanged**. The effect is returned in order inside
  `onEnterEffects` / a choice's `effects` and the host dispatches on `command`, so a
  port that throws on an unknown effect type must add this case. *Validators (both):*
  new issue code **`ENGINE`**. A command that is not lowercase snake_case is an error;
  with the new optional `rules.engine.commands` (`{ name: { args?: n | "any",
  description? } }`) declared, an undeclared command or a wrong `args` count is a
  warning. *Text view:* `+ engine <command> [args…]`. *Vectors:* `apply_effect.json`
  (state unchanged), `step_dialogue.json` / `choose_choice.json` (in order among the
  other effects), and conformance cases `engine-command-*` and `tags-on-lines-clean`.
- **Importers:** the Yarn importer maps custom commands (`<<shakeCamera 0.5>>`) to
  `engine` effects instead of declaring them lost (Cyberharcèlement: 71 carried, 27 named
  as unplaceable. The engine mapping moves no declared loss — commands were never
  prose — so the 101 → 37 there is the node shapes above).

**Exactly what to run.** Nothing for a project. For a port, add the `engine` case to your
effect switch (state unchanged), make sure tags survive `stepDialogue`, add the `ENGINE`
rule if you ship a validator, and re-run the vectors.

### Custom entity types, bindings, flag groups, and loading fixes

- **Asset bindings (`schema/binding.schema.json`, #117).** An optional
  `data/bindings/*.json` maps portrait ids, VO keys and cutscene ids to engine paths per
  `profile` (the one required field). The reference validator (`tooling/validate.py`, the
  only implementation, since bindings are not in the editor's project model) checks each
  file against the schema. It warns `BIND` on a used portrait, voiceable line or
  triggered cutscene left unbound, and on a binding naming a portrait, cutscene or VO key
  that does not exist. A VO key is `dialogue/<id>/nodes/<id>/text` for every node with
  text, matching `extractLocStrings`. Additive: a project without `bindings/` is
  unaffected. Cases: `binding-clean` and `binding-vo-dangling`, both
  `"validators": ["python"]`, with a matching `known_divergences.json` entry.
- **Exclusive flag groups (`rules.flag.exclusiveGroups`, #118).** A list of flag-id
  groups, each of at least two flags, that must never be true together. Both validators
  report `FLAG` error "sets mutually-exclusive flags simultaneously" when one effect list
  sets two flags of a group to `true`. Additive: absent means no groups. Cases:
  `flag-exclusive-group-set-together` and `flag-exclusive-group-set-apart`.
- **Custom entity types (`data/types.json`).** A project may declare its own entity types
  (`fields` of type `string`/`number`/`boolean`/`enum`/`reference`, and `array` with an
  `items` field). Rows are stored one file per row under `data/<plural>/` (nested
  folders allowed), or in a `data/<plural>.json` registry, either as
  `{ "<plural>": [ … ] }` or as an object keyed by anything with each row carrying its
  `id`. `plural` defaults to `<id>s` when absent **or empty**. A `reference` may target a
  built-in type (`skill`, `faction`, `character`, `variable`, `item`, `dialogue`,
  `quest`, `location`, `cutscene`) or another custom type by its id. Missing required
  fields and mistyped values are `SCHEMA` errors, and a dangling `reference` (including
  one list item) is a `REF` error. Additive: the file is optional, and no runtime function
  reads these entities. The reference validator also reports a row id repeated within one
  type as a `DUP` error (a loader-layer check, as for built-in registries; the TypeScript
  validator receives rows already keyed by id). Nine conformance cases pin the storage
  shapes and field kinds (`custom-entity-valid`, `-missing-field`, `-bad-reference`,
  `-registry-array`, `-registry-keyed`, `-nested-directory`, `-default-plural`,
  `-cross-type-reference`, `-field-types`). Writing them found one
  reference-validator bug, fixed here: an empty `plural` made `tooling/validate.py` read
  every JSON file under `data/` as a row of that type. The TypeScript validator already
  used `<id>s`.
- **`types.json` declarations are checked (`SCHEMA`, entity type `types`).** Both
  validators now report a declaration that is not an object; a type id that is a built-in
  reference target (references to it would resolve to the built-in); a `plural` that is
  not a plain name (letters, digits, `_`, `-` — its rows are not loaded, so `../x` can no
  longer steer a read outside `data/`), that names a built-in folder or file, or that
  another type already uses; `fields` that is not an object; and a field with an unknown
  `type`, an enum with no options, or a reference with no or an unknown target. Row ids
  and type ids named after `Object.prototype` members (`__proto__`, `constructor`) are
  ordinary data. A project the editor wrote is unaffected — its type editor already
  refused all of these. Plurals are compared **case-insensitively**, since on macOS and
  Windows `Drinks` and `drinks` (or `Dialogues` and the built-in `dialogues/`) are one
  file, and a Windows device name (`con`, `prn`, `aux`, `nul`, `com1`–`9`, `lpt1`–`9`) is
  refused as a plural. *Port:* if you ship a validator, add the checks, matching a plain
  name against the WHOLE string (a `$`-anchored regex admits a trailing newline); five
  vectors pin them (`types-declaration-plurals`, `-plural-portability`, `-fields`,
  `-not-object`, `custom-entity-prototype-keys`).
- **A UTF-8 byte-order mark is not an error.** A JSON file that starts with U+FEFF —
  what Windows PowerShell 5.1 and older Notepad write — now loads in both validators
  (`tooling/validate.py` reads files as `utf-8-sig`; the editor strips it before
  parsing), and so does such a `parlance.config.json`. Before, the reference validator
  rejected the file as invalid JSON, and the editor silently dropped it from the project.
  Additive: nothing that validated before changes. *Port:* strip one leading U+FEFF
  before parsing. Vector: `utf8-bom-loaded`.
- **A `loreRef` matches its file in either Unicode normalization form.** macOS can
  report an accented name decomposed (NFD) where git and Linux/Windows store it composed
  (NFC); the reference read as missing everywhere but on the Mac that wrote it, and on
  macOS the two validators disagreed. Both now accept a reference whose NFC or NFD form
  names an existing file. Additive: only references that were wrongly `LORE` errors
  change. *Port:* compare the reference in both forms before reporting it missing.
  Vector: `loreref-unicode-form`.
- **A `resolveQuests` vector that needs a second pass.** `resolve_quests.json` goes from
  6 to 7 vectors. The only cascade vector used to order its quests so one in-order pass
  reached the fixpoint, so a port that made one pass and stopped passed all six. The new
  vector reverses the dependency. *Port:* iterate `resolveQuests` to the fixpoint, as the
  contract already said; a one-pass implementation now fails.

---

## 0.14.0 — dialogue offers replace the ladder; checks gain conditional modifiers

0.14.0 bundles two contract changes. Do both when you move a project or a port to it:

1. **Dialogue offers replace the character ladder** — a breaking change (data and runtime).
   Existing projects must be migrated; runtimes must resolve offers instead of ladders.
2. **Conditional check modifiers** — additive to the schema, but *not* safe to ignore: a
   runtime that skips it rolls the wrong odds on any check that uses the field.

Each is written up in full below. A port must ship both before it can claim 0.14.0
conformance; a project only needs the migration in §1 (the modifier field is opt-in).

### 1. The character dialogue ladder is replaced by dialogue offers (breaking)

**What broke.** A character no longer owns an ordered `dialogues` ladder. The field
`character.dialogues` is gone, and so is the dialogue-level `availableWhen` escape hatch.
Instead, each dialogue self-declares its candidacy with an `offer` object,
`{ character?, when?, priority? }`:

- `offer.character` — who presents (offers) the dialogue (defaults to `speakerId`); a scene
  spoken by one character can be offered for another.
- `offer.when` — the gate; **absent** means the fallback (offered whenever nothing more
  specific or higher-tier is eligible).
- `offer.priority` — the tier (default 0); a higher tier beats every lower-tier candidate
  however specific.

The **presence** of the `offer` object is the opt-in. A dialogue with no `offer` is never
a candidate and is reached only by `goto`/`entersDialogue`/route/world placement.
`resolveCharacterDialogue` gathers a character's offers, drops those whose `when` fails
(and visited non-`replayable` ones), and picks by **priority tier, then condition
specificity, then lowest id** — so the arrangement of dialogues in the project no longer
affects resolution. See `RUNTIME_CONTRACT.md`'s offers section for the exact ranking, and
`conformance/resolveCharacterDialogue.json` for the vectors.

**Why it was worth breaking.** The ladder was ordered and first-match-wins, so which
dialogue played depended on array position, and a general rung placed above a specific one
silently shadowed it forever — the single most common authoring bug. Offers make selection
order-independent and *local*: a dialogue carries its own eligibility, the way a node
carries its own `showIf`, and "most specific wins" is the engine's job, not the author's
sort order. It also collapses two mechanisms (the ladder and the `availableWhen` escape
hatch) into one.

**Exactly what to run.** Three equivalent routes, one converter — the editor, the
`parlance` CLI, and the reference script apply the same algorithm (the TypeScript and
Python copies are held to one set of parity vectors under `tooling/conformance/migrate_ladders/`):

- **In the editor:** a project still carrying ladders opens with a `MIGRATE` error and a
  banner in the Validation panel — click **Convert ladders to offers**. The report appears
  in the panel and the issues clear when it finishes.
- **From a terminal, with the editor installed:** `parlance migrate <your-project>`, or
  `parlance migrate <your-project> --check` to see the report without writing.
- **Without the editor:** `python3 tooling/scripts/migrate_ladders.py --root <your-project>`
  (in the published spec repo it sits beside the validator as `validate/migrate_ladders.py`).

It rewrites every `character.dialogues` ladder into `offer` objects on the named dialogues,
assigning priority tiers where a lower rung would otherwise shadow a higher one, and folds
each dialogue-level `availableWhen` into that dialogue's `offer.when`. Run it with
`--check` first to see the report. It preserves the ladder's winner in every state — an
**INVERSION** note marks a rung that needed a priority tier because specificity alone
would have re-ordered it, and a **SHADOWED** note marks an unconditional rung that was
not last: it keeps its tier (so the rungs below stay unreachable, exactly as before) and
the validator's `OFFER` prioritized-fallback warning will point at it — drop the tier if
you would rather those lower rungs now play. Those notes are the few places to eyeball. The validators now emit a `MIGRATE` error, naming these three routes, for any
project still carrying `character.dialogues`, so a stale project fails loudly with an
actionable message rather than a bare schema reject.

**What a port must do.** Reimplement `resolveCharacterDialogue` against offers (gather,
filter, rank by tier → specificity → id) and delete any ladder/`selectDialogue` code path.
If the port implements `nextContinuations`, a routed character's winner counts as forced
only when its gate reads `active_dialogue__<character>` (see RUNTIME_CONTRACT § feed model).
Re-vendor the conformance vectors — `resolveCharacterDialogue.json` is rewritten for the
new semantics and `nextContinuations.json` is new; the validator conformance cases add an
`OFFER` family (no fallback, prioritized fallback, unbreakable tie with an exclusivity
oracle that proves opposite flag/item values and disjoint numeric ranges, names no
character, stranded speaker dialogue, a `set_active_dialogue` target with no forced offer,
a forced offer that can be out-ranked) plus `MIGRATE` and `migrate-character-dialogues`,
rename `dialogue-availablewhen-dangling` to `offer-when-dangling`, and drop the `LADDER`
cases. Two new parity artefacts ship beside them: every validator case now carries
`expected.full.json` (the reference validator's whole output) with
`validator/known_divergences.json` naming the few legitimate differences, and
`conformance/migrate_ladders/vectors.json` pins the migration itself. A port that only
reads 0.14 projects can ignore the migration vectors.

One capability is gone, deliberately: a dialogue is offered by **one** character
(`offer.character ?? speakerId`), where a ladder could list the same dialogue under two.
The migration reports the second listing as `CONFLICT` and drops it; give each character
its own short routing scene that jumps to the shared one if two characters must open it.

### 2. Checks gain conditional modifiers (additive, NOT safe to skip)

**What changed.** `Check` gains an optional `modifiers: { when: Condition, bonus: int,
label? }[]`. Every modifier whose `when` holds adds its `bonus` to the check total (active:
`roll + skill + Σbonus ≥ difficulty`; passive reveal: `skill + Σbonus ≥ difficulty`);
`difficulty` stays the fixed DC and bonuses sum. `CheckResult` gains `bonus` and
`appliedModifiers`, present only when the check declares a modifier.

**Why additive but not ignorable.** Like `DialogueNode.showIf` (0.11.0), a project that uses
the field renders wrong on a runtime that ignores it — the odds and pass/fail silently move.
A port that reads "additive" and skips this release is *wrong*, not merely behind.

**Detection.** `grep -rl '"modifiers"' data/dialogues` — if any dialogue check carries the
field, the runtime must implement it.

**What a port must do.** Implement the modifier sum (a shared `checkBonus` helper);
thread a `project` into `resolveCheck` (a `quest`/`questOutcome` `when` needs it, and the
reference implementation throws if a check with modifiers is resolved without one); add
`passiveCheckPasses` for the passive reveal threshold; re-vendor `conformance/resolve_check.json`
(now 24 vectors, some carrying `project`), `conformance/choose_choice.json`, and the six new
`check-modifier-*` / `check-difficulty-*-bonus` validator cases. `check.modifiers[].when` is a
new condition site — walk it wherever conditions are walked.

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
