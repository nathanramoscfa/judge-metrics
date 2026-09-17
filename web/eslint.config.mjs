// web/eslint.config.mjs
// Next.js core-web-vitals and TypeScript rules plus eslint-plugin-security
// (SAST for the web tier; part of the security gate). `dangerouslySetInnerHTML`
// and `eval` are forbidden outright rather than merely warned about.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import security from "eslint-plugin-security";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  security.configs.recommended,
  {
    rules: {
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "react/no-danger": "error",
      "security/detect-object-injection": "off",
    },
  },
  {
    // Test files read the build output and temp files at paths derived from
    // constants, never from input; the rule stays on for application code.
    files: ["tests/**/*.{ts,tsx}", "vitest.config.ts", "playwright.config.ts"],
    rules: {
      "security/detect-non-literal-fs-filename": "off",
    },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "lib/api/schema.d.ts",
    "playwright-report/**",
    "test-results/**",
  ]),
]);

export default eslintConfig;
