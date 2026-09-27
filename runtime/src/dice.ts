/**
 * Dice notation and probability. Decouples skill checks from a hardcoded d20.
 *
 * Notation: "NdM" — N dice of M sides, summed. N >= 1, M >= 2.
 * The skill value is the modifier (not part of the notation).
 *
 * Roll model (must match every language port — see RUNTIME_CONTRACT.md):
 *   roll  = sum over N of (floor(rng() * M) + 1), consuming N rng() calls in order
 *   total = roll + skillValue
 *   pass  = total >= difficulty
 */

export type DiceSpec = { n: number; m: number };

/** Canonical default when no rules.json / per-check override is present. */
export const DEFAULT_DICE: DiceSpec = { n: 1, m: 20 };

const DICE_RE = /^(\d+)d(\d+)$/;

/**
 * Upper bounds on the notation (mirrored in tooling/validate.py — keep in
 * lockstep). `dicePMF` allocates and convolves n·m cells, so the grammar's
 * `\d+d\d+` alone let `200d1000` stall the inspector for half a minute and
 * `1d99999999999999999999` throw a RangeError out of it (adversarial review
 * D8). Nothing a tabletop system uses comes near either limit.
 */
export const MAX_DICE_COUNT = 100;
export const MAX_DIE_SIDES = 1000;

/** Parse "NdM" → {n, m}. Throws on malformed input or out-of-range values. */
export function parseDice(notation: string): DiceSpec {
  const match = DICE_RE.exec(notation.trim());
  if (!match) throw new Error(`Invalid dice notation '${notation}': expected NdM (e.g. 1d20, 2d6)`);
  const n = Number(match[1]);
  const m = Number(match[2]);
  if (n < 1) throw new Error(`Invalid dice notation '${notation}': need at least 1 die`);
  if (m < 2) throw new Error(`Invalid dice notation '${notation}': die must have at least 2 sides`);
  if (n > MAX_DICE_COUNT) throw new Error(`Invalid dice notation '${notation}': at most ${MAX_DICE_COUNT} dice`);
  if (m > MAX_DIE_SIDES) throw new Error(`Invalid dice notation '${notation}': a die has at most ${MAX_DIE_SIDES} sides`);
  return { n, m };
}

/** Format a DiceSpec back to "NdM". */
export function formatDice(spec: DiceSpec): string {
  return `${spec.n}d${spec.m}`;
}

/** Inclusive min/max of the raw roll (before the skill modifier). */
export function diceRange(spec: DiceSpec): { min: number; max: number } {
  return { min: spec.n, max: spec.n * spec.m };
}

/**
 * Roll each die, returning the individual faces in order. Consumes exactly
 * `n` rng() calls, left to right — the ordering is contract (RUNTIME_CONTRACT).
 *
 * The faces matter, not just the sum: a critical is "every die shows its
 * extreme", which a total cannot tell you (7 on 2d6 is 1+6 or 3+4).
 */
export function rollDiceFaces(spec: DiceSpec, rng: () => number): number[] {
  const faces: number[] = [];
  for (let i = 0; i < spec.n; i++) {
    faces.push(Math.floor(rng() * spec.m) + 1);
  }
  return faces;
}

/** Roll the dice, consuming exactly `n` rng() calls in order. */
export function rollDice(spec: DiceSpec, rng: () => number): number {
  return rollDiceFaces(spec, rng).reduce((sum, face) => sum + face, 0);
}

/**
 * Probability mass function of the sum of N dice of M sides.
 * Returns pmf[s] = P(roll === s) for s in [n, n*m]; index by (sum - n).
 *
 * Computed by convolution with one uniform die at a time. Each die is a
 * window sum — P(sum = s) after adding a die is the mean of the previous
 * distribution over the M sums it can come from — so a prefix-sum table makes
 * every die O(length) rather than O(length · M). The direct form was
 * O(n²·m²) and took ~8 s at the notation's bounds (`100d1000`), which is what
 * the bounds were meant to rule out (D8); this is ~10⁷ operations there.
 */
export function dicePMF(spec: DiceSpec): number[] {
  const m = spec.m;
  // Distribution of a single die: uniform 1..m
  let dist = new Array<number>(m).fill(1 / m); // index 0 => face 1
  for (let d = 1; d < spec.n; d++) {
    // prefix[i] = Σ dist[0..i-1]; the window sum over dist[i-m+1..i] is a difference.
    const prefix = new Array<number>(dist.length + 1).fill(0);
    for (let i = 0; i < dist.length; i++) prefix[i + 1] = prefix[i]! + dist[i]!;
    const len = dist.length + m - 1;
    const next = new Array<number>(len);
    for (let i = 0; i < len; i++) {
      const hi = Math.min(i, dist.length - 1); // last previous index feeding sum i
      const lo = Math.max(0, i - m + 1);        // first
      next[i] = (prefix[hi + 1]! - prefix[lo]!) / m;
    }
    dist = next;
  }
  return dist; // dist[k] => P(sum === n + k)
}

/**
 * Exact success probability of `roll + skill >= difficulty`.
 *
 * With `criticals` OFF: guaranteed (1.0) when even the minimum roll clears;
 * impossible (0.0) when even the maximum roll fails.
 *
 * With `criticals` ON the extremes become unreachable, and this MUST agree with
 * resolveCheck or a displayed number lies to the player: every die on its
 * minimum always fails and every die on its maximum always succeeds, whatever
 * the skill. Since the minimum sum is reachable ONLY by all-minimum faces (and
 * likewise the maximum), the face rule can be applied in sum space: drop the
 * minimum sum from the passing set, and add the maximum sum unconditionally. So
 * the result is clamped to [P(max), 1 - P(min)] — on 2d6 that is 2.8% to 97.2%,
 * and no check is ever a certainty or a lost cause.
 */
export function diceSuccessProbability(
  spec: DiceSpec,
  skill: number,
  difficulty: number,
  criticals = false,
): number {
  const { min, max } = diceRange(spec);
  if (!criticals) {
    if (min + skill >= difficulty) return 1;
    if (max + skill < difficulty) return 0;
  }
  const pmf = dicePMF(spec);
  let p = 0;
  for (let k = 0; k < pmf.length; k++) {
    const rollValue = spec.n + k;
    if (criticals) {
      if (rollValue === min) continue;   // snake eyes: always fails
      if (rollValue === max) { p += pmf[k]!; continue; } // boxcars: always succeeds
    }
    if (rollValue + skill >= difficulty) p += pmf[k]!;
  }
  return p;
}
