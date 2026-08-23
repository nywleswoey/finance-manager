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
    // Holdings' ticker fold is arithmetic, not layout: a consolidated row is either the right
    // number or the wrong one, and it is the same number at every width. One viewport, once —
    // running it ten times would only make ten identical failures out of one, which is the same
    // reasoning the inventory project is built on.
    {
      name: "ticker",
      testMatch: /ticker\.spec\.js/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    // The New Snapshot form's groupings, on the same reasoning: which item is typed under which
    // heading is the catalogue's banding or it is a second banding, and that is the same
    // partition at every width. `editors.spec.js` keeps the form's geometry at all ten.
    {
      name: "catalogue",
      testMatch: /catalogue\.spec\.js/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    // The composition chart's four unreachable states, on the same reasoning again: an empty
    // state is copy, a tick crossover is a count, and where a negative band lands is
    // arithmetic. None of the three is a claim about width, and two of them need a payload the
    // live database cannot hold — see that file's docstring. `charts.spec.js` keeps everything
    // the chart does that IS about width at all ten.
    {
      name: "composition",
      testMatch: /composition\.spec\.js/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    // What a failed payload does to the page that asked for it, on the same reasoning once
    // more: whether a component survives a payload it cannot read is the same at 360px and at
    // 1440px. It needs a deliberately-served failure, because every fixture is a capture of a
    // working database and so none of them is one.
    {
      name: "failures",
      testMatch: /failures\.spec\.js/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    ...VIEWPORTS.map((v) => ({
      name: v.name,
      testMatch: /(baseline|unconditional|foundations|shell|pinned|cards|drill|charts|editors|tablet|tap)\.spec\.js/,
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
