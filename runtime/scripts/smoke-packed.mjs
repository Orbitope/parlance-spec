#!/usr/bin/env node
/**
 * Smoke-test the PACKED runtime tarball the way a game installs it — the
 * failure a workspace run cannot see (a `files` mistake, an `exports` map that
 * still points at src/, a .d.ts that does not resolve).
 *
 *   node scripts/smoke-packed.mjs <tarball.tgz> <project-root> [--tsc <path to tsc>]
 *
 * 1. The tarball holds dist/, LICENSE and README.md — and no src/, test/ or
 *    scripts/ (only the playback bundle ships; the source is on parlance-spec).
 * 2. Installed into an empty directory, `import "@orbitope/parlance-runtime"`
 *    loads a real project and plays its dialogues to the end.
 * 3. With --tsc, a TypeScript consumer type-checks against the shipped .d.ts.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const [tgzArg, projectArg, flag, tscArg] = process.argv.slice(2);
if (!tgzArg || !projectArg) {
  console.error("usage: smoke-packed.mjs <tarball.tgz> <project-root> [--tsc <tsc>]");
  process.exit(2);
}
const tgz = resolve(tgzArg);
const dataDir = join(resolve(projectArg), "data");
const fail = (msg) => {
  console.error(`smoke-packed: ${msg}`);
  process.exit(1);
};

// 1. Contents.
const listed = execFileSync("tar", ["-tzf", tgz], { encoding: "utf-8" }).split("\n").filter(Boolean);
for (const required of ["package/package.json", "package/LICENSE", "package/README.md", "package/dist/index.js", "package/dist/index.d.ts"]) {
  if (!listed.includes(required)) fail(`${required} is missing from the tarball`);
}
const stray = listed.filter((f) => !/^package\/(package\.json|LICENSE|README\.md|dist\/.*)$/.test(f));
if (stray.length) fail(`unexpected files in the tarball (only dist/, LICENSE, README.md ship):\n  ${stray.join("\n  ")}`);
console.log(`smoke-packed: tarball holds ${listed.length} files, all under dist/ or top-level docs`);

// 2. Install and play.
const dir = mkdtempSync(join(tmpdir(), "parlance-runtime-smoke-"));
execFileSync("npm", ["init", "-y"], { cwd: dir, stdio: "ignore" });
execFileSync("npm", ["install", "--no-audit", "--no-fund", tgz], { cwd: dir, stdio: "ignore" });
writeFileSync(
  join(dir, "play.mjs"),
  `import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { loadProjectFromFileMap, createDefaultState, stepDialogue, chooseChoice, advanceNode, applyEffects, resolveQuests, serializeState, deserializeState, mulberry32 } from "@orbitope/parlance-runtime";

const dataDir = ${JSON.stringify(dataDir)};
const paths = readdirSync(dataDir, { recursive: true, encoding: "utf-8" }).filter((p) => p.endsWith(".json"));
const project = loadProjectFromFileMap(new Map(paths.map((p) => [p.replaceAll("\\\\", "/"), readFileSync(join(dataDir, p), "utf-8")])));
const dialogues = Object.values(project.dialogues);
if (dialogues.length === 0) throw new Error("no dialogues loaded");
const rng = mulberry32(7);
let lines = 0;
for (const dlg of dialogues) {
  let state = createDefaultState(project);
  let nodeId = dlg.entry;
  for (let hop = 0; nodeId && hop < 200; hop++) {
    const step = stepDialogue(dlg, nodeId, state, project);
    state = resolveQuests(applyEffects(step.onEnterEffects, state, project), project).state;
    if (step.node.text) lines++;
    const choice = step.visibleChoices[0];
    const out = choice ? chooseChoice(dlg, step.node.id, choice.id, state, project, rng)
      : step.node.next ? advanceNode(dlg, step.node.id, state, project) : null;
    state = out ? out.newState : state;
    nodeId = out ? out.nextNodeId : null;
  }
  const round = serializeState(deserializeState(serializeState(state)));
  if (JSON.stringify(round) !== JSON.stringify(serializeState(state))) throw new Error("save round-trip drifted");
}
console.log("smoke-packed: played " + dialogues.length + " dialogues, " + lines + " lines");
`,
);
execFileSync("node", ["play.mjs"], { cwd: dir, stdio: "inherit" });

// 3. Types.
if (flag === "--tsc" && tscArg) {
  writeFileSync(
    join(dir, "consumer.ts"),
    `import { createDefaultState, stepDialogue, type ProjectData, type GameState, type StepResult } from "@orbitope/parlance-runtime";
export function first(project: ProjectData): StepResult | null {
  const dlg = Object.values(project.dialogues)[0];
  if (!dlg) return null;
  const state: GameState = createDefaultState(project);
  return stepDialogue(dlg, dlg.entry, state, project);
}
`,
  );
  writeFileSync(
    join(dir, "tsconfig.json"),
    JSON.stringify({ compilerOptions: { strict: true, noEmit: true, module: "NodeNext", moduleResolution: "NodeNext", target: "ES2022", skipLibCheck: false, types: [] }, files: ["consumer.ts"] }),
  );
  const consumerPkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
  writeFileSync(join(dir, "package.json"), JSON.stringify({ ...consumerPkg, type: "module" }));
  execFileSync(resolve(tscArg), ["-p", "."], { cwd: dir, stdio: "inherit" });
  console.log("smoke-packed: a strict NodeNext TypeScript consumer type-checks against dist/index.d.ts");
}
