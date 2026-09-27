/**
 * Runtime semantics for Parlance data.
 *
 * This module defines the AUTHORITATIVE behavior of the narrative system —
 * what the data means when executed. Playtest, engine ports, and conformance
 * tests all derive from these functions.
 *
 * See tooling/RUNTIME_CONTRACT.md for the documented semantic decisions.
 */

import type {
  ProjectData,
  Condition,
  Effect,
  Check,
  Cutscene,
  Dialogue,
  DialogueNode,
  Choice,
  Character,
  Codex,
  Op,
  Progression,
  Skill,
  SerializedGameState,
} from "./types.js";
import { conditionReadsFlag } from "./forcedOffer.js";
import { isSkippableNode } from "./nodeGate.js";
export { isSkippableNode } from "./nodeGate.js";
// Re-export so existing `@parlance/core` consumers importing SerializedGameState
// from the runtime module keep working (the type now lives in types.ts).
export type { SerializedGameState } from "./types.js";
import {
  DEFAULT_DICE,
  diceSuccessProbability,
  formatDice,
  parseDice,
  rollDiceFaces,
  type DiceSpec,
} from "./dice.js";
import { interpolate } from "./interpolate.js";
import { ownValue } from "./own.js";

// ---------------------------------------------------------------------------
// GameState — the complete runtime state of one playthrough
// ---------------------------------------------------------------------------

export type GameState = {
  /** Boolean flags declared in variables.json (kind:"flag"). Default: false. */
  readonly flags: Readonly<Record<string, boolean>>;
  /** Faction reputation values. Clamped to faction.reputationRange on write. */
  readonly reputation: Readonly<Record<string, number>>;
  /**
   * Skill values used in condition checks and active check rolls.
   * Typically loaded from the player Character's stats at session start,
   * but any value can be set for playtesting.
   */
  readonly skills: Readonly<Record<string, number>>;
  /** Integer counters declared in variables.json (kind:"counter"). Default: 0. */
  readonly counters: Readonly<Record<string, number>>;
  /** Item ids currently held. Empty by default. */
  readonly inventory: ReadonlySet<string>;
  /** questId → current stage id, for quests advanced via advance_quest effects. */
  readonly questStages: Readonly<Record<string, string>>;
  /**
   * characterId → standing with that character ("approval", "affinity" — the
   * project decides what it means). Absent key = 0. Unclamped, like counters:
   * a character has no declared range the way a faction does.
   */
  readonly relationships: Readonly<Record<string, number>>;
  /** Total XP earned this playthrough (monotonic). Levels/points derive from it. */
  readonly xp: number;
  /** skillId → skill points invested. Effective skills = preset + this (clamped). */
  readonly skillPointsSpent: Readonly<Record<string, number>>;
  /**
   * Values for variables of kind:"text", substituted into `{var_id}`
   * placeholders in player-facing strings at render time (see interpolate).
   * Written only by the `set_text` effect. Never readable by a Condition.
   */
  readonly texts: Readonly<Record<string, string>>;
  /**
   * Quest stage/outcome effects that have already fired (resolveQuests), as
   * `{questId}/stage/{id}` / `{questId}/outcome/{id}` keys — once-only firing.
   * Absent = none fired yet.
   */
  readonly questFired?: ReadonlySet<string>;
  /** Cutscene id queued via play_cutscene, awaiting playback. Absent when none pending. */
  readonly pendingCutscene?: string;
};

/** Create a starting state from project defaults. */
export function createDefaultState(project: ProjectData): GameState {
  const flags: Record<string, boolean> = {};
  const counters: Record<string, number> = {};
  const texts: Record<string, string> = {};

  for (const v of Object.values(project.variables)) {
    if (v.kind === "flag") {
      flags[v.id] = typeof v.default === "boolean" ? v.default : false;
    } else if (v.kind === "counter") {
      counters[v.id] = typeof v.default === "number" ? v.default : 0;
    } else if (v.kind === "text") {
      // No default ⇒ the key stays ABSENT, which is what makes an
      // un-set placeholder render as its raw `{id}` instead of "".
      if (typeof v.default === "string") texts[v.id] = v.default;
    }
    // items: start out of inventory; no default
  }

  // Reputation starts at the midpoint of each faction's declared range.
  const reputation: Record<string, number> = {};
  for (const f of Object.values(project.factions)) {
    reputation[f.id] = Math.floor((f.reputationRange.min + f.reputationRange.max) / 2);
  }

  const base: GameState = {
    flags, reputation, skills: {}, counters, inventory: new Set(),
    questStages: {}, relationships: {}, xp: 0, skillPointsSpent: {}, texts,
  };
  // With progression configured, effective skills start at the preset loadout
  // (clamped to maxSkill). Without it, skills start empty (legacy behavior).
  return project.progression ? recomputeSkills(base, project.progression, project.skills) : base;
}

// ---------------------------------------------------------------------------
// evaluate — test a Condition against a GameState
// ---------------------------------------------------------------------------

/**
 * Evaluate a Condition against the current GameState.
 *
 * Takes `project` for the same reason applyEffect does: some conditions are not
 * answerable from state alone. A quest condition compares stage ORDER, which
 * only the authored quest knows. Passing the project to both entry points keeps
 * them symmetric — a port implements one calling convention, not two.
 *
 * Semantics:
 * - "all" short-circuits left-to-right on first false.
 * - "any" short-circuits left-to-right on first true.
 * - Missing flag defaults to false; missing counter/skill/reputation to 0.
 * - "flag" checks exact boolean equality (not truthiness).
 */
export function evaluate(condition: Condition, state: GameState, project: ProjectData): boolean {
  return evaluateInner(condition, state, project, new Set());
}

/**
 * How SPECIFIC a condition tree is — the "most specific offer wins" tiebreak
 * (ws 17). Lives beside `evaluate` because a port mirrors this file.
 *
 * - absent condition (a fallback offer): 0
 * - any leaf (flag/counter/reputation/skill/item/quest/questOutcome/relationship): 1
 * - `all`: SUM of members (so `all: []` scores 0 — the fallback written the long way)
 * - `any`: MIN of members — an `any` is only as specific as its weakest branch, so
 *   `any(a,b,c)` is NOT rated more specific than `a`. A plain clause count would get
 *   this backwards; `min` is the honest number.
 * - `not`: the specificity of its operand.
 *
 * Total and pure: never throws, reads no state.
 */
export function conditionSpecificity(condition: Condition | undefined): number {
  if (!condition) return 0;
  switch (condition.type) {
    case "all":
      return condition.of.reduce((sum, c) => sum + conditionSpecificity(c), 0);
    case "any":
      return condition.of.length === 0
        ? 0
        : Math.min(...condition.of.map((c) => conditionSpecificity(c)));
    case "not":
      return conditionSpecificity(condition.of);
    default:
      return 1; // any leaf
  }
}

/**
 * `visited` carries the `{quest}/{outcome}` pairs currently being resolved, so a
 * questOutcome condition that (transitively) references itself terminates
 * instead of recursing forever. Entries are removed on the way out, so it is a
 * true DFS cycle guard: two siblings may reference the same outcome.
 */
function evaluateInner(
  condition: Condition,
  state: GameState,
  project: ProjectData,
  visited: Set<string>,
): boolean {
  switch (condition.type) {
    case "flag":
      return (ownValue(state.flags, condition.flag) ?? false) === condition.value;
    case "reputation":
      return compareOp(ownValue(state.reputation, condition.faction) ?? 0, condition.op, condition.value);
    case "skill":
      return compareOp(ownValue(state.skills, condition.skill) ?? 0, condition.op, condition.value);
    case "item":
      return state.inventory.has(condition.item) === condition.has;
    case "counter":
      return compareOp(ownValue(state.counters, condition.counter) ?? 0, condition.op, condition.value);
    case "quest":
      return evaluateQuestCondition(condition, state, project);
    case "questOutcome":
      return evaluateQuestOutcomeCondition(condition, state, project, visited);
    case "relationship":
      return compareOp(ownValue(state.relationships, condition.character) ?? 0, condition.op, condition.value);
    case "all":
      return condition.of.every((c) => evaluateInner(c, state, project, visited));
    case "any":
      return condition.of.some((c) => evaluateInner(c, state, project, visited));
    case "not":
      return !evaluateInner(condition.of, state, project, visited);
  }
}

/**
 * Quest conditions compare STAGE ORDER, not id equality — `>= stg_x` means "at
 * or past that stage", which is what authors actually want and what id equality
 * cannot express.
 *
 * Two decisions worth stating (RUNTIME_CONTRACT.md §Decisions):
 *
 * - An **unadvanced quest sits before every stage**: `<` and `<=` are true,
 *   `>=`, `>` and `==` are false. So "not started yet" is `< <firstStage>` and
 *   "started" is `>= <firstStage>`.
 * - A **quest or stage the project does not define** is false for every op, and
 *   never throws. The validator reports those as REF errors at author time; the
 *   runtime must stay total for stale saves naming a since-deleted stage.
 */
function evaluateQuestCondition(
  condition: Extract<Condition, { type: "quest" }>,
  state: GameState,
  project: ProjectData,
): boolean {
  const quest = ownValue(project.quests, condition.quest);
  if (!quest) return false;

  const orderOf = (stageId: string): number | undefined =>
    quest.stages.find((s) => s.id === stageId)?.order;

  const target = orderOf(condition.stage);
  if (target === undefined) return false;

  const currentStageId = ownValue(state.questStages, condition.quest);
  // Absent key, or a stage id this quest no longer defines, both mean "before
  // every stage" — a stale save degrades to unstarted rather than throwing.
  const current = currentStageId === undefined ? undefined : orderOf(currentStageId);
  if (current === undefined) {
    return condition.op === "<" || condition.op === "<=";
  }
  return compareOp(current, condition.op, target);
}

/**
 * "Has this quest outcome been reached?" — answered by re-evaluating the
 * outcome's own `reachedWhen` against the current state.
 *
 * The tempting implementation is a lookup in `state.questFired`, and it is
 * wrong. `resolveQuests` fires an item only when it **has effects**, so an
 * outcome that records a branch without changing state never enters the fired
 * record, and a fired-record read would report it as never reached — silently,
 * forever. Re-evaluation also keeps the condition independent of whether the
 * host has called `resolveQuests` yet.
 *
 * Consequences worth stating (RUNTIME_CONTRACT.md §Decisions):
 *
 * - An outcome with **no `reachedWhen`** is never reached, matching the
 *   resolution rule that an item with no condition never fires.
 * - An **unknown quest or outcome** is false, never a throw — stale saves and
 *   since-deleted ids degrade rather than crash. The validator reports those as
 *   REF errors at author time.
 * - A **reference cycle** is false at the point it closes, via `visited`. The
 *   validator reports the cycle so authors see a real error, not a quiet false.
 */
function evaluateQuestOutcomeCondition(
  condition: Extract<Condition, { type: "questOutcome" }>,
  state: GameState,
  project: ProjectData,
  visited: Set<string>,
): boolean {
  const quest = ownValue(project.quests, condition.quest);
  if (!quest) return false;

  const outcome = (quest.outcomes ?? []).find((o) => o.id === condition.outcome);
  if (!outcome?.reachedWhen) return false;

  const key = `${condition.quest}/${condition.outcome}`;
  if (visited.has(key)) return false;

  visited.add(key);
  try {
    return evaluateInner(outcome.reachedWhen, state, project, visited);
  } finally {
    visited.delete(key);
  }
}

// ---------------------------------------------------------------------------
// applyEffect — apply one Effect, returning a new immutable GameState
// ---------------------------------------------------------------------------

/**
 * Apply a single Effect to the current state, returning a new state.
 * Reputation is clamped to the faction's declared range after adjustment.
 * advance_quest writes questStages[quest] = toStage (see RUNTIME_CONTRACT.md).
 */
export function applyEffect(
  effect: Effect,
  state: GameState,
  project: ProjectData,
): GameState {
  switch (effect.type) {
    case "set_flag":
      return { ...state, flags: { ...state.flags, [effect.flag]: effect.value } };

    case "adjust_reputation": {
      const faction = ownValue(project.factions, effect.faction);
      const current = ownValue(state.reputation, effect.faction) ?? 0;
      const next = current + effect.delta;
      const clamped = faction
        ? Math.min(faction.reputationRange.max, Math.max(faction.reputationRange.min, next))
        : next;
      return { ...state, reputation: { ...state.reputation, [effect.faction]: clamped } };
    }

    case "adjust_relationship":
      // Unclamped, unlike adjust_reputation: a character carries no declared
      // range. See RUNTIME_CONTRACT §Decisions.
      return {
        ...state,
        relationships: {
          ...state.relationships,
          [effect.character]: (ownValue(state.relationships, effect.character) ?? 0) + effect.delta,
        },
      };

    case "adjust_counter":
      return {
        ...state,
        counters: {
          ...state.counters,
          [effect.counter]: (ownValue(state.counters, effect.counter) ?? 0) + effect.delta,
        },
      };

    case "give_item": {
      const next = new Set(state.inventory);
      next.add(effect.item);
      return { ...state, inventory: next };
    }

    case "take_item": {
      const next = new Set(state.inventory);
      next.delete(effect.item);
      return { ...state, inventory: next };
    }

    case "advance_quest":
      return {
        ...state,
        questStages: { ...state.questStages, [effect.quest]: effect.toStage },
      };

    case "grant_xp":
      // Monotonic total-earned XP. Levels/points are derived from it (never a
      // spendable balance). Investing a point does not decrement xp.
      return { ...state, xp: state.xp + effect.amount };

    case "set_active_dialogue":
      // Feed model: no dedicated activeDialogues map. Setting a normal flag
      // (`active_dialogue__{character}`) lets a forced dialogue carry a tier-1
      // offer gated on it. The `dialogue` field is metadata for
      // tooling/validation; resolution is always through offers.
      return {
        ...state,
        flags: { ...state.flags, [activeDialogueFlag(effect.character)]: true },
      };

    case "play_cutscene":
      return { ...state, pendingCutscene: effect.cutscene };

    case "set_text":
      // Last-write-wins, like any other slot. `value` is a literal — the engine
      // supplies whatever string it collected from the player.
      return { ...state, texts: { ...state.texts, [effect.variable]: effect.value } };

    case "engine":
      // An engine command changes NO state. It is returned in the step's
      // effect list (onEnterEffects / a choice's effects) in order among the
      // others, and the host engine dispatches on `command`; the runtime never
      // interprets it. Returning the same reference keeps "nothing happened"
      // observable to callers that compare identity.
      return state;
  }
}

/** Apply a list of effects in order, threading state through each. */
export function applyEffects(
  effects: Effect[],
  state: GameState,
  project: ProjectData,
): GameState {
  return effects.reduce((s, e) => applyEffect(e, s, project), state);
}

// ---------------------------------------------------------------------------
// resolveCheck — roll for an active skill check
// ---------------------------------------------------------------------------

export type CheckResult = {
  passed: boolean;
  /** The raw dice sum (range depends on the dice spec). */
  roll: number;
  /** roll + skillValue. */
  total: number;
  /** The character's skill value at roll time. */
  skillValue: number;
  /** Dice notation used for this roll (e.g. "1d20", "2d6"). */
  dice: string;
  /**
   * Set only when `rules.check.criticals` is on AND every die landed on an
   * extreme. A critical OVERRIDES the arithmetic: "success" passes a check the
   * total would have failed, "failure" fails one the total would have passed.
   * Absent on an ordinary roll.
   */
  critical?: "success" | "failure";
  /**
   * Sum of every applied modifier's bonus, already folded into `total`. Present
   * ONLY when the check declares at least one modifier (0 when none applied),
   * so a check without modifiers produces a byte-identical result to before the
   * feature existed.
   */
  bonus?: number;
  /**
   * Indices into `check.modifiers` that applied, in array order. Present iff
   * `bonus` is.
   */
  appliedModifiers?: number[];
};

/** The bonus and the indices that produced it. See {@link checkBonus}. */
export type CheckBonus = { bonus: number; appliedModifiers: number[] };

/**
 * Σ of every modifier's bonus whose `when` holds against `state`, plus the
 * indices that contributed. THE single place check modifiers are summed, so the
 * roll (resolveCheck), the odds (checkSuccessProbability), the passive reveal
 * (passiveCheckPasses) and a forced result can never disagree. Total and pure.
 */
export function checkBonus(
  check: Check,
  state: GameState,
  project: ProjectData,
): CheckBonus {
  const mods = check.modifiers;
  if (!mods || mods.length === 0) return { bonus: 0, appliedModifiers: [] };
  let bonus = 0;
  const appliedModifiers: number[] = [];
  mods.forEach((m, i) => {
    if (evaluate(m.when, state, project)) {
      bonus += m.bonus;
      appliedModifiers.push(i);
    }
  });
  return { bonus, appliedModifiers };
}

/**
 * Whether a PASSIVE check reveals its choice: `skill + Σbonus >= difficulty`.
 * Passive checks do not roll — this is the threshold reveal the engine applies
 * to show or hide the option. Defined here so the editor and every port share
 * one formula (the reveal was previously left to each engine).
 */
export function passiveCheckPasses(
  check: Check,
  state: GameState,
  project: ProjectData,
): boolean {
  const skillValue = ownValue(state.skills, check.skill) ?? 0;
  return skillValue + checkBonus(check, state, project).bonus >= check.difficulty;
}

/**
 * Roll an active skill check.
 *
 * Roll model: NdM + skill_value >= difficulty (dice default 1d20).
 *   - rng() returns a value in [0, 1); each die consumes one call, in order.
 *   - roll = sum over N of (floor(rng() * M) + 1)
 *   - total = roll + state.skills[check.skill] ?? 0
 *   - passed = total >= check.difficulty
 *
 * Dice precedence: check.dice > `defaultDice` arg (from project rules) > 1d20.
 *
 * Modifiers: `total = roll + skillValue + Σbonus` over every modifier whose
 * `when` holds against `state`. Evaluating a modifier needs `project` (quest /
 * questOutcome conditions read stage order); a check WITH modifiers passed no
 * `project` throws, because silently reading those conditions as false would be
 * a hard-to-spot wrong odds. Criticals still override on faces — an all-minimum
 * roll fails no matter the bonus.
 *
 * Passive checks do not roll — they are display-only reveals (see
 * passiveCheckPasses). Call chooseChoice with mode:"passive" to handle them.
 */
export function resolveCheck(
  check: Check,
  state: GameState,
  rng: () => number,
  defaultDice: DiceSpec = DEFAULT_DICE,
  criticals = false,
  project?: ProjectData,
): CheckResult {
  const spec = check.dice ? parseDice(check.dice) : defaultDice;
  const faces = rollDiceFaces(spec, rng);
  const roll = faces.reduce((sum, face) => sum + face, 0);
  const skillValue = ownValue(state.skills, check.skill) ?? 0;

  const hasModifiers = !!check.modifiers && check.modifiers.length > 0;
  if (hasModifiers && project === undefined) {
    throw new Error("resolveCheck: check has modifiers; pass project");
  }
  const mod = hasModifiers
    ? checkBonus(check, state, project as ProjectData)
    : undefined;
  const total = roll + skillValue + (mod?.bonus ?? 0);

  let passed = total >= check.difficulty;
  let critical: "success" | "failure" | undefined;

  if (criticals) {
    // Every die on its extreme. Checked on FACES, not the total: 7 on 2d6 is
    // 1+6 or 3+4, and only one of those is interesting.
    if (faces.every((f) => f === spec.m)) {
      critical = "success";
      passed = true;
    } else if (faces.every((f) => f === 1)) {
      critical = "failure";
      passed = false;
    }
  }

  return {
    passed, roll, total, skillValue, dice: formatDice(spec),
    ...(critical !== undefined && { critical }),
    ...(mod !== undefined && { bonus: mod.bonus, appliedModifiers: mod.appliedModifiers }),
  };
}

/** Whether this project enables critical rolls (rules.check.criticals). */
export function projectCriticals(project: ProjectData): boolean {
  return project.rules?.check?.criticals === true;
}

/** Resolve the effective default dice for a project (rules.check.dice or 1d20). */
export function projectDice(project: ProjectData): DiceSpec {
  const notation = project.rules?.check?.dice;
  return notation ? parseDice(notation) : DEFAULT_DICE;
}

/**
 * The odds a check passes right now, as a 0..1 fraction — the number a UI shows
 * beside an active check.
 *
 * Exists so nothing has to re-derive the dice precedence or remember the
 * criticals rule: it resolves `check.dice > rules.check.dice > 1d20` and reads
 * `rules.check.criticals` exactly as resolveCheck does. A displayed probability
 * that disagrees with the roll is a trust bug the player WILL notice, so both
 * numbers come from here and from resolveCheck, never from a caller's own maths.
 *
 * Passive checks are a threshold reveal, not a roll, so they have no odds and
 * this returns null for them rather than a misleading 0 or 1.
 */
export function checkSuccessProbability(
  check: Check,
  state: GameState,
  project: ProjectData,
): number | null {
  if (check.mode !== "active") return null;
  const spec = check.dice ? parseDice(check.dice) : projectDice(project);
  const skill = ownValue(state.skills, check.skill) ?? 0;
  const bonus = checkBonus(check, state, project).bonus;
  return diceSuccessProbability(spec, skill + bonus, check.difficulty, projectCriticals(project));
}

// ---------------------------------------------------------------------------
// stepDialogue — get current node + visible choices (after applying onEnter)
// ---------------------------------------------------------------------------

export type StepResult = {
  /**
   * The resolved node. When `textHidden` is true its `text` is `""` — the
   * authored line is withheld, so a consumer that only reads `text` still
   * renders no line.
   */
  node: DialogueNode;
  /**
   * Choices the player may SELECT: every non-fallback choice whose showIf
   * passes, or — only when that set is empty — every fallback choice whose
   * showIf passes. Authored order is preserved.
   */
  visibleChoices: Choice[];
  /**
   * Choices whose showIf FAILED and whose `whenLocked` resolves to "show"
   * (see resolveWhenLocked): present them greyed out, with `lockedText` when
   * set. Never selectable — `chooseChoice` throws on one. A runtime that
   * ignores this list behaves exactly as before (the choice stays hidden).
   */
  lockedChoices: Choice[];
  /**
   * True when the node carries a `showIf` that failed on a node with choices
   * or isEnd: the LINE is hidden (node.text is ""), but the node is still
   * reached — its choices are offered / the dialogue ends, and onEnter fires.
   * An interstitial node whose gate fails is skipped by resolveNode instead
   * and never appears here.
   */
  textHidden: boolean;
  /** Effects from node.onEnter (caller should apply to state). */
  onEnterEffects: Effect[];
};

/** Whether a node's line is withheld at this state: a failed gate on a non-skippable node. */
export function nodeTextHidden(node: DialogueNode, state: GameState, project: ProjectData): boolean {
  return !!node.showIf && !isSkippableNode(node) && !evaluate(node.showIf, state, project);
}

/**
 * How a choice whose showIf fails is presented: per-choice `whenLocked`, else
 * the project's `rules.choices.whenLockedDefault`, else `"hide"`.
 */
export function resolveWhenLocked(choice: Choice, project: ProjectData): "hide" | "show" {
  return choice.whenLocked ?? project.rules?.choices?.whenLockedDefault ?? "hide";
}

/**
 * Partition a node's choices at a state into the selectable set and the
 * locked-but-shown set. THE one place the fallback and whenLocked rules
 * live; stepResolvedNode and chooseChoice both read it so a choice can never
 * be selectable in one and not the other.
 */
export function partitionChoices(
  node: DialogueNode,
  state: GameState,
  project: ProjectData,
): { visibleChoices: Choice[]; lockedChoices: Choice[] } {
  const all = node.choices ?? [];
  const passes = all.map((ch) => !ch.showIf || evaluate(ch.showIf, state, project));
  const anyPrimary = all.some((ch, i) => !ch.fallback && passes[i]);
  const visibleChoices = all.filter((ch, i) => passes[i] && (anyPrimary ? !ch.fallback : !!ch.fallback));
  const lockedChoices = all.filter((ch, i) => !passes[i] && resolveWhenLocked(ch, project) === "show");
  return { visibleChoices, lockedChoices };
}

/**
 * Evaluate what the player sees at a given node.
 * Does NOT apply onEnter effects — the caller decides when to apply them
 * (on first arrival; not on replay). Use applyEffects() on onEnterEffects.
 *
 * The returned `node.text` and choice texts are INTERPOLATED (`{var_id}` →
 * state.texts). The underlying entity objects are never mutated — a shallow
 * copy is made only when a string actually changes, so callers comparing node
 * identity for unchanged text still see the original object.
 */
/**
 * Walk past INTERSTITIAL nodes whose `showIf` fails, following `next`, and
 * return the first node that is actually reached.
 *
 * This is THE one place the skip walk lives. Every arrival into a dialogue —
 * `entry`, a `next` advance, a choice `goto`, a check's onSuccess/onFailure —
 * goes through here, so a conditional node behaves identically however it is
 * reached. A skipped node is inert: no text, no effects, no transcript entry.
 *
 * A node with `choices` or `isEnd` is never skipped (isSkippableNode): a failed
 * gate there hides only its line — stepResolvedNode reports `textHidden` — so
 * the player still gets the choices, or the dialogue still ends.
 *
 * The invariants it relies on are validator errors (COND), not runtime
 * concerns, so violating them throws rather than guessing: a skippable node
 * carrying `showIf` always has `next`, and a `next` chain always terminates
 * at an unconditional node.
 */
export function resolveNode(
  dialogue: Dialogue,
  nodeId: string,
  state: GameState,
  project: ProjectData,
): DialogueNode {
  const seen = new Set<string>();
  let currentId = nodeId;
  for (;;) {
    const node = dialogue.nodes.find((n) => n.id === currentId);
    if (!node) throw new Error(`Node '${currentId}' not found in dialogue '${dialogue.id}'`);
    if (!node.showIf || !isSkippableNode(node) || evaluate(node.showIf, state, project)) return node;
    if (seen.has(currentId)) {
      throw new Error(
        `Cycle among conditional nodes in dialogue '${dialogue.id}' at '${currentId}'`,
      );
    }
    seen.add(currentId);
    if (!node.next) {
      throw new Error(
        `Node '${currentId}' in dialogue '${dialogue.id}' has showIf but no 'next' to skip to`,
      );
    }
    currentId = node.next;
  }
}

/**
 * StepResult for a node that has ALREADY been resolved.
 *
 * Split out because resolution must happen exactly ONCE per arrival, against
 * the state at arrival time. A caller that resolves, applies the node's
 * `onEnter`, and then calls `stepDialogue` again would resolve a second time
 * against post-effect state — and a node whose own `onEnter` flips its own
 * `showIf` would then be skipped after already being shown, producing a step
 * whose text and choices come from different nodes.
 */
export function stepResolvedNode(
  node: DialogueNode,
  state: GameState,
  project: ProjectData,
): StepResult {
  const parts = partitionChoices(node, state, project);
  const visibleChoices = parts.visibleChoices.map((ch) => interpolateChoice(ch, state));
  const lockedChoices = parts.lockedChoices.map((ch) => interpolateChoice(ch, state));
  const textHidden = nodeTextHidden(node, state, project);

  return {
    node: textHidden ? { ...node, text: "" } : interpolateNode(node, state),
    visibleChoices,
    lockedChoices,
    textHidden,
    onEnterEffects: node.onEnter ?? [],
  };
}

export function stepDialogue(
  dialogue: Dialogue,
  nodeId: string,
  state: GameState,
  project: ProjectData,
): StepResult {
  // NOTE: the node returned may not be the node whose id was requested — a
  // conditional node is skipped here. Callers must surface the RESOLVED id.
  return stepResolvedNode(resolveNode(dialogue, nodeId, state, project), state, project);
}

/** A node with its player-facing `text` interpolated. Same object when unchanged (or text-less). */
function interpolateNode(node: DialogueNode, state: GameState): DialogueNode {
  if (node.text === undefined) return node;
  const text = interpolate(node.text, state);
  return text === node.text ? node : { ...node, text };
}

/** A choice with its player-facing `text` (and `lockedText`) interpolated. Same object when unchanged. */
function interpolateChoice(choice: Choice, state: GameState): Choice {
  const text = interpolate(choice.text, state);
  const lockedText = choice.lockedText === undefined ? undefined : interpolate(choice.lockedText, state);
  if (text === choice.text && lockedText === choice.lockedText) return choice;
  return { ...choice, text, ...(lockedText !== undefined && { lockedText }) };
}

// ---------------------------------------------------------------------------
// chooseChoice — resolve a player choice, returning the next node + new state
// ---------------------------------------------------------------------------

export type ChoiceOutcome = {
  /** Next node id, or null if this is a terminal (isEnd) choice. */
  nextNodeId: string | null;
  newState: GameState;
  /** Present if the choice had an active check. */
  checkResult?: CheckResult;
};

/** Where a choice leads, once its effects have already been applied. */
export type ChoiceTarget = {
  /** Next node id, or null if this is a terminal (isEnd) choice. */
  nextNodeId: string | null;
  /** Present if the choice had an active check. */
  checkResult?: CheckResult;
};

/**
 * Resolve where a choice leads, given state its effects have ALREADY been
 * applied to. Split out of `chooseChoice` so a caller that needs per-effect
 * snapshots (playSession, for its applied-effect log) can apply the effects
 * once, keep the intermediate states, and still route through this one
 * implementation of the check/goto rules rather than a second copy.
 */
export function resolveChoiceTarget(
  choice: Choice,
  stateAfterEffects: GameState,
  project: ProjectData,
  rng: () => number = Math.random,
): ChoiceTarget {
  if (choice.check && choice.check.mode === "active") {
    const checkResult = resolveCheck(
      choice.check,
      stateAfterEffects,
      rng,
      projectDice(project),
      projectCriticals(project),
      project,
    );
    const nextNodeId = checkResult.passed
      ? (choice.check.onSuccess ?? null)
      : (choice.check.onFailure ?? null);
    return { nextNodeId, checkResult };
  }

  if (choice.goto) return { nextNodeId: choice.goto };

  // Terminal choice
  return { nextNodeId: null };
}

/**
 * Resolve a player's choice selection.
 *
 * Sequence:
 *   1. Apply choice.effects to state.
 *   2. If active check: roll resolveCheck(), advance to onSuccess/onFailure.
 *   3. If goto: advance to goto node.
 *   4. No destination (terminal choice on isEnd node): nextNodeId = null.
 *
 * Passive checks: treated as a plain goto (the check is display-only).
 * No state mutation happens for passive checks beyond any explicit effects.
 *
 * Throws when the choice is not SELECTABLE at `state` — its showIf fails
 * (hidden or locked), or it is a fallback while a non-fallback choice is
 * visible. Same partition as stepDialogue, against the same state the caller
 * presented, so the engine can never take a choice it did not offer.
 */
export function chooseChoice(
  dialogue: Dialogue,
  nodeId: string,
  choiceId: string,
  state: GameState,
  project: ProjectData,
  rng: () => number = Math.random,
): ChoiceOutcome {
  const node = dialogue.nodes.find((n) => n.id === nodeId);
  if (!node) throw new Error(`Node '${nodeId}' not found in dialogue '${dialogue.id}'`);

  const choice = (node.choices ?? []).find((c) => c.id === choiceId);
  if (!choice) throw new Error(`Choice '${choiceId}' not found in node '${nodeId}'`);
  if (!partitionChoices(node, state, project).visibleChoices.includes(choice)) {
    throw new Error(`Choice '${choiceId}' in node '${nodeId}' is not selectable at this state (hidden, locked, or an unoffered fallback)`);
  }

  const newState = applyEffects(choice.effects ?? [], state, project);
  const target = resolveChoiceTarget(choice, newState, project, rng);
  return { ...target, newState };
}

// ---------------------------------------------------------------------------
// advanceNode — choiceless advance via DialogueNode.next
// ---------------------------------------------------------------------------

export type AdvanceOutcome = {
  nextNodeId: string;
  newState: GameState;
};

/**
 * Resolve a node's `next` pointer — advancing a listen-only beat (ambient
 * chatter, narration) with no player choice involved.
 *
 * Deliberately narrow, unlike chooseChoice:
 *   - no effects are applied and no check is resolved here (next carries
 *     neither); `newState` is returned unchanged so callers can treat this
 *     uniformly with ChoiceOutcome, but there is nothing to compute.
 *   - the target's onEnter is NOT applied here, exactly like chooseChoice —
 *     that stays the caller's job (playSession.buildArrivalStep), which is
 *     what makes advance-arrival and goto-arrival identical (see
 *     playSession.advance).
 *   - does not chase further `next` pointers. One call = one discrete step.
 *
 * Throws (does not return a problem) on a node with no `next`, or a `next`
 * pointing at a node absent from this dialogue — the validator and the
 * client UI both prevent constructing this call in the first place, so
 * reaching either case means a bug upstream, and silence would hide it.
 */
export function advanceNode(
  dialogue: Dialogue,
  nodeId: string,
  state: GameState,
  project: ProjectData,
): AdvanceOutcome {
  const node = dialogue.nodes.find((n) => n.id === nodeId);
  if (!node) throw new Error(`Node '${nodeId}' not found in dialogue '${dialogue.id}'`);
  if (!node.next) throw new Error(`Node '${nodeId}' in dialogue '${dialogue.id}' has no 'next' to advance to`);

  const target = dialogue.nodes.find((n) => n.id === node.next);
  if (!target) {
    throw new Error(`Node '${nodeId}' in dialogue '${dialogue.id}' has next '${node.next}', which does not exist`);
  }

  // Resolve through any conditional nodes so the id returned is the node the
  // player will actually see, not one that is about to be skipped.
  return { nextNodeId: resolveNode(dialogue, target.id, state, project).id, newState: state };
}

// ---------------------------------------------------------------------------
// SerializedGameState — JSON-safe representation for conformance suite and
// external consumers who need to store/transmit state
// ---------------------------------------------------------------------------

// SerializedGameState now lives in types.ts (re-exported above) — it's the
// shared save-state contract used by snapshots too. serializeState /
// deserializeState below convert to/from the live GameState.

/** Convert a live GameState to its JSON-safe form. */
export function serializeState(state: GameState): SerializedGameState {
  return {
    flags: { ...state.flags },
    reputation: { ...state.reputation },
    skills: { ...state.skills },
    counters: { ...state.counters },
    inventory: [...state.inventory].sort(),
    questStages: { ...state.questStages },
    xp: state.xp,
    skillPointsSpent: { ...state.skillPointsSpent },
    ...(Object.keys(state.relationships).length > 0 && { relationships: { ...state.relationships } }),
    ...(Object.keys(state.texts).length > 0 && { texts: { ...state.texts } }),
    ...(state.questFired && state.questFired.size > 0 && { questFired: [...state.questFired].sort() }),
    ...(state.pendingCutscene !== undefined && { pendingCutscene: state.pendingCutscene }),
  };
}

/** Reconstruct a live GameState from its JSON-safe form. */
export function deserializeState(s: SerializedGameState): GameState {
  return {
    flags: s.flags,
    reputation: s.reputation,
    skills: s.skills,
    counters: s.counters,
    inventory: new Set(s.inventory),
    questStages: s.questStages ?? {},
    relationships: s.relationships ?? {},
    xp: s.xp ?? 0,
    skillPointsSpent: s.skillPointsSpent ?? {},
    texts: s.texts ?? {},
    ...(s.questFired && s.questFired.length > 0 && { questFired: new Set(s.questFired) }),
    ...(s.pendingCutscene !== undefined && { pendingCutscene: s.pendingCutscene }),
  };
}

// ---------------------------------------------------------------------------
// Progression — XP → levels → skill points → invested skills (all pure)
//
// `xp` is total-earned (monotonic); levels and points are DERIVED from it, so
// there is never a desync between XP and level. Effective skills are recomputed
// as preset + invested (clamped to maxSkill), so the existing check machinery —
// which reads state.skills — needs zero changes. See RUNTIME_CONTRACT.md.
// ---------------------------------------------------------------------------

/** Highest threshold index ≤ xp (thresholds are strictly increasing). */
export function levelForXp(xp: number, config: Progression): number {
  let level = 0;
  for (let i = 0; i < config.xpThresholds.length; i++) {
    if (xp >= (config.xpThresholds[i] ?? Infinity)) level = i;
    else break;
  }
  return level;
}

/** Total skill points ever granted at this xp: level × pointsPerLevel. */
export function pointsEarned(xp: number, config: Progression): number {
  return levelForXp(xp, config) * config.pointsPerLevel;
}

/**
 * The hard ceiling for one skill: its own `max` (skills.json) if set, else the
 * project-wide `progression.maxSkill`. Lets a signature skill cap higher (or a
 * deliberately shallow one cap lower) than the rest.
 */
export function skillCap(
  skillId: string,
  config: Progression,
  skills?: Readonly<Record<string, Skill>>,
): number {
  return skills?.[skillId]?.max ?? config.maxSkill;
}

/**
 * Effective value of a skill: preset loadout + points invested, clamped to that
 * skill's ceiling. This is what checks compare against. Pass `skills` to honour
 * per-skill `max` overrides; omit it for the global ceiling only.
 */
export function effectiveSkill(
  skillId: string,
  state: GameState,
  config: Progression,
  skills?: Readonly<Record<string, Skill>>,
): number {
  const preset = config.startingSkills[skillId] ?? 0;
  const invested = ownValue(state.skillPointsSpent, skillId) ?? 0;
  return Math.min(preset + invested, skillCap(skillId, config, skills));
}

/** Unspent points = earned − Σ invested. A derived value; never stored. */
export function availablePoints(state: GameState, config: Progression): number {
  let spent = 0;
  for (const v of Object.values(state.skillPointsSpent)) spent += v;
  return pointsEarned(state.xp, config) - spent;
}

/**
 * Recompute state.skills = effectiveSkill(preset + invested) for every skill in
 * the preset or with points invested. Non-progression skills are preserved.
 * Call on load and after any invest so checks read the correct effective value.
 */
export function recomputeSkills(
  state: GameState,
  config: Progression,
  skills?: Readonly<Record<string, Skill>>,
): GameState {
  const next: Record<string, number> = { ...state.skills };
  const ids = new Set<string>([
    ...Object.keys(config.startingSkills),
    ...Object.keys(state.skillPointsSpent),
  ]);
  for (const id of ids) next[id] = effectiveSkill(id, state, config, skills);
  return { ...state, skills: next };
}

/**
 * Spend one skill point on `skillId`. Player-driven (level-up UI), NOT an
 * effect. Guarded no-op unless an unspent point is available AND the skill is
 * below the ceiling — never silently wastes a point on a capped skill.
 */
export function investSkillPoint(
  state: GameState,
  skillId: string,
  config: Progression,
  skills?: Readonly<Record<string, Skill>>,
): GameState {
  if (availablePoints(state, config) <= 0) return state;
  if (effectiveSkill(skillId, state, config, skills) >= skillCap(skillId, config, skills)) return state;
  const skillPointsSpent = {
    ...state.skillPointsSpent,
    [skillId]: (ownValue(state.skillPointsSpent, skillId) ?? 0) + 1,
  };
  return recomputeSkills({ ...state, skillPointsSpent }, config, skills);
}

// ---------------------------------------------------------------------------
// Quest resolution — fire stage/outcome effects when their conditions hold
//
// advance_quest only RECORDS a stage id; the effects authored on quest stages
// (`onComplete`) and outcomes (`effects`) fire here. Rules (deliberately dumb,
// see RUNTIME_CONTRACT.md):
//   - An item fires when it HAS effects, HAS a condition (completeWhen /
//     reachedWhen), the condition evaluates true, and it has not fired before.
//   - Firing is once-only per playthrough, recorded in state.questFired.
//   - An item with effects but NO condition never fires (validator warns).
//   - Resolution runs to a fixpoint: one firing's effects may satisfy another
//     item's condition. Termination is guaranteed because each item fires at
//     most once.
//   - Deterministic order: quests by id, stages then outcomes in array order.
// ---------------------------------------------------------------------------

export type QuestFiring = {
  quest: string;
  kind: "stage" | "outcome";
  /** The stage / outcome id that fired. */
  id: string;
  /** The effects it applied, in order. */
  effects: Effect[];
};

/** The questFired record key for a stage/outcome. */
export function questFiredKey(questId: string, kind: "stage" | "outcome", id: string): string {
  return `${questId}/${kind}/${id}`;
}

/**
 * Evaluate every quest's stage `completeWhen` / outcome `reachedWhen` against
 * the state and apply the effects of newly-satisfied items, once each. Returns
 * the resulting state plus the ordered list of firings (empty = no change; the
 * input state object is returned unchanged in that case).
 *
 * The play session runs this after every state transition, so authored quest
 * effects (XP grants, rep changes, follow-up flags) actually happen in play.
 */
export function resolveQuests(
  state: GameState,
  project: ProjectData,
): { state: GameState; firings: QuestFiring[] } {
  const firings: QuestFiring[] = [];
  const fired = new Set(state.questFired ?? []);
  let current = state;

  const tryFire = (
    questId: string,
    kind: "stage" | "outcome",
    id: string,
    condition: Condition | undefined,
    effects: Effect[] | undefined,
  ): boolean => {
    if (!effects || effects.length === 0) return false;
    if (!condition) return false; // unconditioned effects never auto-fire
    const key = questFiredKey(questId, kind, id);
    if (fired.has(key)) return false;
    if (!evaluate(condition, current, project)) return false;
    current = applyEffects(effects, current, project);
    fired.add(key);
    firings.push({ quest: questId, kind, id, effects });
    return true;
  };

  const questIds = Object.keys(project.quests).sort();
  let changed = true;
  while (changed) {
    changed = false;
    for (const qid of questIds) {
      const quest = project.quests[qid]!;
      for (const st of quest.stages) {
        if (tryFire(qid, "stage", st.id, st.completeWhen, st.onComplete)) changed = true;
      }
      for (const oc of quest.outcomes ?? []) {
        if (tryFire(qid, "outcome", oc.id, oc.reachedWhen, oc.effects)) changed = true;
      }
    }
  }

  if (firings.length === 0) return { state, firings };
  return { state: { ...current, questFired: fired }, firings };
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function compareOp(left: number, op: Op, right: number): boolean {
  switch (op) {
    case ">=": return left >= right;
    case "<=": return left <= right;
    case "==": return left === right;
    case ">":  return left > right;
    case "<":  return left < right;
  }
}

// ---------------------------------------------------------------------------
// Character dialogue offers — feed-model resolution (single source of truth)
// ---------------------------------------------------------------------------

/**
 * The flag name a `set_active_dialogue` effect for `characterId` sets. The
 * forced dialogue is expected to carry a tier-1 offer gated on this flag.
 * Clearing the flag (set false) lets resolution fall to the next-best offer.
 */
export function activeDialogueFlag(characterId: string): string {
  return `active_dialogue__${characterId}`;
}

/**
 * The dialogue a character currently OFFERS, or null (ws 17 — saliency model).
 *
 * A dialogue opts in by carrying an `offer`; it is offered BY
 * `offer.character ?? speakerId`. Among a character's offers, the ones whose
 * `offer.when` passes (absent = always) are eligible — minus, when a `visited`
 * set is given, the non-replayable ones already seen. The winner is the most
 * SALIENT eligible offer:
 *
 *   1. priority tier   descending  (offer.priority ?? 0)
 *   2. specificity     descending  (conditionSpecificity(offer.when))
 *   3. id              ascending   (ordinal / UTF-16 code-unit compare)
 *
 * There is no array order anywhere — reordering files changes nothing. Re-entry
 * is just re-running this against current state. Returns null if the character
 * has no eligible offer.
 *
 * `visited` is optional: an engine that tracks no visited set gets the pure
 * state answer (what NPC-interactable resolution wants). `offerIndex` is an
 * optional prebuilt `indexOffersByCharacter` result — pass it when resolving
 * many characters at once (nextContinuations) to avoid rescanning every
 * dialogue per character.
 */
export function resolveCharacterDialogue(
  state: GameState,
  character: Character,
  project: ProjectData,
  visited?: ReadonlySet<string>,
  offerIndex?: ReadonlyMap<string, Dialogue[]>,
): string | null {
  const offers = offerIndex
    ? (offerIndex.get(character.id) ?? [])
    : Object.values(project.dialogues).filter(
        // `!= null`: hand-edited data can carry `offer: null`, which the guard
        // reports but the runtime must still survive.
        (d) => d.offer != null && (d.offer.character ?? d.speakerId) === character.id,
      );

  return resolveOffer(offers, state, project, visited);
}

/**
 * Pick the most salient eligible offer from a character's candidate list.
 * Split out so the sort/tiebreak rule lives in exactly one place.
 */
function resolveOffer(
  offers: Dialogue[],
  state: GameState,
  project: ProjectData,
  visited?: ReadonlySet<string>,
): string | null {
  const eligible = offers.filter((d) => {
    if (d.offer?.when && !evaluate(d.offer.when, state, project)) return false;
    if (visited && d.replayable !== true && visited.has(d.id)) return false;
    return true;
  });
  if (eligible.length === 0) return null;
  return eligible.reduce((best, d) => (betterOffer(d, best) ? d : best)).id;
}

/** True if offer `a` outranks `b`: higher tier, then higher specificity, then lower ordinal id. */
function betterOffer(a: Dialogue, b: Dialogue): boolean {
  const pa = a.offer?.priority ?? 0;
  const pb = b.offer?.priority ?? 0;
  if (pa !== pb) return pa > pb;
  const sa = conditionSpecificity(a.offer?.when);
  const sb = conditionSpecificity(b.offer?.when);
  if (sa !== sb) return sa > sb;
  return a.id < b.id; // ordinal (UTF-16 code-unit) compare — NOT localeCompare
}

/**
 * Group a project's OFFERED dialogues by the character that offers them
 * (`offer.character ?? speakerId`), for resolving many characters at once.
 * Dialogues without an `offer` are skipped.
 */
export function indexOffersByCharacter(project: ProjectData): ReadonlyMap<string, Dialogue[]> {
  const index = new Map<string, Dialogue[]>();
  for (const dialogue of Object.values(project.dialogues)) {
    if (!dialogue.offer) continue;
    const key = dialogue.offer.character ?? dialogue.speakerId;
    if (!key) continue;
    const bucket = index.get(key);
    if (bucket) bucket.push(dialogue);
    else index.set(key, [dialogue]);
  }
  return index;
}

/**
 * Clear the `active_dialogue__{characterId}` flag (set it false), so the
 * character's forced (tier-1) offer stops winning and resolution falls to the
 * next-best offer. Call this after a forced dialogue has been consumed to avoid
 * re-offering it.
 */
export function clearActiveDialogue(characterId: string, state: GameState): GameState {
  return { ...state, flags: { ...state.flags, [activeDialogueFlag(characterId)]: false } };
}

/** Clear pendingCutscene, e.g. once playback has ended or handed off to dialogue. */
export function clearPendingCutscene(state: GameState): GameState {
  const { pendingCutscene: _drop, ...rest } = state;
  return rest;
}

// ---------------------------------------------------------------------------
// getPortrait — resolve which portrait to show for a dialogue node
// ---------------------------------------------------------------------------

/**
 * Resolve the portrait registry id to render for a dialogue node.
 * Priority: node.portrait (Tier 2 override) > character.portrait > null.
 */
export function getPortrait(node: DialogueNode, character: Character | undefined): string | null {
  if (node.portrait) return node.portrait;
  if (character?.portrait) return character.portrait;
  return null;
}

// ---------------------------------------------------------------------------
// nextContinuations — what to offer the player when a scene ends (M3b)
// ---------------------------------------------------------------------------

export type DialogueContinuation = {
  kind: "dialogue";
  /**
   * The character key this continuation belongs to. For a queued continuation
   * this is the `set_active_dialogue` effect's `character` (the activeDialogues
   * key) — NOT necessarily the dialogue's speakerId. Clear it with
   * clearActiveDialogue(continuation.characterId, ...) before starting.
   */
  characterId: string;
  dialogue: Dialogue;
  /** true if explicitly queued via set_active_dialogue; false if discovered. */
  queued: boolean;
};

/**
 * A pending cutscene always takes priority over dialogue offers: the host
 * plays `cutscene.asset`, applies `effectsOnComplete`, clears
 * `pendingCutscene` (clearPendingCutscene), then enters `entersDialogue`
 * if the manifest chains into one.
 */
export type CutsceneContinuation = {
  kind: "cutscene";
  cutscene: Cutscene;
};

export type Continuation = DialogueContinuation | CutsceneContinuation;

/**
 * Decide which dialogues to offer when the current scene ends (feed model).
 *
 * Priority: if ANY character has been forced via `set_active_dialogue` (its
 * `active_dialogue__{id}` flag is set), ONLY the offer-resolved dialogues for
 * those characters are offered (`queued: true`) — explicit narrative routing
 * wins. Otherwise DISCOVERY runs across every character (`queued: false`):
 * each resolves its most salient eligible offer via `resolveCharacterDialogue`.
 *
 * The current dialogue is always excluded. Results are de-duplicated by
 * dialogue id (first occurrence wins).
 */
export function nextContinuations(
  state: GameState,
  project: ProjectData,
  visitedDialogueIds: ReadonlySet<string>,
  currentDialogueId: string,
): Continuation[] {
  const seen = new Set<string>([currentDialogueId]);

  // A pending cutscene always comes first — it's the very next thing the
  // host must play before any dialogue offer.
  const pending: Continuation[] = [];
  if (state.pendingCutscene) {
    const cutscene = ownValue(project.cutscenes, state.pendingCutscene);
    if (cutscene) pending.push({ kind: "cutscene", cutscene });
  }

  // Forced routing: characters with an active_dialogue flag set. Resolution
  // is the same ranking as always (the forced offer is expected to sit at a
  // higher tier), ignoring the visited filter — re-entry is intended. But the
  // winner counts as FORCED only if its gate actually reads the flag: if the
  // routed character's best offer is an ordinary one (the forced offer's gate
  // has an extra conjunct that fails, or the target carries no forced offer
  // at all — the validator warns about both), that is not routing. It must
  // not be presented as queued, must not consume the flag, and must not
  // bypass the visited filter; the character falls through to discovery and
  // the flag stays set until the forced offer can win.
  const offerIndex = indexOffersByCharacter(project);
  const forced: Continuation[] = [];
  for (const char of Object.values(project.characters)) {
    const flag = activeDialogueFlag(char.id);
    if (ownValue(state.flags, flag) !== true) continue;
    const resolvedId = resolveCharacterDialogue(state, char, project, undefined, offerIndex);
    if (!resolvedId) continue;
    const dialogue = project.dialogues[resolvedId];
    if (!dialogue || !conditionReadsFlag(dialogue.offer?.when, flag)) continue;
    if (!seen.has(dialogue.id)) {
      seen.add(dialogue.id);
      forced.push({ kind: "dialogue", characterId: char.id, dialogue, queued: true });
    }
  }
  if (forced.length > 0) return [...pending, ...forced];

  // Discovery — each character offers its most salient eligible dialogue
  // (resolveCharacterDialogue applies the visited/replayable filter before the
  // pick, so a visited one-shot yields the next-best rather than nothing).
  const discovered: Continuation[] = [];
  for (const char of Object.values(project.characters)) {
    const resolvedId = resolveCharacterDialogue(state, char, project, visitedDialogueIds, offerIndex);
    if (!resolvedId) continue;
    const dialogue = project.dialogues[resolvedId];
    if (dialogue && !seen.has(dialogue.id)) {
      seen.add(dialogue.id);
      discovered.push({ kind: "dialogue", characterId: char.id, dialogue, queued: false });
    }
  }
  return [...pending, ...discovered];
}

// ---------------------------------------------------------------------------
// Codex — player-facing knowledge entries
// ---------------------------------------------------------------------------

/**
 * The codex entries currently readable, in id order.
 *
 * Unlocking is definitionally `evaluate(unlockedBy)` — there is no separate
 * unlocked-set in GameState to keep in sync, so an entry re-locks if the
 * condition it reads stops holding. An entry with no `unlockedBy` is always
 * unlocked (unlike an Ending, whose condition is required).
 */
export function unlockedCodexEntries(project: ProjectData, state: GameState): Codex[] {
  return Object.values(project.codex ?? {})
    .filter((entry) => !entry.unlockedBy || evaluate(entry.unlockedBy, state, project))
    // Ordinal (UTF-16 code-unit) compare, like betterOffer — NOT localeCompare,
    // whose order depends on the host's ICU data, so a port reading this
    // contract could disagree with the editor on which entry comes first (E9).
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}
