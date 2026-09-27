/**
 * @orbitope/parlance-runtime — the playback half of Parlance.
 *
 * Plays a Parlance narrative project: evaluates conditions, applies effects,
 * steps dialogues, resolves checks, offers and quests, and round-trips saves.
 * The authoritative semantics are tooling/RUNTIME_CONTRACT.md, and the
 * conformance vectors in tooling/conformance/ are run against this package.
 */
export * from "./types.js";
export * from "./runtime.js";
export * from "./dice.js";
export * from "./nodeGate.js";
export * from "./forcedOffer.js";
export * from "./interpolate.js";
export * from "./speaker.js";
export * from "./rng.js";
export * from "./own.js";
export * from "./loader.js";
