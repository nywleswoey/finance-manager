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

/**
 * Every ticker a detail payload was captured for, with that payload — read off the route table
 * so a recapture that adds or drops a holding moves what the gates run over.
 *
 * Here rather than in the one spec that walks them, because the route table lives here and a
 * second `fs.readFileSync` of `manifest.json` in a spec file is a second parser of this file's
 * own format.
 */
export function capturedHoldings() {
  return [...ROUTES.entries()]
    .map(([route, entry]) => [/^\/api\/holding\?ticker=(.+)$/.exec(route), entry])
    .filter(([m]) => m)
    .map(([m, entry]) => ({ ticker: decodeURIComponent(m[1]), body: readFixture(entry.file) }))
    .sort((a, b) => (a.ticker < b.ticker ? -1 : 1));
}

/**
 * A captured detail payload with a provenance object beside its summary.
 *
 * The captures that CARRY a carry ship their own `summary.provenance` and need nothing from
 * this — it exists for the shapes the book has no instance of: a written 1:1 carry, and one
 * name's real object on another name's payload. `unknown-book.spec.js` is its only consumer.
 */
export const withProvenance = (body, provenance) =>
  ({ ...body, summary: { ...body.summary, provenance } });

/**
 * A name's REAL provenance, off the captured `/api/positions?closed=true` payload. Read rather
 * than rebuilt, so a recapture propagates instead of being maintained by hand against a second
 * copy of the same four fields — which is what it is for: putting one name's true object on
 * ANOTHER name's payload, the shape no capture can supply.
 *
 * Throws rather than returning null: a caller asks for this because it is about to gate a claim
 * the object is the only source of, and a missing one is a fixture that can no longer carry the
 * gate — silence there is how a test goes vacuous.
 */
export function capturedProvenance(ticker) {
  const row = (fixtureFor("/api/positions?closed=true")?.body.positions || [])
    .find((r) => r.ticker === ticker && r.provenance);
  if (!row) throw new Error(`${ticker} no longer carries a provenance object on the wire`);
  return row.provenance;
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
 * The seven pathological rows the fixtures exist to carry, each with the reason it is
 * here. `inventory.spec.js` asserts every one of them, so these are load-bearing checks
 * rather than commentary: the moment a recapture drops one, the suite says so.
 *
 * Every one of these came out of planning, and each of them either broke a measurement
 * or would have. Fixtures that were merely *plausible* would not contain any of them.
 *
 * `scripts/capture_web_fixtures.py` asserts the same seven at capture time, so a
 * recapture cannot quietly drop one. Move a threshold here and move it there, and ADD A
 * ROW IN BOTH — the duplication is what gives these checks their teeth.
 *
 * `fixture` IS ONE FILE OR SEVERAL. Six are a claim about one payload; the spend-trend spread is
 * a claim about two together, because the spread that decides that chart's whole form only exists
 * inside the window a second endpoint defines.
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
  // THE REFUSAL IS TWO ROWS, NOT ONE, and they are the pair this list grew by. ASTREA6B is the
  // only name in the book whose entering units have no recorded cost, so the only page with no
  // bottom line — and the page is reachable only through the Holdings row, because
  // `SecurityDetail` is component state with one caller. Each half is useless without the other,
  // which is exactly why they are separate rows: two rows name WHICH half went missing, where one
  // row could only say the state is gone.
  {
    name: "the refusal's own payload — a Net that is absent, not zero",
    // Without this, the only page that says "the book does not know" has no payload behind it,
    // and every gate on the refusal layout renders a 404 instead.
    fixture: "holding-astrea6b.json",
    holds: (body) => {
      const s = body.summary ?? {};
      return { ok: s.net_verdict === "refuse" && s.net_pl_sgd == null,
               saw: `summary says net_verdict=${JSON.stringify(s.net_verdict)}, `
                  + `net_pl_sgd=${JSON.stringify(s.net_pl_sgd)}` };
    },
  },
  {
    name: "the Holdings row that reaches the refusal",
    // Without this, the payload above is a fixture no test can open: there is no deep link to a
    // detail page, so the only route to one is clicking a row in this list. A row that lost its
    // refusal — or a recapture where `is_leg` stopped keeping it — would take the whole refusal
    // render state with it, in silence.
    fixture: "positions-closed.json",
    holds: (body) => {
      const rows = (body.positions ?? []).filter((r) => r.net_verdict === "refuse");
      return { ok: rows.length > 0,
               saw: `${rows.length} refusing row(s) of ${(body.positions ?? []).length}`
                  + `${rows.length ? ": " + rows.map((r) => r.ticker).join(", ") : ""}` };
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
