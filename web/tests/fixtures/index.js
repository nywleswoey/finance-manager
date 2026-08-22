/**
 * The fixture route table — the suite's one seam.
 *
 * Everything above the HTTP API boundary (real Chromium, real layout engine, real
 * media-query evaluation) is the application under test. Everything below it is these
 * files. This is the same substitution shape the backend suite already uses one layer
 * down, where Postgres is swapped for in-memory SQLite at the persistence boundary.
 *
 * The frontend's `api.js` is the app's only chokepoint to the server: all thirteen views
 * call through it, and the auth gate turns on a single session endpoint. Mocking that one
 * endpoint renders the whole app without Google, because the identity script only loads
 * on the login screen.
 *
 * The files under `api/` are derived from the live database once, by
 * `scripts/capture_web_fixtures.py`, and committed. They are not hand-written and should
 * not be hand-edited: every measurement in the responsive spec is data-dependent, and
 * plausible-looking rows are exactly what produced the 415px-vs-519px error that made
 * fixtures necessary in the first place.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const API_DIR = path.join(HERE, "api");

/** path -> { file, status }, written by the capture script. */
const MANIFEST = JSON.parse(fs.readFileSync(path.join(HERE, "manifest.json"), "utf8"));

/**
 * Collapse a request path to a comparison key: pathname plus its query parameters in a
 * fixed order. Without this, `?a=1&b=2` and `?b=2&a=1` are different fixtures, and
 * `encodeURIComponent`'s `%20` never matches `URLSearchParams`' `+` for the same string.
 */
export function normalize(pathAndQuery) {
  const u = new URL(pathAndQuery, "http://fixture.invalid");
  const params = [...u.searchParams.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const query = params.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  return u.pathname + (query ? `?${query}` : "");
}

const ROUTES = new Map(
  Object.entries(MANIFEST).map(([p, entry]) => [normalize(p), entry])
);

// Cached per worker process. The route handler is on the hot path of every page load and
// the largest fixture is a third of a megabyte, so re-reading and re-parsing it per
// request would cost more than the assertions do. Nothing mutates a fixture body.
const cache = new Map();

export function readFixture(file) {
  if (!cache.has(file)) {
    cache.set(file, JSON.parse(fs.readFileSync(path.join(API_DIR, file), "utf8")));
  }
  return cache.get(file);
}

/** The recorded response for a request path, or null if nothing was captured for it. */
export function fixtureFor(pathAndQuery) {
  const entry = ROUTES.get(normalize(pathAndQuery));
  if (!entry) return null;
  return { status: entry.status, body: readFixture(entry.file) };
}


/**
 * The spend trend's counterfactual: how many pixels the SMALLEST of the four series would get
 * if all four shared one y-axis floored at zero, in a panel plot 140px tall
 * (`SpendTrend.jsx`'s PANEL_H).
 *
 * Exported because two things need it and they need it for opposite reasons. The pathological
 * row below asserts the fixtures still CARRY the spread — a window whose four series happened
 * to agree in magnitude would pass "no series is flattened onto the floor" under a shared axis
 * too, which is the one way that gate goes quietly vacuous. `charts.spec.js` prints the same
 * number as the annotation beside what each panel actually drew. Two copies of this arithmetic
 * could disagree, and the pair only means anything if they cannot.
 *
 * `scripts/capture_web_fixtures.py` carries the third — deliberately, and for the reason every
 * pathological row is asserted twice: that one fails at the source, the moment a recapture
 * would have dropped the spread. Move the 5px threshold in one and move it in the other.
 */
export function sharedAxisSpanPx(trends, window, plotPx = 140) {
  const rows = trends.series.filter((r) => r.ym >= window.start && r.ym <= window.end);
  const spans = trends.groups.map((name) => {
    const vals = rows.map((r) => Number(r[name] ?? 0));
    return { name, lo: Math.min(...vals), hi: Math.max(...vals) };
  });
  const ceiling = Math.max(...spans.map((s) => s.hi));
  const worst = spans.reduce((a, b) => (b.hi - b.lo < a.hi - a.lo ? b : a));
  return { name: worst.name, px: ((worst.hi - worst.lo) / ceiling) * plotPx };
}

/**
 * The five pathological rows the fixtures exist to carry, each with the reason it is
 * here. `inventory.spec.js` asserts every one of them, so these are load-bearing checks
 * rather than commentary: the moment a recapture drops one, the suite says so.
 *
 * Every one of these came out of planning, and each of them either broke a measurement
 * or would have. Fixtures that were merely *plausible* would not contain any of them.
 *
 * `scripts/capture_web_fixtures.py` asserts the same five at capture time, so a
 * recapture cannot quietly drop one. Move a threshold here and move it there.
 *
 * `fixture` IS ONE FILE OR SEVERAL. Four of these are a claim about one payload; the
 * fifth is a claim about two together, because the spread that decides the spend trend's
 * whole form only exists inside the window a second endpoint defines.
 */
export const PATHOLOGICAL = [
  {
    name: "the 30-character subcategory name",
    // "Life/Health/Surgical Insurance". This single string is why the top-line-items
    // card needs 519px rather than the ~420px the two-column grid's minimum
    // optimistically assumes, and it is the row that truncates to nothing on a phone.
    fixture: "spending-summary.json",
    holds: (body) => {
      const subs = body.by_subcategory ?? [];
      const longest = subs.reduce((m, s) => Math.max(m, (s.subcategory ?? "").length), 0);
      return { ok: longest >= 30, saw: `longest subcategory is ${longest} chars` };
    },
  },
  {
    name: "a security with 73 option trades",
    // PLTR. The longest options history in the database, which makes SecurityDetail's
    // options table the tallest table in the app. It is also why the suite reaches
    // SecurityDetail through PLTR rather than through whatever sorts first.
    fixture: "options-trades.json",
    holds: (body) => {
      const n = body.filter((t) => t.underlying === "PLTR").length;
      return { ok: n >= 73, saw: `PLTR has ${n} option trades` };
    },
  },
  {
    name: "a 65-character merchant string",
    // Unbounded free text in a single cell, at its worst. The rule that decides whether
    // a table needs a pattern is "does any column hold unbounded free text?", so this
    // row is the one that decides it. It sits older than the newest 1000 rows the view
    // asks for, so the capture script splices it in deliberately — see that script.
    fixture: "spending-transactions.json",
    holds: (body) => {
      const longest = body.reduce((m, r) => Math.max(m, (r.merchant ?? "").length), 0);
      return { ok: longest >= 65, saw: `longest merchant is ${longest} chars` };
    },
  },
  {
    name: "the ~150x spread inside the spend-trend window",
    // What makes the spend trend small multiples rather than one chart. Four series in the
    // same window differ by two orders of magnitude, so under a single y-axis floored at
    // zero the smallest of them is drawn flat: this computes that counterfactual and holds
    // it under 5px of the 140px plot the panels actually get. A recapture that flattened the
    // spread — a quiet month, a reclassification — would leave `charts.spec.js`'s "none is
    // flattened onto the floor" gate passing against data where a shared axis would have
    // passed it too, which is the one way that gate can go quietly vacuous.
    fixture: ["spending-trends.json", "spending-window.json"],
    holds: (trends, win) => {
      const { name, px } = sharedAxisSpanPx(trends, win);
      return { ok: px < 5,
               saw: `${name} would draw ${px.toFixed(1)}px of a 140px plot under a shared axis` };
    },
  },
  {
    name: "the null-category row",
    // Unclassified spend, where `category` is NULL. It renders as "Uncategorized", is
    // deliberately not drillable, and is the one row in the category table with a
    // different shape. It is also what used to make /api/spending/trends return a 500 —
    // `sorted()` over {str, None} — so this row is what the stacked chart's
    // "Uncategorized" band is drawn from, and dropping it from the database would take
    // that band with it.
    fixture: "spending-summary.json",
    holds: (body) => {
      const groups = body.by_group ?? [];
      const n = groups.filter((g) => g.category == null).length;
      return { ok: n > 0, saw: `${n} null-category groups` };
    },
  },
];
