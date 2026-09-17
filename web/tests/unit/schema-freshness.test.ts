// web/tests/unit/schema-freshness.test.ts
// lib/api/schema.d.ts is committed; it must be exactly what `pnpm
// generate:api` writes from ../docs/openapi.json, so a route change that
// regenerated the OpenAPI document without the client types fails here.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const WEB_ROOT = resolve(__dirname, "../..");
const OPENAPI = resolve(WEB_ROOT, "../docs/openapi.json");
const COMMITTED = resolve(WEB_ROOT, "lib/api/schema.d.ts");

function normalize(text: string): string {
  return text.replace(/\r\n/g, "\n");
}

describe("lib/api/schema.d.ts", () => {
  it("is what openapi-typescript generates from docs/openapi.json", () => {
    const cli = resolve(require.resolve("openapi-typescript/package.json"), "../bin/cli.js");
    const dir = mkdtempSync(join(tmpdir(), "judgemetrics-schema-"));
    const output = join(dir, "schema.d.ts");
    try {
      execFileSync(process.execPath, [cli, OPENAPI, "--output", output], {
        cwd: WEB_ROOT,
        stdio: "pipe",
      });
      const generated = normalize(readFileSync(output, "utf8"));
      const committed = normalize(readFileSync(COMMITTED, "utf8"));
      expect(committed).toBe(generated);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }, 30_000);
});
