import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  expect: {
    timeout: 10_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  use: {
    baseURL: "http://localhost:3001",
  },
  webServer: {
    // Repo-root orchestration: Postgres + migrations + seed + API + web.
    // The first Next.js dev compile is slow, hence the generous timeout.
    command: "make -C ../.. dev",
    url: "http://localhost:3001",
    reuseExistingServer: true,
    timeout: 240_000,
  },
});
