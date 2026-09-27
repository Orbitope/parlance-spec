# @orbitope/parlance-runtime

The [Parlance](https://github.com/Orbitope/parlance-releases) narrative runtime for
JavaScript and TypeScript: load a Parlance project and play it — conditions, effects,
dialogue stepping, skill checks, dialogue offers, quests, progression and saves —
with exactly the semantics the Parlance editor plays it with.

It is the same code the editor's Play panel and share builds run, extracted and
published under the MIT license so it can ship inside any game, commercial ones
included. Zero dependencies; pure functions (no filesystem, no DOM, no clock); runs
in browsers, Node, Deno, Bun and embedded JS engines.

## Install

```bash
npm install @orbitope/parlance-runtime
```

## Example: step through a dialogue

```ts
import { readFileSync, readdirSync } from "node:fs";
import { loadProjectFromFileMap, createDefaultState, stepDialogue, chooseChoice, advanceNode, applyEffects, resolveQuests } from "@orbitope/parlance-runtime";

// Every .json under data/, keyed by its data-relative POSIX path. (Use fetch, an asset bundle, … elsewhere.)
const paths = readdirSync("data", { recursive: true, encoding: "utf-8" }).filter((p) => p.endsWith(".json"));
const project = loadProjectFromFileMap(new Map(paths.map((p) => [p.replaceAll("\\", "/"), readFileSync(`data/${p}`, "utf-8")])));

const dlg = project.dialogues["dlg_gatekeeper_intro"]!;
let state = createDefaultState(project);
let nodeId: string | null = dlg.entry;
while (nodeId) {
  const step = stepDialogue(dlg, nodeId, state, project);   // resolves (and may skip) gated nodes
  state = resolveQuests(applyEffects(step.onEnterEffects, state, project), project).state;
  if (step.node.text) console.log(step.node.text);
  const choice = step.visibleChoices[0];                     // your UI lets the player pick
  const out = choice ? chooseChoice(dlg, step.node.id, choice.id, state, project)
    : step.node.next ? advanceNode(dlg, step.node.id, state, project) : null;
  state = out?.newState ?? state;
  nodeId = out?.nextNodeId ?? null;
}
```

The integration guide has the full loop: locked choices, cutscenes, offers (which
dialogue a character says next) and saves (`serializeState` / `deserializeState`).

## Documentation

- **[Runtime contract](https://github.com/orbitope/parlance-spec/blob/main/docs/RUNTIME_CONTRACT.md)**
  — the authoritative semantics every function here implements.
- **[Integration guide](https://github.com/orbitope/parlance-spec/blob/main/docs/INTEGRATION.md)**
  — loading, the API, hooks, saves.
- **[Conformance vectors](https://github.com/orbitope/parlance-spec/tree/main/conformance)**
  — this package passes all of them; so do the Unity, Godot and Unreal runtimes.

The package version tracks the Parlance format version it plays (see VERSIONING in the
spec repository).

## License

MIT — see [LICENSE](LICENSE).
