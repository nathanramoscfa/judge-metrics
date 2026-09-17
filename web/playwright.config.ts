// web/playwright.config.ts
// Browser smoke test against a running web app and API. This config starts
// nothing itself: CI (the `e2e` job) and the operator provide the API on
// NEXT_PUBLIC_API_BASE_URL and the web server on PLAYWRIGHT_BASE_URL
// (default http://localhost:3000; `pnpm build && pnpm start`, or `pnpm dev`).
import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
