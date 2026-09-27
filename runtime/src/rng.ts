/**
 * Deterministic seeded RNG — mulberry32.
 *
 * The exact stream is part of the runtime contract: `tooling/conformance/rng.json`
 * pins its outputs for several seeds, so a port that reproduces it replays a
 * recorded route (and every check roll in it) identically. Pass the returned
 * function as the `rng` argument of `resolveCheck` / `chooseChoice`.
 */
export function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s += 0x6d2b79f5;
    let z = s;
    z = Math.imul(z ^ (z >>> 15), z | 1);
    z ^= z + Math.imul(z ^ (z >>> 7), z | 61);
    return ((z ^ (z >>> 14)) >>> 0) / 4294967296;
  };
}
