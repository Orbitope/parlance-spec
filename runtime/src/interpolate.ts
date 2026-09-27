/**
 * Text interpolation — `{var_id}` placeholders in player-facing strings.
 *
 * This is a STRING SUBSTITUTION LAYER, not an expression language. There are
 * deliberately no conditionals, no formatting, no nesting, and no arithmetic.
 * If you find yourself wanting those, the answer is authored branching, not a
 * richer placeholder syntax.
 *
 * Substitution happens at RENDER time, never at save time — authored JSON
 * always contains the placeholder, and a value is never baked into content.
 *
 * See tooling/RUNTIME_CONTRACT.md § Text interpolation.
 */

import type { GameState } from "./runtime.js";
import { ownValue } from "./own.js";

/**
 * A placeholder: a single brace pair around a bare entity id, no spaces, no
 * filters, no modifiers. The id pattern is the format's id pattern
 * (`definitions/id` in schema/common.schema.json), so
 * `{not an id}` and `{}` are left alone as ordinary text.
 *
 * There is no escaping mechanism in v1: a literal `{` followed by a valid id
 * pattern and `}` IS a placeholder, and there is no way to write one literally.
 * Documented as a limitation rather than solved.
 */
export const PLACEHOLDER_PATTERN = /\{([a-z][a-z0-9_]*)\}/g;

/** Ids already warned about, so a missing value logs once, not once per frame. */
const warnedIds = new Set<string>();

/** Test seam: forget which ids have been warned about. */
export function resetInterpolationWarnings(): void {
  warnedIds.clear();
}

/** Every distinct placeholder id appearing in `text`, in first-seen order. */
export function placeholdersIn(text: string): string[] {
  const ids: string[] = [];
  for (const m of text.matchAll(PLACEHOLDER_PATTERN)) {
    const id = m[1]!;
    if (!ids.includes(id)) ids.push(id);
  }
  return ids;
}

/**
 * Replace every `{var_id}` in `text` with `state.texts[var_id]`.
 *
 * Missing key → the placeholder is left **as written**, so the failure is
 * visible in-game rather than silently rendering an empty string, and a warning
 * is logged once per unique id. Never throws: a missing value must not take a
 * dialogue down.
 *
 * (`createDefaultState` seeds `state.texts` from each text variable's `default`,
 * so "fall back to the default" is already accounted for by the time a state
 * exists — a key is absent here only when the variable has no default and no
 * `set_text` has run.)
 */
export function interpolate(text: string, state: GameState): string {
  // Fast path: most authored lines contain no placeholder at all.
  if (!text.includes("{")) return text;

  return text.replace(PLACEHOLDER_PATTERN, (match, id: string) => {
    // Own key only: `{constructor}` used to render Object's constructor
    // function as dialogue text (E3).
    const value = ownValue(state.texts, id);
    if (value === undefined) {
      if (!warnedIds.has(id)) {
        warnedIds.add(id);
        console.warn(
          `[parlance] text placeholder '{${id}}' has no value and no default — rendering it literally`,
        );
      }
      return match;
    }
    return value;
  });
}
