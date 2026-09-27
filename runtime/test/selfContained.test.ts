/**
 * The package's whole promise is that it is ONLY the playback code: MIT, zero
 * dependencies, no editor module riding along. The moment a src/ file imports
 * anything but a sibling — `@parlance/core`, a validator helper, `fs`, zod —
 * the published bundle either inlines personal-use code under an MIT label or
 * stops running outside Node. Both are silent in a type check and a test run,
 * so this pins it.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "fs";
import { dirname, join, resolve } from "path";
import { fileURLToPath } from "url";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const IMPORT_RE = /(?:^|\n)\s*(?:import|export)\b[^;]*?\bfrom\s+["']([^"']+)["']|(?:^|\n)\s*import\s+["']([^"']+)["']|\bimport\(\s*["']([^"']+)["']\s*\)/g;

function specifiers(file: string): string[] {
  const text = readFileSync(join(SRC, file), "utf-8");
  return [...text.matchAll(IMPORT_RE)].map((m) => (m[1] ?? m[2] ?? m[3])!);
}

describe("runtime package is self-contained", () => {
  const files = readdirSync(SRC).filter((f) => f.endsWith(".ts"));

  it("has source files to check", () => {
    expect(files.length).toBeGreaterThan(5);
  });

  for (const file of files) {
    it(`${file} imports only sibling modules`, () => {
      const outside = specifiers(file).filter((s) => !/^\.\/[A-Za-z0-9_-]+\.js$/.test(s));
      expect(outside).toEqual([]);
    });
  }

  it("declares no runtime dependencies", () => {
    const pkg = JSON.parse(readFileSync(resolve(SRC, "../package.json"), "utf-8")) as Record<string, unknown>;
    expect(pkg.dependencies ?? {}).toEqual({});
    expect(pkg.peerDependencies ?? {}).toEqual({});
  });
});
