/**
 * Own-key access on the plain-object maps the runtime reads and builds.
 *
 * Project registries and the state maps are JSON-shaped records whose keys are
 * ids, and an id may legally spell a prototype key (`constructor`,
 * `toString`). Reading or writing those through ordinary `rec[key]` reaches
 * the prototype, so every lookup of an author- or save-supplied key goes
 * through these helpers.
 */

/**
 * Own-key READ on a plain-object map: `rec[key]` reads through the prototype,
 * so `state.flags["constructor"]` is a function (never `=== true`, but never
 * the absent-key default either), `state.questStages["toString"]` is a
 * function where a stage id is expected, and `state.texts["constructor"]`
 * rendered `function Object() { [native code] }` into a line of dialogue
 * (adversarial review E3). The runtime's maps are JSON-shaped records whose
 * keys are ids, so an inherited key is by definition absent.
 */
export function ownValue<T>(rec: Readonly<Record<string, T>> | undefined | null, key: string): T | undefined {
  return rec != null && Object.hasOwn(rec, key) ? rec[key] : undefined;
}

/** Store `value` under `key` as an own data property, whatever the key is. */
export function setOwn<T>(obj: Record<string, T>, key: string, value: T): void {
  Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
}
