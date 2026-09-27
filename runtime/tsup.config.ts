import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm"],
  dts: true,
  // Engine-neutral: no Node built-ins, no DOM — the same bundle runs in a
  // browser, Node, Deno, Bun or an embedded JS engine.
  platform: "neutral",
  target: "es2022",
  outDir: "dist",
  clean: true,
});
