/**
 * Speaker resolution — the single place `node.speakerId ?? dialogue.speakerId`
 * (and the portrait fallback built on top of it) is computed. Every consumer
 * must go through these functions rather than re-implementing the `??` — that
 * duplication is exactly how the portrait-resolution order and the narration
 * convention would drift out of sync with each other.
 *
 * "No speakerId" IS the narration signal, not a distinct value an author sets.
 * See tooling/RUNTIME_CONTRACT.md § Node speaker resolution (N1).
 */

import type { ProjectData, Dialogue, DialogueNode, Character, Skill, Id } from "./types.js";

export type ResolvedSpeaker =
  | { kind: "character"; id: Id; character: Character }
  | { kind: "skill"; id: Id; skill: Skill }
  | { kind: "narration" };

/**
 * `node.speakerId ?? dialogue.speakerId` — the one fallback, named.
 *
 * Takes `Pick<DialogueNode, "speakerId">` rather than a full `DialogueNode` so
 * callers that only have a partial node shape (e.g. `{ id, text?, speakerId? }`)
 * can use the real resolver instead of re-deriving the fallback by hand.
 */
export function effectiveSpeakerId(dialogue: Dialogue, node: Pick<DialogueNode, "speakerId">): Id | undefined {
  return node.speakerId ?? dialogue.speakerId;
}

/**
 * Resolve the effective speaker to a concrete entity. Checks characters
 * first, then skills — an id present in both maps is a validator error
 * (checkSpeakerRef), not something this function disambiguates; it simply
 * picks character in that (unreachable-in-valid-data) case.
 *
 * An id that resolves to neither returns `{ kind: "narration" }` rather than
 * throwing, mirroring the omitted-speakerId case: the validator is what
 * turns a dangling id into an error, not this resolver. Callers that need to
 * distinguish "no speaker was ever set" from "the id is dangling" should
 * check `effectiveSpeakerId` themselves.
 */
export function resolveSpeaker(project: ProjectData, dialogue: Dialogue, node: Pick<DialogueNode, "speakerId">): ResolvedSpeaker {
  const id = effectiveSpeakerId(dialogue, node);
  if (!id) return { kind: "narration" };

  const character = project.characters[id];
  if (character) return { kind: "character", id, character };

  const skill = project.skills[id];
  if (skill) return { kind: "skill", id, skill };

  return { kind: "narration" };
}

/**
 * Portrait to render for this node (D10): the node's own Tier-2 override,
 * else the effective speaker's portrait, else null. Only a character speaker
 * carries a portrait — a skill or narration speaker falls through to null,
 * which is a legal, expected result (the presentation layer decides whether
 * to hold the last character portrait or clear it; see RUNTIME_CONTRACT.md).
 */
export function resolvePortrait(project: ProjectData, dialogue: Dialogue, node: Pick<DialogueNode, "speakerId" | "portrait">): Id | null {
  if (node.portrait) return node.portrait;
  const speaker = resolveSpeaker(project, dialogue, node);
  if (speaker.kind === "character" && speaker.character.portrait) return speaker.character.portrait;
  return null;
}
