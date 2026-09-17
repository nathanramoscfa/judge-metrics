// web/tests/unit/bundle-secrets.test.ts
// Only NEXT_PUBLIC_* variables may reach the client bundle. This scans the
// production build output for the server-side `JUDGEMETRICS_` prefix and
// fails on any hit. It needs `pnpm build` to have run: locally it skips when
// there is no build; in CI (CI=true) a missing build is itself a failure, so
// the `web` job builds before it tests.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = resolve(__dirname, "../..");
const BUILD_DIRS = ["static", "server"].map((dir) => resolve(WEB_ROOT, ".next", dir));
const FORBIDDEN = /JUDGEMETRICS_[A-Z0-9_]+/g;
const SCANNED_EXTENSIONS = new Set([".js", ".mjs", ".cjs", ".json", ".html", ".css", ".txt", ".rsc"]);

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      yield* walk(path);
    } else if ([...SCANNED_EXTENSIONS].some((ext) => path.endsWith(ext))) {
      yield path;
    }
  }
}

const built = BUILD_DIRS.every((dir) => existsSync(dir));

describe("production build output", () => {
  if (process.env.CI && !built) {
    it("exists in CI", () => {
      throw new Error("no .next build to scan: run `pnpm build` before `pnpm test` in CI");
    });
    return;
  }

  it.skipIf(!built)("contains no JUDGEMETRICS_ variable", () => {
    const hits: string[] = [];
    let scanned = 0;
    for (const dir of BUILD_DIRS) {
      for (const file of walk(dir)) {
        scanned += 1;
        const matches = readFileSync(file, "utf8").match(FORBIDDEN);
        if (matches) {
          hits.push(`${relative(WEB_ROOT, file)}: ${[...new Set(matches)].join(", ")}`);
        }
      }
    }
    expect(scanned).toBeGreaterThan(0);
    expect(hits, `server-side variables reached the build output:\n${hits.join("\n")}`).toEqual([]);
  });
});
