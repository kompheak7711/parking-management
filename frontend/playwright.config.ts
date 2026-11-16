// UI v81 (owner 08/11/2026 06:55, point 4): the screen checks. Every screen of the list in
// e2e/screens.ts opens at five sizes against the built app, with the server answers replayed
// from e2e/fixtures (no database, no API), and the check fails on horizontal overflow, a
// button, link or tab under 44 × 44 px, colour contrast under 4.5:1 (axe-core), cut-off text or
// numbers, a role badge inside a button, a card alone in a grid row on a desktop, and two
// stacked tables. `npm run screens` here and in CI.

import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

// With the local certificate of vite.config.ts in place the preview serves HTTPS; CI has none.
const certificate = fileURLToPath(
  new URL("../.local/https/server.pem", import.meta.url),
);
const origin = `${existsSync(certificate) ? "https" : "http"}://127.0.0.1:4173`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: process.env.CI !== undefined,
  retries: 0,
  workers: process.env.CI === undefined ? undefined : 2,
  reporter: process.env.CI === undefined ? "list" : [["list"], ["github"]],
  timeout: 90_000,
  outputDir: "./e2e/results",
  use: {
    baseURL: origin,
    ignoreHTTPSErrors: true,
    trace: "off",
    screenshot: "off",
    video: "off",
    // The preinstalled browser of the cloud review machine; left out elsewhere.
    launchOptions:
      process.env.PLAYWRIGHT_CHROMIUM === undefined
        ? {}
        : { executablePath: process.env.PLAYWRIGHT_CHROMIUM },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: {
    // The built app (`npm run build` first; CI builds in its own step).
    command: "npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: origin,
    ignoreHTTPSErrors: true,
    reuseExistingServer: process.env.CI === undefined,
    timeout: 180_000,
  },
});
