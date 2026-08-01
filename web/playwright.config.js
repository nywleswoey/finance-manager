import { defineConfig, devices } from "@playwright/test";
import { VIEWPORTS } from "./tests/viewports.js";

const PORT = Number(process.env.PREVIEW_PORT ?? 4173);

/**
 * The repo's first JS test infrastructure. Geometry only — see `tests/baseline.spec.js`
 * for what this suite does and does not claim.
 *
 * Served from a production build through vite's preview server rather than the dev
 * server, so the suite tests what ships: the same bundling, the same CSS ordering, the
 * same minification. `make test-web` does the build; the webServer block below only
 * serves it.
 *
 * One project per named viewport, so a failure reads as "phone-tier-last-pixel broke"
 * rather than as a line number.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? "list" : [["list"], ["html", { open: "never" }]],
  timeout: 60_000,

  use: {
    baseURL: `http://localhost:${PORT}`,
    // Geometry only. Screenshot and visual-diff assertions are deliberately absent from
    // this suite — nothing in the responsive spec is a claim about colour or exact
    // rendering, and screenshot suites are what make teams abandon these harnesses.
    screenshot: "off",
    video: "off",
    trace: process.env.CI ? "on-first-retry" : "retain-on-failure",
  },

  projects: [
    // Checks that read files rather than pixels — the checklist/viewport parity, the
    // table inventory, the fixtures' own integrity. They do not depend on a viewport, so
    // running them ten times would only make ten identical failures out of one.
    { name: "inventory", testMatch: /inventory\.spec\.js/ },
    ...VIEWPORTS.map((v) => ({
      name: v.name,
      testMatch: /(baseline|unconditional|foundations|shell)\.spec\.js/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: v.width, height: v.height },
      },
    })),
  ],

  webServer: {
    command: `npm run preview -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
