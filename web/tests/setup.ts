// web/tests/setup.ts
// Vitest setup: Testing Library's jest-dom matchers and DOM cleanup.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
