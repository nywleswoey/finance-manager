/**
 * Inventory checks: the things that must agree with each other, and the fixtures' own
 * integrity. Nothing here opens a browser.
 *
 * These exist because the mobile-responsive planning effort was burned by exactly two
 * kinds of drift. Four tables went unassigned through the whole effort, because two
 * views never entered the inventory and two tables render only behind a conditional —
 * so the table count is asserted rather than grepped by hand. And the automated sweep
 * and the manual checklist are two lists of the same ten viewports, which is one list
 * too many unless something checks they still match.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { HSCROLL_GATE_APPLIES_BELOW, VIEWPORTS } from "./viewports.js";
import { HSCROLL_BASELINE } from "./hscroll-baseline.js";
import { PATHOLOGICAL, readFixture } from "./fixtures/index.js";
import { VIEWS } from "./support/app.js";

const WEB = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const REPO = path.dirname(WEB);

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    return e.isDirectory() ? sourceFiles(full) : [full];
  });
}

test("the table inventory is 22", () => {
  // The same count `RESPONSIVE.md` asks a human to run by hand:
  //     grep -ro "<table" web/src | wc -l
  // A table added or removed without updating the per-view assignment table makes that
  // table stale, and a stale assignment table is precisely how four tables went through
  // an entire planning effort with no pattern assigned to them.
  const tables = sourceFiles(path.join(WEB, "src"))
    .map((f) => (fs.readFileSync(f, "utf8").match(/<table/g) ?? []).length)
    .reduce((a, b) => a + b, 0);
  expect(tables, "web/src table count — update RESPONSIVE.md's per-view table if this moved")
    .toBe(22);
});

test("exactly one donut implementation exists", () => {
  // `portfolio/Overview.jsx` carried a hand-copied duplicate of `charts.jsx`'s `Donut`,
  // with its own 7-colour palette, so every chart change had to land twice across four
  // call sites — and the copy sorted the caller's array in place during render. Counting
  // `<PieChart` is what makes "merged" a fact rather than a commit message: a second copy
  // can be re-introduced by paste in ten seconds, and this is the only thing that notices.
  const pies = sourceFiles(path.join(WEB, "src"))
    .flatMap((f) => (fs.readFileSync(f, "utf8").match(/<PieChart/g) ?? []).map(() => path.relative(WEB, f)));
  expect(pies, "files rendering a <PieChart> — the donut is shared, not copied").toHaveLength(1);
});

test("the ten viewports match the manual checklist one-for-one", () => {
  // RESPONSIVE.md's viewport table is the human-facing list; `viewports.js` is the
  // machine-facing one. Two lists of the same ten viewports drift the moment nothing
  // reads both, so this reads both — names as well as sizes, and in order, because the
  // name is what you type at `--project=` and what a failure is reported under.
  const md = fs.readFileSync(path.join(REPO, "RESPONSIVE.md"), "utf8");
  const section = md.split("## Viewports")[1].split("\n##")[0];
  const fromChecklist = [
    ...section.matchAll(/\|\s*\d+\s*\|\s*\**(\d+)×(\d+)\**\s*\|\s*`([a-z-]+)`\s*\|/g),
  ].map(([, w, h, name]) => `${name} ${w}x${h}`);

  expect(fromChecklist, "parsed from RESPONSIVE.md's viewport table").toHaveLength(10);
  expect(VIEWPORTS.map((v) => `${v.name} ${v.width}x${v.height}`)).toEqual(fromChecklist);
});

test("the horizontal-overflow baseline covers every gated viewport and view", () => {
  // A missing entry defaults to 0 and so fails loudly, but a *stale* one — a view
  // renamed or removed — would sit in the file forever pretending to hold a defect that
  // no longer exists. Both directions are checked here so the ratchet stays honest about
  // what it is actually ratcheting.
  const gated = VIEWPORTS.filter((v) => v.width < HSCROLL_GATE_APPLIES_BELOW).map((v) => v.name);
  expect(Object.keys(HSCROLL_BASELINE).sort()).toEqual([...gated].sort());
  const views = VIEWS.map((v) => v.name).sort();
  for (const vp of gated) {
    expect(Object.keys(HSCROLL_BASELINE[vp]).sort(), `baseline entries for ${vp}`).toEqual(views);
  }
});

test.describe("the fixtures carry the pathological rows they exist for", () => {
  // Fixtures that were merely *plausible* are what produced the error these exist to
  // prevent: the top-line-items card measured 415px against invented rows during
  // planning and 519px against real ones. Each case below names why it is here.
  for (const c of PATHOLOGICAL) {
    test(c.name, () => {
      const { ok, saw } = c.holds(readFixture(c.fixture));
      expect(ok, `${c.fixture}: ${saw}`).toBe(true);
    });
  }
});

test("no screenshot or visual-diff assertions anywhere in the suite", () => {
  // Scoped out by decision, not by omission. Nothing in the responsive spec is a claim
  // about colour or exact rendering, and screenshot suites are the thing that makes
  // teams abandon these harnesses. Asserting it keeps the decision from eroding one
  // convenient `toHaveScreenshot` at a time.
  const offenders = sourceFiles(path.join(WEB, "tests"))
    .filter((f) => f.endsWith(".js"))
    // This file names the forbidden calls in order to look for them, so it cannot be
    // its own subject.
    .filter((f) => f !== fileURLToPath(import.meta.url))
    .filter((f) => /toHaveScreenshot|toMatchSnapshot|screenshot\(/.test(fs.readFileSync(f, "utf8")));
  expect(offenders.map((f) => path.relative(WEB, f))).toEqual([]);
});
