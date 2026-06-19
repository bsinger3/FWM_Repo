import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:4322",
    headless: true,
    trace: "on-first-retry",
  },
  webServer: {
    command: "node scripts/test-server.mjs",
    url: "http://127.0.0.1:4322",
    // Always launch our own test server. Reusing whatever already listens on the
    // port let a stale dashboard dev server get adopted and serve the wrong
    // pages; if the port is busy now, fail loudly instead of testing silently
    // against the wrong server.
    reuseExistingServer: false,
  },
});
