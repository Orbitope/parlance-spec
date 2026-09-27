import type { Condition } from "./types.js";

/**
 * Condition shape helpers the runtime reads to decide which dialogue offer is
 * the FORCED one (`set_active_dialogue` routing). Shared with the validator's
 * offer rules and the ladder migration, so no reader can disagree with the
 * runtime about what "an offer that reads this flag" means. Mirrors
 * `condition_reads_flag` in tooling/validate.py.
 */

/** Top-level conjuncts: an `all` flattened one level; anything else is itself. */
export function topConjuncts(c: Condition): Condition[] {
  // Tolerates a wrong-typed `of` (a hand-edited `of: null`): schema validation
  // names it; this runs over unvalidated data too and must not throw.
  if (c === null || typeof c !== "object") return [];
  return c.type === "all" ? (Array.isArray(c.of) ? c.of : []).flatMap(topConjuncts) : [c];
}

/**
 * Does this gate REQUIRE `flag` to be true — a top-level conjunct `flag f = true`?
 * The test for a forced offer: `set_active_dialogue` sets `active_dialogue__X`,
 * and only an offer that reads that flag at the top level is routing; an
 * ordinary offer of a routed character is not, however it ranks. Shared by
 * the runtime (which offer counts as the forced one), the validator (the
 * routing-only exemption and the forced-target rules) and the migration.
 * Mirrors `condition_reads_flag` in tooling/validate.py.
 */
export function conditionReadsFlag(c: Condition | undefined, flag: string): boolean {
  return c != null && typeof c === "object" && topConjuncts(c).some((t) => t.type === "flag" && t.flag === flag && t.value === true);
}
