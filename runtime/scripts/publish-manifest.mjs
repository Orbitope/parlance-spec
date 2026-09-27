#!/usr/bin/env node
/**
 * Swap package.json between its WORKSPACE shape and its PUBLISHED shape.
 *
 * In the monorepo, `exports` points at the TypeScript source, exactly like
 * @parlance/core: core, host, client, the share-build player and every test
 * import this package live, with no build step, and a mutation of src/ is seen
 * by every suite. The published tarball carries only dist/ (no src/), so it
 * needs `exports`/`main`/`types` pointing there instead — the shape held in
 * `publishConfig`. npm itself does not apply `publishConfig.exports` (pnpm
 * does; npm only honours config keys there), so this script does it:
 *
 *   prepack  → `apply`:   back up package.json, write the published shape
 *   postpack → `restore`: put the workspace shape back
 *
 * `npm publish` re-reads package.json AFTER packing to build the registry
 * metadata, so under `npm publish` the restore is skipped: the registry then
 * records the same manifest the tarball carries. (That leaves the checkout
 * rewritten, which only ever happens on a throwaway CI runner;
 * `node scripts/publish-manifest.mjs force-restore` puts it back.)
 */
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = join(root, "package.json");
const backup = join(root, ".package.workspace.json");

function apply() {
  if (existsSync(backup)) {
    console.log("publish-manifest: already applied");
    return;
  }
  const text = readFileSync(manifest, "utf-8");
  const pkg = JSON.parse(text);
  const pub = pkg.publishConfig ?? {};
  if (!pub.exports) throw new Error("publish-manifest: publishConfig.exports is missing");
  writeFileSync(backup, text);
  const { exports, main, types, ...config } = pub;
  pkg.exports = exports;
  if (main) pkg.main = main;
  if (types) pkg.types = types;
  pkg.publishConfig = config;
  writeFileSync(manifest, JSON.stringify(pkg, null, 2) + "\n");
  const leaked = JSON.stringify(pkg.exports).includes("./src/") || JSON.stringify(pkg.exports).includes("./test/");
  if (leaked) throw new Error("publish-manifest: published exports still reference src/ or test/");
  console.log("publish-manifest: package.json now points at dist/");
}

function restore() {
  if (process.env.npm_command === "publish") {
    console.log("publish-manifest: publishing — leaving the published manifest for the registry");
    return;
  }
  if (!existsSync(backup)) return;
  renameSync(backup, manifest);
  console.log("publish-manifest: package.json restored to the workspace shape");
}

const cmd = process.argv[2];
if (cmd === "apply") apply();
else if (cmd === "restore") restore();
else if (cmd === "force-restore") {
  if (existsSync(backup)) renameSync(backup, manifest);
} else {
  console.error("usage: publish-manifest.mjs apply|restore|force-restore");
  process.exit(2);
}
