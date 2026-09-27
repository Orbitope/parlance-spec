import type { DialogueNode } from "./types.js";

/**
 * Whether a failed `showIf` SKIPS this node — interstitial narration with no
 * choices and not isEnd, where resolution continues at `next` — or only hides
 * its LINE (a node with choices or isEnd is still reached: choices offered,
 * dialogue ended, onEnter fired). One definition, read by resolveNode,
 * stepResolvedNode, both validators' COND rules and the inspector.
 *
 * See tooling/RUNTIME_CONTRACT.md for the node-gate semantics.
 */
export function isSkippableNode(node: DialogueNode): boolean {
  return (node.choices?.length ?? 0) === 0 && !node.isEnd;
}
