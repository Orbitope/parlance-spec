/**
 * The executable half of the runtime contract: every vector file in
 * tooling/conformance/ (except the validator and ladder-migration suites, which
 * test the editor, not playback), run against whichever implementation of the
 * runtime API is handed in.
 *
 * One runner, two callers, so the two can never test different things:
 * `runtime/test/conformance.test.ts` runs it against this package's own source,
 * and `core/test/conformance.test.ts` against what `@parlance/core` re-exports.
 * Workspace-only — reachable as `@orbitope/parlance-runtime/test/conformance`
 * inside the monorepo, and never published.
 */
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync, readdirSync } from "fs";
import { join, dirname, resolve } from "path";
import { fileURLToPath } from "url";
import type {
  Condition,
  Effect,
  Check,
  Character,
  Progression,
  Dialogue,
  ProjectData,
  SerializedGameState,
} from "../src/index.js";
import type * as Runtime from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
/**
 * The vectors: `tooling/conformance/` in the Parlance monorepo, `conformance/`
 * beside `runtime/` in the published spec repository.
 */
const CONFORMANCE = [resolve(HERE, "../../../tooling/conformance"), resolve(HERE, "../../conformance")]
  .find((d) => existsSync(join(d, "evaluate.json"))) ?? resolve(HERE, "../../../tooling/conformance");

/** The slice of the runtime API the vectors exercise. */
export type ConformanceApi = Pick<
  typeof Runtime,
  | "nextContinuations"
  | "evaluate"
  | "applyEffect"
  | "resolveCheck"
  | "stepDialogue"
  | "chooseChoice"
  | "advanceNode"
  | "resolveCharacterDialogue"
  | "resolveQuests"
  | "levelForXp"
  | "pointsEarned"
  | "availablePoints"
  | "investSkillPoint"
  | "recomputeSkills"
  | "serializeState"
  | "deserializeState"
  | "parseDice"
  | "mulberry32"
>;

export function runConformanceSuite(api: ConformanceApi): void {
  const {
    nextContinuations,
    evaluate,
    applyEffect,
    resolveCheck,
    stepDialogue,
    chooseChoice,
    advanceNode,
    resolveCharacterDialogue,
    resolveQuests,
    levelForXp,
    pointsEarned,
    availablePoints,
    investSkillPoint,
    recomputeSkills,
    serializeState,
    deserializeState,
    parseDice,
    mulberry32,
  } = api;


  const loaded = new Set<string>();
  function loadVectors(file: string): unknown[] {
    loaded.add(file);
    return JSON.parse(readFileSync(join(CONFORMANCE, file), "utf-8")) as unknown[];
  }

  // ---------------------------------------------------------------------------
  // Minimal project shape used in applyEffect / chooseChoice vectors.
  // Only factions are needed for reputation clamping; cast to ProjectData.
  // ---------------------------------------------------------------------------
  type MinimalProject = {
    factions?: Record<string, { id: string; name: string; summary: string; reputationRange: { min: number; max: number } }>;
    // Quest conditions compare stage ORDER, so those vectors carry the quests
    // they reference. Absent for every pre-existing vector.
    quests?: Record<string, unknown>;
    // Offer resolution reads project.dialogues (their `offer`/`speakerId`/`replayable`).
    dialogues?: Record<string, unknown>;
  };

  function asProject(p: MinimalProject | undefined): ProjectData {
    return (p ?? {}) as unknown as ProjectData;
  }

  // ---------------------------------------------------------------------------
  // evaluate
  // ---------------------------------------------------------------------------

  type EvaluateVector = {
    fn: "evaluate";
    description: string;
    state: SerializedGameState;
    condition: Condition;
    /** Only present for conditions that need project data (e.g. quest). */
    project?: MinimalProject;
    expected: boolean;
  };

  describe("conformance: evaluate", () => {
    const vectors = loadVectors("evaluate.json") as EvaluateVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        expect(evaluate(v.condition, state, asProject(v.project))).toBe(v.expected);
      });
    }
  });

  // ---------------------------------------------------------------------------
  // applyEffect
  // ---------------------------------------------------------------------------

  type ApplyEffectVector = {
    fn: "applyEffect";
    description: string;
    state: SerializedGameState;
    effect: Effect;
    project: MinimalProject;
    expected: SerializedGameState;
  };

  describe("conformance: applyEffect", () => {
    const vectors = loadVectors("apply_effect.json") as ApplyEffectVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        const result = applyEffect(v.effect, state, asProject(v.project));
        expect(serializeState(result)).toEqual(v.expected);
      });
    }
  });

  // ---------------------------------------------------------------------------
  // resolveCheck
  // ---------------------------------------------------------------------------

  type ResolveCheckVector = {
    fn: "resolveCheck";
    description: string;
    state: SerializedGameState;
    check: Check;
    /** Single value (constant rng) or a sequence consumed one per die, in order. */
    rng: number | number[];
    /** Project default dice (rules.check.dice). Absent ⇒ engine default 1d20. */
    defaultDice?: string;
    /** rules.check.criticals. Absent ⇒ off. */
    criticals?: boolean;
    /** Needed only when the check declares modifiers whose `when` reads quest state. */
    project?: MinimalProject;
    expected: {
      passed: boolean; roll: number; total: number; skillValue: number; dice: string;
      critical?: "success" | "failure";
      bonus?: number; appliedModifiers?: number[];
    };
  };

  describe("conformance: resolveCheck", () => {
    const vectors = loadVectors("resolve_check.json") as ResolveCheckVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        // Array rng feeds one value per die call, in order; number is constant.
        let i = 0;
        const seq = Array.isArray(v.rng) ? v.rng : null;
        const rng = seq ? () => seq[i++ % seq.length]! : () => v.rng as number;
        const defaultDice = v.defaultDice ? parseDice(v.defaultDice) : undefined;
        // A check with modifiers requires a project (as the real caller always
        // passes one); use the vector's project when it needs quest state, else {}.
        const hasModifiers = !!v.check.modifiers && v.check.modifiers.length > 0;
        const project = v.project ? asProject(v.project) : hasModifiers ? asProject({}) : undefined;
        expect(resolveCheck(v.check, state, rng, defaultDice, v.criticals ?? false, project)).toEqual(v.expected);
      });
    }
  });

  // ---------------------------------------------------------------------------
  // stepDialogue
  // ---------------------------------------------------------------------------

  type StepDialogueVector = {
    fn: "stepDialogue";
    description: string;
    dialogue: Dialogue;
    nodeId: string;
    state: SerializedGameState;
    project?: MinimalProject;
    expected: {
      /**
       * The RESOLVED node's id. Load-bearing for conditional narration: without
       * it, a port that never implements the skip walk still passes every vector
       * whose skipped node carries no onEnter — which is the typical gated line,
       * since a conditional node is choiceless by construction.
       *
       * REQUIRED, not optional. It was optional when it was introduced, which
       * quietly reopened the same hole one level up: a vector that omitted it
       * skipped the assertion and read as passing. Every vector states its
       * resolved node, including the eight where it is the node asked for.
       */
      nodeId: string;
      visibleChoiceIds: string[];
      /**
       * Choices whose showIf failed and whose whenLocked resolves to "show"
       * (0.15). REQUIRED on every vector, for the same reason `nodeId` is: an
       * optional field is an assertion a port can pass by never implementing it.
       * Every pre-0.15 vector states `[]`.
       */
      lockedChoiceIds: string[];
      /**
       * The line-only gate (0.15): true when the node's showIf failed on a node
       * with choices or isEnd. Optional in the file — absent means false, and
       * the harness asserts false, so a port that skips such a node fails.
       */
      textHidden?: boolean;
      /** The returned node's text; `null` pins a text-less node's ABSENT text. Optional. */
      text?: string | null;
      onEnterEffectCount: number;
      /** The node's onEnter effects, in order — the contract the count only hinted at. */
      onEnterEffects: unknown[];
      /** The resolved node's tags, exactly as authored (pass-through). */
      nodeTags?: string[];
      /** Per visible choice, its tags (null where the choice has none), in visibleChoiceIds order. */
      visibleChoiceTags?: (string[] | null)[];
    };
  };

  describe("conformance: stepDialogue", () => {
    const vectors = loadVectors("step_dialogue.json") as StepDialogueVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        const result = stepDialogue(v.dialogue, v.nodeId, state, asProject(v.project));
        // Asserted unconditionally: a vector missing this field is a defect in the
        // vector file, and must fail here rather than silently skip the check.
        expect(v.expected.nodeId).toBeDefined();
        expect(result.node.id).toBe(v.expected.nodeId);
        expect(result.visibleChoices.map((c) => c.id)).toEqual(v.expected.visibleChoiceIds);
        expect(v.expected.lockedChoiceIds).toBeDefined();
        expect(result.lockedChoices.map((c) => c.id)).toEqual(v.expected.lockedChoiceIds);
        expect(result.textHidden).toBe(v.expected.textHidden ?? false);
        if (v.expected.text !== undefined) {
          expect(result.node.text).toBe(v.expected.text === null ? undefined : v.expected.text);
        }
        // Count AND content. Counting alone let a port return the choice's
        // effects instead of the node's, or return them reversed, or return two
        // nulls, and still be declared conformant — while applying the wrong
        // effects to the player's state.
        expect(result.onEnterEffects.length).toBe(v.expected.onEnterEffectCount);
        expect(result.onEnterEffects).toEqual(v.expected.onEnterEffects);
        // Tags are opaque pass-through: a port that strips them (or invents
        // them) fails here. Asserted only where the vector states them.
        if (v.expected.nodeTags !== undefined) expect(result.node.tags).toEqual(v.expected.nodeTags);
        if (v.expected.visibleChoiceTags !== undefined) {
          expect(result.visibleChoices.map((c) => c.tags ?? null)).toEqual(v.expected.visibleChoiceTags);
        }
      });
    }
  });

  // ---------------------------------------------------------------------------
  // chooseChoice
  // ---------------------------------------------------------------------------

  type ChooseChoiceVector = {
    fn: "chooseChoice";
    description: string;
    dialogue: Dialogue;
    nodeId: string;
    choiceId: string;
    state: SerializedGameState;
    project: MinimalProject;
    rng?: number;
    expected?: {
      nextNodeId: string | null;
      newState: SerializedGameState;
      checkResult?: { passed: boolean; roll: number; total: number; skillValue: number };
    };
    /**
     * Present instead of `expected` when the call must THROW (0.15): a choice
     * that is hidden, locked, or an unoffered fallback is not selectable. Same
     * convention as advance.json — substring of the error message.
     */
    expectedError?: string;
  };

  describe("conformance: chooseChoice", () => {
    const vectors = loadVectors("choose_choice.json") as ChooseChoiceVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        const rng = v.rng !== undefined ? () => v.rng! : Math.random;
        if (v.expectedError !== undefined) {
          expect(() => chooseChoice(v.dialogue, v.nodeId, v.choiceId, state, asProject(v.project), rng)).toThrow(v.expectedError);
          return;
        }
        const result = chooseChoice(v.dialogue, v.nodeId, v.choiceId, state, asProject(v.project), rng);

        expect(v.expected).toBeDefined();
        expect(result.nextNodeId).toBe(v.expected!.nextNodeId);
        expect(serializeState(result.newState)).toEqual(v.expected!.newState);

        if (v.expected!.checkResult !== undefined) {
          expect(result.checkResult).toEqual(v.expected!.checkResult);
        } else {
          expect(result.checkResult).toBeUndefined();
        }
      });
    }
  });

  // ---------------------------------------------------------------------------
  // advanceNode (N2 — DialogueNode.next, the choiceless counterpart of
  // chooseChoice)
  //
  // The FIRST conformance vector file to need a failure case: every other
  // vector set is expected + deep-equal only. advanceNode's own contract is
  // throw-on-misuse (no `Problem`/result-object encoding), so the vectors need
  // an explicit `expectedError` field and the runner needs a branch for it —
  // this is new suite-wide convention, not just new vectors.
  // ---------------------------------------------------------------------------

  type AdvanceVector = {
    fn: "advanceNode";
    description: string;
    dialogue: Dialogue;
    nodeId: string;
    state: SerializedGameState;
    expected?: { nextNodeId: string; newState: SerializedGameState };
    /** Only present for vectors whose skip walk needs project data. */
    project?: MinimalProject;
    /** Substring the thrown Error's message must contain. Mutually exclusive with `expected`. */
    expectedError?: string;
  };

  describe("conformance: advanceNode", () => {
    const vectors = loadVectors("advance.json") as AdvanceVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        if (v.expectedError !== undefined) {
          expect(() => advanceNode(v.dialogue, v.nodeId, state, asProject(v.project))).toThrow(v.expectedError);
          return;
        }
        const result = advanceNode(v.dialogue, v.nodeId, state, asProject(v.project));
        expect(result.nextNodeId).toBe(v.expected!.nextNodeId);
        expect(serializeState(result.newState)).toEqual(v.expected!.newState);
      });
    }
  });

  // ---------------------------------------------------------------------------
  // resolveCharacterDialogue — dialogue offers (most-salient-wins)
  // ---------------------------------------------------------------------------

  type ResolveCharacterDialogueVector = {
    fn: "resolveCharacterDialogue";
    description: string;
    state: SerializedGameState;
    character: Character;
    project?: MinimalProject;
    /** Optional visited-dialogue set — non-replayable offers in it are dropped before selection. */
    visited?: string[];
    expected: string | null;
  };

  describe("conformance: resolveCharacterDialogue", () => {
    const vectors = loadVectors("resolveCharacterDialogue.json") as ResolveCharacterDialogueVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        const visited = v.visited ? new Set(v.visited) : undefined;
        expect(resolveCharacterDialogue(state, v.character, asProject(v.project), visited)).toBe(v.expected);
      });
    }
  });

  // ---------------------------------------------------------------------------
  // nextContinuations — forced routing vs discovery, the visited set, cutscenes
  // ---------------------------------------------------------------------------

  type NextContinuationsVector = {
    fn: "nextContinuations";
    description: string;
    state: SerializedGameState;
    visited: string[];
    currentDialogueId: string;
    project: MinimalProject & { characters: Record<string, Character>; cutscenes?: Record<string, unknown> };
    expected: Array<
      | { kind: "dialogue"; characterId: string; dialogue: string; queued: boolean }
      | { kind: "cutscene"; cutscene: string }
    >;
  };

  describe("conformance: nextContinuations", () => {
    const vectors = loadVectors("nextContinuations.json") as NextContinuationsVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        const out = nextContinuations(state, asProject(v.project), new Set(v.visited), v.currentDialogueId).map((c) =>
          c.kind === "cutscene"
            ? { kind: "cutscene" as const, cutscene: c.cutscene.id }
            : { kind: "dialogue" as const, characterId: c.characterId, dialogue: c.dialogue.id, queued: c.queued },
        );
        expect(out).toEqual(v.expected);
      });
    }
  });

  // ---------------------------------------------------------------------------
  // resolveQuests — quest stage/outcome effects fire when their conditions hold
  // ---------------------------------------------------------------------------

  type ResolveQuestsVector = {
    fn: "resolveQuests";
    description: string;
    state: SerializedGameState;
    project: MinimalProject & { quests: Record<string, unknown> };
    expected: {
      state: SerializedGameState;
      firings: { quest: string; kind: "stage" | "outcome"; id: string }[];
    };
  };

  describe("conformance: resolveQuests", () => {
    const vectors = loadVectors("resolve_quests.json") as ResolveQuestsVector[];
    for (const v of vectors) {
      it(v.description, () => {
        const state = deserializeState(v.state);
        const result = resolveQuests(state, v.project as unknown as ProjectData);
        expect(serializeState(result.state)).toEqual(v.expected.state);
        expect(result.firings.map((f) => ({ quest: f.quest, kind: f.kind, id: f.id }))).toEqual(v.expected.firings);
      });
    }
  });

  // ---------------------------------------------------------------------------
  // progression — levelForXp / pointsEarned / availablePoints / investSkillPoint
  // / recomputeSkills (dispatched on the vector's `fn` field)
  // ---------------------------------------------------------------------------

  type ProgressionVector =
    | { fn: "levelForXp" | "pointsEarned"; description: string; config: Progression; xp: number; expected: number }
    | { fn: "availablePoints"; description: string; config: Progression; state: SerializedGameState; expected: number }
    | { fn: "investSkillPoint"; description: string; config: Progression; state: SerializedGameState; skillId: string; expected: SerializedGameState }
    | { fn: "recomputeSkills"; description: string; config: Progression; state: SerializedGameState; expected: SerializedGameState };

  describe("conformance: progression", () => {
    const vectors = loadVectors("progression.json") as ProgressionVector[];
    for (const v of vectors) {
      it(`${v.fn}: ${v.description}`, () => {
        switch (v.fn) {
          case "levelForXp":
            expect(levelForXp(v.xp, v.config)).toBe(v.expected);
            break;
          case "pointsEarned":
            expect(pointsEarned(v.xp, v.config)).toBe(v.expected);
            break;
          case "availablePoints":
            expect(availablePoints(deserializeState(v.state), v.config)).toBe(v.expected);
            break;
          case "investSkillPoint":
            expect(serializeState(investSkillPoint(deserializeState(v.state), v.skillId, v.config))).toEqual(v.expected);
            break;
          case "recomputeSkills":
            expect(serializeState(recomputeSkills(deserializeState(v.state), v.config))).toEqual(v.expected);
            break;
        }
      });
    }
  });

  // ---------------------------------------------------------------------------
  // rng — the mulberry32 stream a port must reproduce to replay a seeded route
  // ---------------------------------------------------------------------------

  describe("conformance: rng", () => {
    const fixture = loadVectors("rng.json") as { seed: number; outputs: number[] }[];
    for (const { seed, outputs } of fixture) {
      it(`seed ${seed}: first ${outputs.length} outputs match`, () => {
        const rng = mulberry32(seed);
        for (const expected of outputs) expect(rng()).toBe(expected);
      });
    }
  });

  // A vector file nobody runs is a contract nobody checks: every top-level
  // vector file must have been loaded by a describe block above.
  describe("conformance: coverage", () => {
    it("runs every vector file in tooling/conformance/", () => {
      const onDisk = readdirSync(CONFORMANCE).filter((f) => f.endsWith(".json")).sort();
      expect([...loaded].sort()).toEqual(onDisk);
    });
  });
}
