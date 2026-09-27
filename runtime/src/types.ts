export type Id = string;

export type LoreRef = {
  file: string;
  anchor?: string;
};

export type Op = ">=" | "<=" | "==" | ">" | "<";

export type Condition =
  | { type: "flag"; flag: Id; value: boolean }
  | { type: "reputation"; faction: Id; op: Op; value: number }
  | { type: "skill"; skill: Id; op: Op; value: number }
  | { type: "item"; item: Id; has: boolean }
  | { type: "counter"; counter: Id; op: Op; value: number }
  // Quest progress, compared by stage ORDER (not id equality), so `>= stg_x`
  // means "at or past that stage". An unadvanced quest sits before every stage.
  // See RUNTIME_CONTRACT.md §evaluate.
  | { type: "quest"; quest: Id; op: Op; stage: Id }
  // "This quest outcome has been reached" — re-evaluates that outcome's own
  // `reachedWhen` against current state. Deliberately NOT a read of
  // `questFired`: resolveQuests only records outcomes that carry effects, so a
  // fired-record read would be silently false for every effect-less outcome.
  // See RUNTIME_CONTRACT.md §evaluate.
  | { type: "questOutcome"; quest: Id; outcome: Id }
  // Standing with a single character, the per-character counterpart of
  // `reputation`. Absent = 0.
  | { type: "relationship"; character: Id; op: Op; value: number }
  | { type: "all" | "any"; of: Condition[] }
  | { type: "not"; of: Condition };

export type Effect =
  | { type: "set_flag"; flag: Id; value: boolean }
  | { type: "adjust_reputation"; faction: Id; delta: number }
  // Per-character standing. Unclamped (a character declares no range).
  | { type: "adjust_relationship"; character: Id; delta: number }
  | { type: "give_item" | "take_item"; item: Id }
  | { type: "adjust_counter"; counter: Id; delta: number }
  | { type: "advance_quest"; quest: Id; toStage: Id }
  // Progression — grant total XP (monotonic). Authored on quest outcomes by
  // convention (XP comes from quests). `amount` should be positive.
  | { type: "grant_xp"; amount: number }
  // Feed-model dialogue routing — sets the flag `active_dialogue__{character}`
  // (see activeDialogueFlag in runtime.ts); the forced dialogue carries a
  // tier-1 offer whose `when` reads that flag. The `dialogue` field names it
  // for validation/tooling. No separate activeDialogues state exists.
  | { type: "set_active_dialogue"; character: Id; dialogue: Id }
  // Queues a cutscene; runtime only records the request (see pendingCutscene on GameState)
  | { type: "play_cutscene"; cutscene: Id }
  // Writes a string-substitution slot (variable kind:"text"), read back by
  // interpolate() wherever `{variable}` appears in player-facing text. `value`
  // is always a literal — capturing free-text player input is the engine's job,
  // which calls this effect with whatever string it collected.
  | { type: "set_text"; variable: Id; value: string }
  // An engine command: an opaque name plus literal arguments, handed to the
  // host in order among the other effects (camera shake, a sound cue). The
  // runtime changes NO state for it — applyEffect returns the state untouched
  // and the engine dispatches on `command`. Validator: `command` must be
  // snake_case (ENGINE error); when `rules.engine.commands` declares the
  // project's commands, an undeclared name or a wrong arg count is a warning.
  | { type: "engine"; command: string; args?: (string | number | boolean)[] };

/**
 * A conditional adjustment to one check. Modifiers are PER-CHECK: an item that
 * should help everywhere is re-declared on each check (or the engine reflects
 * it as a flag) — there is no global equipment layer.
 */
export type CheckModifier = {
  /**
   * Applies when this passes — evaluated against the same state the check rolls
   * against (AFTER choice.effects). Reuses the whole Condition union.
   */
  when: Condition;
  /** Added to the check total (roll + skill). Negative = harder. Integer. */
  bonus: number;
  /**
   * Author-facing name for odds breakdowns ("Crowbar in hand"). NOT player-facing
   * and not a loc string; revisit if an engine wants to show it.
   */
  label?: string;
};

export type Check = {
  mode: "active" | "passive";
  skill: Id;
  difficulty: number;
  onSuccess?: Id;
  onFailure?: Id;
  /**
   * Conditional bonuses, summed over every modifier whose `when` holds. Active:
   * `roll + skill + Σbonus >= difficulty`. Passive: `skill + Σbonus >= difficulty`
   * (see passiveCheckPasses). `difficulty` stays the fixed DC.
   */
  modifiers?: CheckModifier[];
  /** Per-check dice override in NdM notation. Defaults to the project rules / 1d20. */
  dice?: string;
  /**
   * Authoring-intent tag for active checks (validation + presentation only —
   * the runtime does not branch on it). "priced" (default for active checks):
   * failure must proceed at a cost (its onFailure branch advances). "oneshot":
   * pass-or-not-forever identity moment, exempt from the proceed requirement.
   */
  kind?: "priced" | "oneshot";
  /**
   * Only meaningful with kind:"oneshot". Declares that content reachable only by
   * passing this check is INTENDED to be unreachable on a fail, suppressing the
   * REACH oneshot-lockout warning for the nodes behind it.
   */
  acknowledgedLockout?: boolean;
};

export type Choice = {
  id: Id;
  text: string;
  showIf?: Condition;
  check?: Check;
  effects?: Effect[];
  goto?: Id;
  /**
   * Offered ONLY when no non-fallback choice on the node is visible (its own
   * `showIf`, if any, must still pass) — Ink's `* ->`, Yarn's fallthrough. A
   * node with an ungated fallback can never strand the player, so the FLOW
   * "may be stuck" warning does not fire on it. See stepResolvedNode.
   */
  fallback?: boolean;
  /**
   * What the player sees when `showIf` FAILS. `"hide"` (the engine default,
   * overridable by `rules.choices.whenLockedDefault`) drops the choice from
   * the step; `"show"` returns it in `StepResult.lockedChoices` so the engine
   * can present it greyed out. Never selectable either way — `chooseChoice`
   * throws. See resolveWhenLocked.
   */
  whenLocked?: "hide" | "show";
  /**
   * Replacement text for a choice presented locked, e.g. "[Requires
   * Engineering 3]". Localizable (`…/choices/<id>/lockedText`), never voiced.
   * Absent = show the choice's own `text`.
   */
  lockedText?: string;
  /**
   * Opaque per-choice labels (`mood:angry`), the same shape as `Dialogue.tags`.
   * Pure pass-through: `stepDialogue` returns them on the visible choice and
   * nothing in core reads them.
   */
  tags?: string[];
};

export type DialogueNode = {
  id: Id;
  /**
   * Overrides the dialogue's default speaker for this line only — a character
   * or skill id (resolveSpeaker in speaker.ts checks characters first, then
   * skills; an id matching both is a validator error). Omit for narration —
   * "no speaker" IS the narration signal, not a separate value. See
   * resolveSpeaker / effectiveSpeakerId for the one place this fallback logic
   * lives; nothing else should re-implement the `??`.
   */
  speakerId?: Id;
  /**
   * The line shown at this node. Optional ONLY on a node with non-empty
   * `choices` — a text-less choice node presents just its options (back-to-back
   * option blocks). Every other node must carry it (validator FLOW).
   */
  text?: string;
  /**
   * Optional gate on this node's DISPLAY. Two behaviours, decided by the node's
   * shape (`isSkippableNode`):
   *
   * - INTERSTITIAL node (has `next`, no choices, not isEnd): when the gate
   *   fails the node is SKIPPED and resolution continues at `next` — the text
   *   is not shown and `onEnter` DOES NOT fire, because a skipped node did not
   *   happen. Requires `next`. See resolveNode in runtime.ts — nothing else
   *   should re-implement the skip walk.
   * - node with `choices` or `isEnd`: when the gate fails only the LINE is
   *   hidden (`StepResult.textHidden`). The node is still reached, its choices
   *   are still offered (or the dialogue still ends) and `onEnter` still fires
   *   — hiding is presentation, effects are state.
   */
  showIf?: Condition;
  onEnter?: Effect[];
  isEnd?: boolean;
  /**
   * Opaque per-line labels (`mood:angry`, `sfx:door`) an engine hangs
   * animation, audio or camera work off. Pure pass-through: returned on the
   * step's node, read by no rule, not a Condition site.
   */
  tags?: string[];
  choices?: Choice[];
  /**
   * Choiceless advance to another node id in the SAME dialogue — for
   * listen-only beats (ambient chatter, narration runs) that would otherwise
   * cost a synthetic single choice. Mutually exclusive with `choices` (must be
   * non-empty) and `isEnd`; enforced by the validator, not the schema (see
   * dialogue.schema.json for why oneOf doesn't work here). Carries no effects
   * and resolves no check — effects live on the target's onEnter, exactly as
   * they would on goto arrival (advanceNode in runtime.ts reuses that same
   * arrival path). The runtime does NOT chase next chains: each advance is one
   * discrete, explicit step (see playSession.advance).
   */
  next?: Id;
  /**
   * Portrait registry id for this node only, overriding the speaking
   * character's default — for projects that author per-line expressions.
   * Omit to use the character's own portrait.
   */
  portrait?: Id;
  /** Author-only annotation. Never shown to the player; ignored by the runtime. */
  notes?: string;
};

/**
 * A dialogue's self-declaration that it can be OFFERED to the player — presented
 * when they approach its character, or discovered as a continuation. The
 * PRESENCE of this object is the opt-in: a dialogue with no `offer` is never a
 * candidate (it is reached by `goto`, `entersDialogue`, a route, or a world
 * placement). See resolveCharacterDialogue for the selection rule.
 *
 * Replaces the character-side `dialogues` ladder (ws 17, Parlance 0.14); a
 * project still carrying one gets a MIGRATE error.
 */
export type DialogueOffer = {
  /**
   * The character this dialogue is offered BY, when that is not its `speakerId`
   * (e.g. a narrated protagonist trial with no speaker). Default: `speakerId`.
   */
  character?: Id;
  /** Gate. Absent = the fallback (specificity 0), offered whenever nothing better is. */
  when?: Condition;
  /**
   * Priority TIER, compared before specificity. Default 0. A higher tier beats
   * every lower-tier candidate however specific. Most dialogues never set it;
   * forced routing (`set_active_dialogue`) uses a tier-1 offer gated on the
   * `active_dialogue__{character}` flag.
   */
  priority?: number;
};

export type Dialogue = {
  id: Id;
  title?: string;
  speakerId?: Id;
  replayable?: boolean;
  /** Self-declared offer candidacy (ws 17). See DialogueOffer. */
  offer?: DialogueOffer;
  entry: Id;
  nodes: DialogueNode[];
  loreRef?: LoreRef;
  tags?: string[];
};

export type Skill = {
  id: Id;
  name: string;
  /**
   * Optional project-defined grouping (body / mind / heart, or whatever axis the
   * project sorts its skills by). Free-form and optional: the taxonomy is
   * per-project, not a Parlance concept, so a project that doesn't group its
   * skills omits it.
   */
  cluster?: string;
  description: string;
  voice?: string;
  /**
   * Per-skill hard ceiling, overriding progression.maxSkill for this skill —
   * e.g. a signature skill that caps higher than the rest. Absent ⇒ the global
   * `progression.maxSkill` applies. See skillCap / effectiveSkill.
   */
  max?: number;
  loreRef?: LoreRef;
  tags?: string[];
};

export type Variable = {
  id: Id;
  /**
   * Player-facing display name — "Rusted Key" for an item, say. Optional;
   * `description` stays the authoring-facing note. Consumers fall back
   * `name ?? description ?? id`.
   */
  name?: string;
  /**
   * "text" is a string-substitution slot, not a gate: text variables are never
   * readable by a Condition. They exist to be interpolated into player-facing
   * strings as `{var_id}` — see interpolate() and GameState.texts.
   */
  kind: "flag" | "counter" | "text";
  description: string;
  /** boolean for flag, integer for counter, string for text. */
  default?: boolean | number | string;
  /**
   * Who writes this variable. "data" (the default) means an authored effect
   * writes it and the hygiene passes expect to find one. "engine" means the host
   * writes it at runtime — free text the player typed, or state the game
   * computes — so never-written / read-never-set are expected and suppressed.
   */
  writtenBy?: "data" | "engine";
  tags?: string[];
};

export type Faction = {
  id: Id;
  name: string;
  summary: string;
  reputationRange: { min: number; max: number };
  opposes?: Id[];
  alliedWith?: Id[];
  loreRef?: LoreRef;
  tags?: string[];
};

export type Character = {
  id: Id;
  name: string;
  /**
   * Project-defined grouping for this character — role, class, species, rank,
   * whatever axis the project sorts its cast by. Free-form and optional:
   * the taxonomy is per-project, not a Parlance concept.
   */
  archetype?: string;
  factionId?: Id;
  role?: string;
  description?: string;
  dialogueStyle?: string;
  stats?: Record<string, number>;
  /** Portrait registry id (data/portraits.json), e.g. "portrait_wren". */
  portrait?: Id;
  loreRef?: LoreRef;
  tags?: string[];
};

/**
 * One route the protagonist could take through the current stage — an
 * INTENTION in the protagonist's own voice ("Find out who moved the crates"), not a
 * task handed down by the game. The journal UI renders the current stage's
 * visible objectives as its available-routes list.
 *
 * DISPLAY-ONLY. Objectives carry no effects, no `goto`, and no per-objective
 * completion state; the runtime never reads them. `Stage.completeWhen` remains
 * the sole authority on stage completion, whichever route the player took.
 * See RUNTIME_CONTRACT.md § Quest journal.
 */
export interface Objective {
  /** Stable, unique WITHIN the stage. Validator + diff only — never rendered. */
  id: Id;
  /** Protagonist-voice intention line, shown while the stage is current. */
  text: string;
  /**
   * Visibility gate. Omitted = always visible. Gates on knowledge and
   * acquaintance (has she met this character, does she know this place) — an
   * objective shows only if she could actually name that route.
   */
  showIf?: Condition;
}

export type Stage = {
  id: Id;
  order: number;
  /**
   * RETROSPECTIVE line — what the protagonist did, shown in the journal once
   * the stage is complete. Not a to-do: the current stage's forward-looking
   * routes are `objectives`.
   */
  description: string;
  completeWhen?: Condition;
  onComplete?: Effect[];
  /**
   * Routes available while this stage is current, in authoring order (the
   * journal renders them in this order). Display-only — see Objective.
   */
  objectives?: Objective[];
};

export type Outcome = {
  id: Id;
  kind: "success" | "failure" | "neutral";
  description: string;
  reachedWhen?: Condition;
  effects?: Effect[];
};

export type Quest = {
  id: Id;
  name: string;
  summary: string;
  giverId?: Id;
  startsAvailable?: boolean;
  availableWhen?: Condition;
  closedWhen?: Condition;
  stages: Stage[];
  outcomes?: Outcome[];
  loreRef?: LoreRef;
  /**
   * Freeform labels. The journal's grouping and prioritisation (main vs. side,
   * act, faction) is driven from here. Linted against the project's declared
   * `rules.quest.tagVocabulary` when it has one. Main-vs-side is a tag, never
   * a boolean field.
   */
  tags?: string[];
  /**
   * Player-facing quest title shown in the journal. Falls back to `name` when
   * absent — `name` stays the authoring-facing label.
   */
  journalName?: string;
};

/**
 * Project-defined presentation kind for a gated exit (e.g. locked_door,
 * toll_booth, guard_post). Free-form: the engine maps it to art; Parlance only
 * checks that a gateType is paired with a gate condition.
 */
export type GateType = string;

export type SpawnRef = {
  id: Id;
  /**
   * The location's default arrival point — where the engine puts the player
   * when nothing named a specific spawn (new game, dev entry, a cutscene
   * arrival with no door). At most one per location, and exempt from the
   * unused-spawn check since no exit needs to point at it.
   *
   * Named `isDefault` rather than `default`, which is a reserved word in
   * several of the languages ports are written in.
   */
  isDefault?: boolean;
};

export type Exit = {
  id: Id;
  to: { location: Id; spawn: Id };
  gate?: Condition;
  gateType?: GateType;
  /** Dialogue that plays when the player is denied by the gate. */
  denialDialogue?: Id;
};

export type Interactable = {
  id: Id;
  kind: "npc" | "object" | "environment";
  /** For object/environment interactables: the dialogue to play. */
  dialogue?: Id;
  /** For npc interactables: runtime resolves the character's offers (resolveCharacterDialogue). */
  character?: Id;
  showIf?: Condition;
  /**
   * How the player reaches this. "walk_up" (the default when absent) is a thing
   * in space the player approaches; "on_enter" plays automatically on entering
   * the location once showIf passes (day scenes, turnbacks). Ambient barks are
   * walk_up: they are embodied by an unnamed extra at a marker, not auto-played.
   */
  trigger?: "walk_up" | "on_enter";
};

export type Location = {
  id: Id;
  name: string;
  description?: string;
  /** Project-defined grouping of locations for the zone map. */
  zone?: string;
  /** Opaque scene key for the engine to resolve (scene name, addressable, resource path). */
  scene?: string;
  spawns?: SpawnRef[];
  exits?: Exit[];
  interactables?: Interactable[];
  loreRef?: LoreRef;
  tags?: string[];
};

export type Ending = {
  id: Id;
  name: string;
  summary: string;
  /** Tone, same vocabulary as Outcome.kind. Optional — not every project sorts its endings this way. */
  kind?: "success" | "failure" | "neutral";
  unlockedBy: Condition;
  loreRef?: LoreRef;
  tags?: string[];
};

/**
 * A player-facing knowledge entry — the codex / bestiary / glossary read
 * in-game. Distinct from `/lore`, which is authoring canon and never ships:
 * this is narrative text the player sees, so it is authored here and localized
 * like any other player-facing string.
 */
export type Codex = {
  id: Id;
  name: string;
  /** The entry's player-facing text. */
  body: string;
  /** Project-defined grouping for the codex UI (people / places / history…). */
  category?: string;
  /** Reveals the entry. ABSENT = always unlocked, unlike Ending.unlockedBy. */
  unlockedBy?: Condition;
  loreRef?: LoreRef;
  tags?: string[];
};

// ---------------------------------------------------------------------------
// Items — data/items.json (flat registry, like skills/variables)
// ---------------------------------------------------------------------------

/**
 * A thing the player can carry.
 *
 * Possession is NOT a field here — it is runtime state (`GameState.inventory`),
 * written by give_item / take_item and read by the `item` condition. This
 * registry only says what an item is, which is precisely what the old
 * `variable.kind: "item"` could not: a boolean has no name to show a player.
 */
export type Item = {
  id: Id;
  /** Player-facing display name. The reason this entity exists. */
  name: string;
  description?: string;
  loreRef?: LoreRef;
  tags?: string[];
};

// ---------------------------------------------------------------------------
// Portraits — data/portraits.json (flat registry, like skills/variables)
// ---------------------------------------------------------------------------

export type Portrait = {
  id: Id;
  name?: string;
  /** Character.id this portrait belongs to, if any (named characters only). */
  character?: Id;
  tags?: string[];
};

// ---------------------------------------------------------------------------
// Cutscenes — data/cutscenes/{id}.json (one file per cutscene)
//
// A cutscene is a MANIFEST, not a script (Cutscene Manifest System v2): an
// opaque engine asset key plus the game-state effects applied when it
// completes. Motion, camera, and timing live in the engine — never in
// JSON. Staging → talk → staging is authored as a CHAIN (cutscene ends into
// a dialogue via entersDialogue; a node there can queue the next cutscene
// via play_cutscene), never by nesting dialogue inside a cutscene.
// ---------------------------------------------------------------------------

export type Cutscene = {
  id: Id;
  name: string;
  /**
   * Opaque key to an engine asset (e.g. "Cutscenes/HarbourArrival").
   * Parlance never resolves or validates the asset itself — a mismatch is the
   * engine loader's error to report, not Parlance's.
   */
  asset: string;
  /** Player may skip; skipping applies effectsOnComplete immediately. */
  skippable: boolean;
  /** The only game-state a cutscene produces, applied when it ends. */
  effectsOnComplete: Effect[];
  /** Chain: dialogue to open when the cutscene finishes. */
  entersDialogue?: Id;
  /**
   * Where the player stands when this cutscene ends. Applied by the host after
   * effectsOnComplete and after clearing pendingCutscene, before entersDialogue.
   * Motion inside the cutscene is choreography only: skipping and watching in
   * full must land in the same place with the same state. Omit for a cutscene
   * that plays in place.
   */
  arrivesAt?: { location: Id; spawn: Id };
};

/** Project-wide rules (data/rules.json). Absent ⇒ all defaults. */
export type Rules = {
  check?: {
    /** Default dice for active checks, NdM notation. Defaults to 1d20. */
    dice?: string;
    /**
     * Critical rolls (snake-eyes / boxcars). When true, every die showing its
     * MINIMUM always fails and every die showing its MAXIMUM always succeeds,
     * regardless of skill or difficulty.
     *
     * Off by default — enabling it changes every check outcome, so it is a
     * per-project opt-in rather than a silent behaviour change.
     */
    criticals?: boolean;
  };
  quest?: {
    /**
     * Controlled vocabulary for `Quest.tags`. Journal UIs group and prioritise
     * quests from these (main-vs-side is a tag, never a boolean), so a typo'd
     * tag silently falls out of the grouping — hence the OBJ warning.
     *
     * The vocabulary is per-project and lives here rather than in Parlance:
     * declare it to get the check, omit it and any tag is accepted.
     */
    tagVocabulary?: string[];
  };
  flag?: {
    exclusiveGroups?: readonly (readonly string[])[];
  };
  choices?: {
    /**
     * Project-wide default for `Choice.whenLocked` when a choice does not set
     * it. Engine default `"hide"` (a gated-out choice is dropped from the
     * step); `"show"` returns it in `lockedChoices` for greyed-out display.
     */
    whenLockedDefault?: "hide" | "show";
  };
  engine?: {
    /**
     * The project's engine commands (the `engine` effect's `command`), keyed
     * by name. Declare it and an undeclared command — or, when `args` is a
     * number, a call with a different argument count — is an ENGINE warning;
     * omit it and any command is accepted. The runtime never reads this.
     */
    commands?: Record<string, { args?: number | "any"; description?: string }>;
  };
};

/**
 * Progression config (data/progression.json). A first-class registered
 * singleton (like rules). Absent ⇒ progression disabled (no XP/levels).
 * Thresholds are tuning values in data so they can be re-balanced without code.
 */
export type Progression = {
  /** xp needed to reach each level; strictly increasing, index 0 = level 0 (usually 0). */
  xpThresholds: number[];
  /** Skill points granted per level. ≥ 1. */
  pointsPerLevel: number;
  /** Character-creation preset loadout: skillId → base value. */
  startingSkills: Record<string, number>;
  /** Per-skill hard ceiling (single global int applies to all skills). ≥ 1. */
  maxSkill: number;
};

export type ProjectData = {
  skills: Record<Id, Skill>;
  variables: Record<Id, Variable>;
  factions: Record<Id, Faction>;
  characters: Record<Id, Character>;
  dialogues: Record<Id, Dialogue>;
  quests: Record<Id, Quest>;
  locations: Record<Id, Location>;
  endings: Record<Id, Ending>;
  /**
   * Optional, unlike `endings`: a project without a codex simply omits it, and
   * every existing ProjectData literal stays valid.
   */
  codex?: Record<Id, Codex>;
  /** Item registry (data/items.json). Absent ⇒ treated as empty. */
  items?: Record<Id, Item>;
  /** Portrait registry (data/portraits.json). Absent ⇒ treated as empty. */
  portraits?: Record<Id, Portrait>;
  /** Cutscene entities (data/cutscenes/*.json). Absent ⇒ treated as empty. */
  cutscenes?: Record<Id, Cutscene>;
  /** Route test specs (data/routes/*.json). Absent ⇒ treated as empty. */
  routes?: Record<Id, RouteSpec>;
  /** Named game-state snapshots (data/snapshots/*.json). Absent ⇒ treated as empty. */
  snapshots?: Record<Id, Snapshot>;
  /** Project rules; absent fields fall back to engine defaults. */
  rules?: Rules;
  /** Progression config (data/progression.json). Absent ⇒ progression disabled. */
  progression?: Progression;
  /** Custom entity type definitions (data/types.json). Absent ⇒ treated as empty. */
  entityTypes?: Record<Id, CustomEntityDefinition>;
  /** Custom entities keyed by custom entity type ID, then entity ID. */
  customEntities?: Record<Id, Record<Id, CustomEntity>>;
};

export type CustomFieldType = "string" | "number" | "boolean" | "enum" | "reference" | "array";

export type CustomFieldDefinition = {
  type: CustomFieldType;
  required?: boolean;
  default?: unknown;
  options?: string[];
  target?: string;
  items?: CustomFieldDefinition;
};

export type CustomEntityDefinition = {
  name: string;
  plural: string;
  fields: Record<string, CustomFieldDefinition>;
};

export type CustomEntity = {
  id: Id;
  name?: string;
  [field: string]: unknown;
};

// ---------------------------------------------------------------------------
// Route types
// ---------------------------------------------------------------------------

export type RouteChoiceStep = {
  choiceId: string;
  /** Force an active check to pass or fail instead of rolling. */
  forced?: "pass" | "fail";
  /** dialogueId to pick as next continuation before making this choice. */
  continuation?: string;
};

/**
 * Consume the pending cutscene: apply its effectsOnComplete, clear
 * pendingCutscene, and enter entersDialogue if the manifest has one.
 * Only legal when the current dialogue has ended (cutscenes are atomic and
 * play between scenes) and `cutscene` matches state.pendingCutscene.
 */
export type RouteCutsceneStep = {
  cutscene: string;
};

/**
 * Walk `count` consecutive `next`-advances (N2) from the current node — the
 * choiceless counterpart of RouteChoiceStep, for recording a long ambient run
 * (narration, chatter) as one step instead of one synthetic-choice step per
 * beat. The runner asserts the current node actually declares `next` at each
 * hop and fails with a timeline dump otherwise — there is no implicit
 * "advance until you can't" behavior, matching advanceNode's own
 * one-discrete-step contract (D3).
 */
export type RouteAdvanceStep = {
  /** Number of consecutive advance() calls this step performs. Typically 1;
   *  set higher to collapse a whole next-chain into one route-file line. */
  advance: number;
};

export type RouteStep = RouteChoiceStep | RouteCutsceneStep | RouteAdvanceStep;

export type RouteAssertEnd = {
  flags?: Record<string, boolean>;
  questStages?: Record<string, string>;
  relationships?: Record<string, number>;
  forbiddenFlags?: string[];
  /** Ending whose unlockedBy must evaluate true against the final state. */
  endingAvailable?: string;
  /** Cutscene id expected in state.pendingCutscene at route end. Use null to assert none pending. */
  pendingCutscene?: string | null;
};

export type RouteSpec = {
  id: string;
  description?: string;
  dialogueId: string;
  seed?: number;
  /**
   * Id of a Snapshot to start from. Its state is the base; `startState` (if
   * also present) overlays it per top-level field. Absent ⇒ project defaults.
   */
  startSnapshot?: string;
  startState?: {
    flags?: Record<string, boolean>;
    reputation?: Record<string, number>;
    skills?: Record<string, number>;
    counters?: Record<string, number>;
    inventory?: string[];
    questStages?: Record<string, string>;
    relationships?: Record<string, number>;
    xp?: number;
    skillPointsSpent?: Record<string, number>;
  };
  steps: RouteStep[];
  assertEnd?: RouteAssertEnd;
};

/**
 * JSON-serializable form of the runtime GameState. `inventory` is a sorted
 * string array (not a Set) so it round-trips through JSON. This is THE
 * save-state contract (RUNTIME_CONTRACT.md §SerializedGameState) — engine
 * ports and snapshots both use it. Convert to/from the live GameState with
 * serializeState / deserializeState (runtime.ts).
 */
export type SerializedGameState = {
  flags: Record<string, boolean>;
  reputation: Record<string, number>;
  skills: Record<string, number>;
  counters: Record<string, number>;
  /** Item ids currently held, sorted alphabetically for stable diffs. */
  inventory: string[];
  /** questId → current stage id. Empty object when no quests have been advanced. */
  questStages: Record<string, string>;
  /** Total XP earned this playthrough (monotonic). Levels/points derive from it. */
  xp: number;
  /** skillId → skill points invested (audit + recompute of effective skills). */
  skillPointsSpent: Record<string, number>;
  /**
   * characterId → standing with that character. Omitted when empty, like
   * `texts` — so saves and snapshots written before relationships existed stay
   * valid and round-trip unchanged.
   */
  relationships?: Record<string, number>;
  /**
   * Text-variable values substituted into `{var_id}` placeholders at render
   * time. Omitted when empty, like questFired — so saves and snapshots written
   * before text variables existed stay valid and round-trip unchanged.
   */
  texts?: Record<string, string>;
  /**
   * Quest stage/outcome effects already fired (once-only), as sorted
   * `{questId}/stage/{id}` / `{questId}/outcome/{id}` keys. Omitted when none.
   */
  questFired?: string[];
  /** Cutscene id queued via play_cutscene. Absent when null/cleared. */
  pendingCutscene?: string;
};

// ---------------------------------------------------------------------------
// Snapshot — data/snapshots/{id}.json
//
// A named, reusable game-state baseline. The inner `state` is the exact
// SerializedGameState from RUNTIME_CONTRACT.md §SerializedGameState (the
// runtime save-state contract) — NOT a Parlance-specific variant — so editor
// snapshots and real player saves speak the same language. `schemaVersion`
// lives on the envelope (not inside `state`) to avoid churning the core
// serialized-state contract / its conformance vectors.
// ---------------------------------------------------------------------------

export type Snapshot = {
  /** Envelope format version. Current: 1. */
  schemaVersion: number;
  id: Id;
  name: string;
  description?: string;
  tags?: string[];
  state: SerializedGameState;
  /**
   * Dialogues already seen when this baseline was captured. Host bookkeeping
   * rather than game state — the runtime *asks* for this set (discovery filters
   * on it) but `SerializedGameState` deliberately has no field for it — so it
   * rides on the envelope next to the state, exactly where an engine save keeps
   * it. A route with `startSnapshot` seeds its visited set from here, which is
   * what keeps a spent one-shot spent. Sorted; omitted when empty.
   */
  visitedDialogueIds?: Id[];
};
