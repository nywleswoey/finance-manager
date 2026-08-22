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
import { HSCROLL_GATE_APPLIES_BELOW, PHONE_TIER_EDGE, VIEWPORTS } from "./viewports.js";
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

/**
 * Source with its comments removed — `/* *\/` and `//` alike, which covers JS and CSS both.
 *
 * Three gates below forbid a construct, and every file that dropped that construct explains
 * at length what it dropped and why. A grep that cannot tell prose from markup makes the
 * explanation the violation, and what gets deleted then is the explanation.
 */
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

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

test("no chart renders the library's own legend", () => {
  // `<Legend>` is a chart child, so its space comes out of the plot — measured at ~75px of
  // the stacked bar chart's 300px, a quarter of the drawing spent on eight words. Every key
  // in the app is DOM under the container instead.
  //
  // Source-grepped as well as measured, and it stays that way now that both can be. The one
  // chart that had a `<Legend>` used to be the one surface the suite could not reach at all —
  // `/api/spending/trends` was captured as a 500, so `trend.series.length > 0` was false and
  // the chart never mounted, leaving this grep as its only coverage. The endpoint is fixed
  // and `charts.spec.js` now asserts that chart's key in the DOM, but a grep still catches
  // what a DOM gate cannot: a `<Legend>` added to a chart no fixture happens to mount.
  //
  // Comments are stripped first, for the reason the `100vh` gate strips them: four files
  // explain at length what `<Legend>` did and why it is gone, and a gate that cannot tell
  // prose from markup gets the explanation deleted rather than the defect.
  const offenders = sourceFiles(path.join(WEB, "src"))
    .filter((f) => /<Legend[\s/>]/.test(stripComments(fs.readFileSync(f, "utf8"))))
    .map((f) => path.relative(WEB, f));
  expect(offenders, "render the key as DOM — `ChartKey` in `charts.jsx`").toEqual([]);
});

test("both multi-series charts carry a DOM key", () => {
  // The counterpart of the gate above: forbidding `<Legend>` is satisfied by having no key
  // at all, which is exactly the state `NetWorth` shipped in — two coloured lines named only
  // in a tooltip that touch never opens. Named files rather than a count, because "multi-
  // series" is not greppable and a third one arriving should have to be added here by hand.
  //
  // Comments stripped, like its two siblings — and here the direction of the mistake is the
  // interesting one. The `<Legend>` gate forbids a construct, so a prose mention would fail it
  // wrongly; this gate *requires* one, so a prose mention would PASS it wrongly. `charts.jsx`
  // names `<ChartKey>` in its own docstring, which is exactly the shape that would.
  //
  // `NetWorth.jsx` LEFT THIS LIST BY LOSING ITS CHART, not by losing its key: the two anonymous
  // lines were replaced by the composition chart in a file of its own, so the multi-series
  // surface on that view is now `Composition.jsx` and the key moved with it. The spend trend is
  // deliberately NOT here and must not be added: it is small multiples, four panels of one
  // series each, and its panel headers *are* its key — a shared key beneath the grid would
  // restate four names written immediately above four panels.
  const wanted = ["src/modules/networth/Composition.jsx", "src/modules/spending/Overview.jsx"];
  const keyed = sourceFiles(path.join(WEB, "src"))
    .filter((f) => /<ChartKey[\s/>]/.test(stripComments(fs.readFileSync(f, "utf8"))))
    .map((f) => path.relative(WEB, f))
    .sort();
  expect(keyed, "a multi-series chart with no key is anonymous on touch").toEqual(wanted);
});

test("no spending surface indexes the positional palette", () => {
  // `POSITIONAL_COLOURS` is an ordered array, so reading it is reading a *position*. The
  // donut's list, the monthly stacked bar and the by-category row markers each indexed it
  // with their own `i` — and those three orders are three different sorts of the same four
  // names (spend descending, alphabetical, and this-year's spend descending), which is how
  // Personal came out blue in one card and green in the next one down.
  //
  // The array itself stays: the portfolio donut slices by market and by account, which is
  // not a taxonomy anything can key a map on. What is forbidden is a *second* consumer, and
  // the file that owns the donut is the only one allowed to be it.
  //
  // Comments stripped, like its siblings above — `charts.jsx` and both spending views
  // explain at length what they used to index and why they no longer do.
  const importers = sourceFiles(path.join(WEB, "src"))
    .filter((f) => /\bPOSITIONAL_COLOURS\b/.test(stripComments(fs.readFileSync(f, "utf8"))))
    .map((f) => path.relative(WEB, f))
    .sort();
  expect(importers, "colour by name — `categoryColour` / `BAND_COLOURS` in `palette.js`")
    .toEqual(["src/charts.jsx", "src/palette.js"]);
});

test("no source file hard-codes a net-worth catalogue code", () => {
  // WHAT THIS FORBIDS IS A LIST OF ITEMS. The New Snapshot form used to render a constant that
  // named fourteen item codes under four headings — not the catalogue it is capturing — so an
  // item in no list rendered no row, `save()` never sent it, and the creator's zeroing rule
  // fabricated a $0 for it on every capture with nothing on screen to say so. The form now reads
  // `band` off the catalogue; this is what stops the constant coming back, in that file or in a
  // new one, because a paste re-introduces it in ten seconds and nothing else would notice.
  //
  // A behavioural gate cannot close this on its own. `catalogue.spec.js` proves the *rendering*
  // is derived — it serves a fifteenth item and finds its row — but a list kept for the headings
  // alone, or for a subset of rows, would pass every assertion in that file and still be a second
  // catalogue free to drift from the first.
  //
  // DERIVED FROM THE FIXTURE, so a recapture keeps the gate honest rather than stale. `srs` is
  // the one code held out, and the reason is a three-way collision rather than an exemption: the
  // same word is a catalogue *code*, a *band* value (`NetWorth.jsx`'s `BAND_TITLES` is keyed on
  // bands and legitimately writes it) and a *funding bucket* (`Dividends.jsx`'s `BUCKET_LABEL`,
  // `account.funding_bucket` server-side). Three partitions, one word — so this gate cannot see
  // it, and the gate's claim is therefore about the other thirteen. They still cover the deleted
  // constant, which named all fourteen. RENAMING THE `srs` ITEM IS THE ONE CHANGE THIS WOULD NOT
  // CATCH: `BAND_TITLES.srs` would go dead silently, so check it by hand if that day comes.
  //
  // Comments stripped, like its siblings above: this file and `NetWorth.jsx` both explain at
  // length what the constant was, and a gate that cannot tell prose from markup gets the
  // explanation deleted rather than the defect. `stripComments` only strips a `//` that starts a
  // line, so a code written in a TRAILING comment would fail this gate on prose — `palette.js`
  // already has one for `srs`, which the hold-out above happens to cover. The next one will not
  // be covered, and the fix then is that comment or this regex, not the exemption list.
  const codes = readFixture("networth-items.json").map((i) => i.code).filter((c) => c !== "srs");
  expect(codes.length, "the catalogue fixture is empty — this gate would be vacuous")
    .toBeGreaterThan(0);

  const offenders = sourceFiles(path.join(WEB, "src")).flatMap((f) => {
    const src = stripComments(fs.readFileSync(f, "utf8"));
    return codes
      .filter((c) => new RegExp(`\\b${c}\\b`).test(src))
      .map((c) => `${path.relative(WEB, f)}: ${c}`);
  });
  expect(offenders, "group by `band` off the catalogue — see `BAND_TITLES` in `NetWorth.jsx`")
    .toEqual([]);
});

test("the two colour maps agree about Housing", async () => {
  // THE COUPLING IS DELIBERATE AND THIS IS WHERE IT IS ENFORCED. Spend Housing holds
  // Mortgage, Property Taxes and Utilities — the running cost of the same HDB whose equity
  // is the net-worth Housing band — so the two maps name one thing and share its colour.
  // Not a homonym, and so not something to break apart when one map is recoloured.
  //
  // A test rather than only a comment because the two maps are read by different views and
  // nothing renders them side by side: recolour one and no viewport in this suite would
  // look wrong. If a future decision genuinely decouples them, this is the file that has to
  // be edited to say so — which is the whole point, since editing it means having looked at
  // the other map.
  const { CATEGORY_COLOURS, BAND_COLOURS } = await import("../src/palette.js");
  expect(CATEGORY_COLOURS.Housing,
    "a recolour of either map must check the other — see `palette.js`")
    .toBe(BAND_COLOURS.housing);
});

test("the composition's cumulative edges are the summary tiles, to the cent", () => {
  // THE ANCHOR CLAIM OF THE COMPOSITION CHART, and the reason its band order is load-bearing:
  // accumulate the bands bottom→top and three of the four running totals ARE three of the six
  // tiles printed directly above the chart. The chart stacks in the payload's `bands` order and
  // names those edges in its footnote, so a reordered `bands` array would leave the footnote
  // pointing at boundaries that equal nothing — with no viewport looking wrong.
  //
  // Two payloads compared against each other rather than pixels read off a chart, because that
  // is where the identity lives: `/api/networth/composition`'s last point and
  // `/api/networth/latest`'s metrics are two views of one snapshot. `tests/test_networth.py`
  // holds the same identity one layer down, against the database; this holds it across the two
  // committed fixtures the browser actually draws, which is what a recapture could break.
  //
  // Exact equality, never approximate: the server derives each band as the difference between
  // adjacent *rounded* edges precisely so this is true by arithmetic instead of by luck.
  // ASSERTED AT THE SNAPSHOT THE TWO FIXTURES SHARE, not at the composition's last point, and
  // the difference is a fact about the capture rather than about the identity: the composition
  // fixture was captured against the merged five-point history the chart is specced for, while
  // `latest` and `snapshots` still hold the two-point capture that predates the promotion. So
  // the newest point has no metrics fixture to be compared against. Finding the shared date
  // keeps the gate true both today and after a recapture folds them back together — and fails
  // loudly if a recapture ever leaves them with no snapshot in common at all.
  const comp = readFixture("networth-composition.json");
  const latest = readFixture("networth-latest.json");
  const point = comp.series.find((p) => String(p.date) === String(latest.date));
  expect(point, `no composition point for ${latest.date} — the two fixtures share no snapshot`)
    .toBeTruthy();

  const edges = {};
  let running = 0;
  for (const b of comp.bands) edges[b] = running = Math.round((running + point[b]) * 100) / 100;

  // Bottom→top: cash is no tile, then the three that are. Named here rather than derived,
  // because the mapping from an edge to a metric is the decision this gate exists to pin —
  // `Composition.jsx`'s EDGE_NAMES prints these same three, in these same words.
  expect(edges[comp.bands[1]], "excl. Housing & CPF Cash is the edge above Portfolio")
    .toBe(latest.net_worth_excl_housing_cpf);
  expect(edges[comp.bands[2]], "excl. Housing is the edge above CPF cash")
    .toBe(latest.net_worth_excl_housing);
  expect(edges[comp.bands[3]], "net worth is the top edge").toBe(latest.net_worth);
});

test("the composition chart's crossover is not keyed to viewport width", () => {
  // ITS TICK RULE AND ITS DOTS SHARE ONE CONSTANT — six — and the reason it must never become a
  // function of viewport width is measured rather than stylistic: the plot width of a chart in
  // this app's two-column grid is NON-MONOTONIC in viewport width, 726px at 1100 and 335px at
  // 1180 where the grid flips to two columns. A width-derived rule therefore hands the generous
  // branch to the narrower plot, at the chart's own worst width.
  //
  // Asserted as an absence of any viewport read in that file: no `matchMedia`, and no `usePhone`.
  // The `640` gate below cannot catch this — a rule keyed to 1024, or to a `usePhone()` call,
  // would leave that count at four. Comments are stripped, because the file explains at length
  // what it must not do.
  const src = stripComments(
    fs.readFileSync(path.join(WEB, "src/modules/networth/Composition.jsx"), "utf8"));
  expect(src.match(/matchMedia|usePhone|innerWidth|ResizeObserver/g),
    "the tick crossover must be one constant at every width — see `TICK_CROSSOVER`")
    .toBeNull();
});

test("`640` is written in exactly four places", () => {
  // The stylesheet, the suite, `Holdings.jsx`'s read-at-mount and `cards.jsx`'s `usePhone` —
  // no build step makes a single source of truth possible, so what is left is counting them
  // and cross-referencing in comments. The map expected the charts to add a fifth; they read
  // `usePhone()` instead, and this is what keeps that decision from eroding.
  //
  // FILES, not occurrences. `viewports.js` writes the number four times — two exported
  // constants and two viewport rows either side of the edge — and those are one site by any
  // reading that matters: they are in one file, under one comment, and they move together.
  // What this is counting is the number of places a reader has to know about.
  //
  // Comments are excluded, because every one of these four sites explains at length where the
  // other three are — a gate that counts its own cross-references counts twelve.
  const sites = [...new Set(
    [
      ...sourceFiles(path.join(WEB, "src")),
      ...sourceFiles(path.join(WEB, "tests")).filter((f) => f.endsWith("viewports.js")),
    ]
      .filter((f) => /639\.98|\b640\b/.test(stripComments(fs.readFileSync(f, "utf8"))))
      .map((f) => path.relative(WEB, f))
  )].sort();
  expect(sites, "a new literal 640 — reuse `usePhone()` or add the site to every comment")
    .toEqual([
      "src/cards.jsx",
      "src/modules/portfolio/Holdings.jsx",
      "src/styles.css",
      "tests/viewports.js",
    ]);
});

test("both JavaScript media queries say exactly what the stylesheet says", () => {
  // COUNTING THE SITES IS NOT CHECKING THEY AGREE, and the gate above only counts. Rewrite
  // `cards.jsx`'s query as `(max-width: 640px)` and the count is still four, every comment is
  // still true to the word, and the whole card-per-row tier has silently moved into the 1px
  // dead zone against the tablet tier's `min-width: 640px` — which is the entire reason the
  // number is `639.98` and not `639`. This is the assertion the spec asked for by name.
  //
  // The stylesheet side is `foundations.spec.js`'s job: it reads the *shipped* CSS, where the
  // build has rewritten `@media (max-width: 639.98px)` into range syntax and only the number
  // survives. So the two halves meet at `PHONE_TIER_EDGE` rather than at each other.
  const want = `(max-width: ${PHONE_TIER_EDGE})`;
  const queries = [
    ["src/cards.jsx", "usePhone — the live layout hook"],
    ["src/modules/portfolio/Holdings.jsx", "startsCollapsed — the read at mount"],
  ].map(([file, what]) => {
    const src = stripComments(fs.readFileSync(path.join(WEB, file), "utf8"));
    return [what, src.match(/matchMedia\(\s*"([^"]*)"|"(\(max-width:[^"]*\))"/)?.slice(1).find(Boolean)];
  });
  for (const [what, query] of queries) {
    expect(query, `${what}: its media query must be the tier edge, character for character`)
      .toBe(want);
  }
});

test("no `vh` unit survives anywhere under web/src", () => {
  // The shell and sign-in both moved to `svh`, for two different reasons: `height: 100vh`
  // leaves a permanently *unreachable* strip in a shell that owns its own scroll, and
  // `min-height: 100vh` leaves a *scrollable* one that pushes centred content ~32px low.
  // Neither reproduces in a browser with no retractable toolbar, so this grep is the only
  // gate the suite can hold on it — and the same one a reviewer would run by eye.
  //
  // WIDENED FROM `100vh` TO THE UNIT, when the rule modal's `6vh` / `84vh` became `svh`.
  // `100vh` was the whole population at the time and the gate was written to the population
  // rather than to the rule; the two fractions in that modal are the same defect at a
  // smaller number, and the sheet's cap growing past the screen is exactly the failure
  // `lvh` produces. `\d…vh` does not match `100svh` — the character before `vh` is `s` —
  // so the correct unit is not caught by the gate that forbids the wrong one.
  //
  // Comments are stripped first — three files explain at length what `vh` did and why it
  // is gone, and a gate that forbids naming the thing it forbids is a gate that gets the
  // explanation deleted rather than the defect.
  const offenders = sourceFiles(path.join(WEB, "src"))
    .filter((f) => /\d(?:\.\d+)?vh\b/.test(stripComments(fs.readFileSync(f, "utf8"))))
    .map((f) => path.relative(WEB, f));
  expect(offenders, "`vh` is `lvh` by spec — use `svh`").toEqual([]);
});

test("the viewport meta opts into the safe area", () => {
  // `foundations.spec.js` asserts this on the served document. Here because the source is
  // where a reviewer looks, and because a build that silently dropped it would fail there
  // with no indication of which of the two files was wrong.
  const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
  const meta = html.match(/<meta name="viewport"[^>]*content="([^"]*)"/)?.[1];
  expect(meta, "web/index.html has no viewport meta tag").toBeTruthy();
  expect(meta, "without `viewport-fit=cover` every env(safe-area-inset-*) resolves to 0")
    .toContain("viewport-fit=cover");
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
