const base = "";
// Session lives in an HttpOnly cookie; include it on every request. A 401 means the
// session expired or was revoked -> tell the AuthGate to drop back to the login screen.
const CREDS = { credentials: "include" };
function on401(r) {
  if (r.status === 401) window.dispatchEvent(new Event("auth-expired"));
  return r;
}
export async function get(path) {
  const r = on401(await fetch(base + path, CREDS));
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
async function send(method, path, body) {
  const opts = { method, ...CREDS };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const r = on401(await fetch(base + path, opts));
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail || ""; } catch {}
    throw new Error(detail || path + " " + r.status);
  }
  return r.json();
}
export const post = (path, body) => send("POST", path, body);
export const put = (path, body) => send("PUT", path, body);
export const patch = (path, body) => send("PATCH", path, body);
export async function del(path) {
  const r = on401(await fetch(base + path, { method: "DELETE", ...CREDS }));
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
export const fmt = (n, d = 0) =>
  n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
export const pct = (n) => (n == null ? "—" : (n * 100).toFixed(1) + "%");
const SYM = {
  SGD: "S$", USD: "US$", EUR: "€", GBP: "£", HKD: "HK$",
  JPY: "¥", CNY: "CN¥", AUD: "A$", CAD: "C$", NZD: "NZ$", CHF: "CHF ", MYR: "RM",
};
export const sgd = (n) => "S$" + fmt(n, 0);
// value + currency code → symbol-prefixed, e.g. "S$1,234", "US$1,234.56", "€99". Unknown ccy → "CCY x".
export const money = (n, ccy, d = 2) =>
  n == null ? "—" : (SYM[ccy] || (ccy ? ccy + " " : "")) + fmt(n, d);
export const cls = (n) => (n == null ? "" : n >= 0 ? "pos" : "neg");
/**
 * A signed reading — `+8,736`, `−1,174`, `+6.9` — for the captions that state in words what a
 * chart's pixels cannot carry.
 *
 * U+2212 MINUS RATHER THAN A HYPHEN, because these sit in columns of digits and a hyphen is a
 * different width from a plus. `cls` above is the other half of the same job and deliberately
 * stays separate: that one colours a gain or a loss, and a spending caption has no such reading —
 * spending more is not a loss.
 *
 * Here beside `fmt` rather than in a chart, because three surfaces need it and the test suite
 * needs the fourth: `readings.spec.js` imports this rather than restating it, and a restated
 * formatter is how a gate ends up asserting its own rounding instead of the app's.
 */
export const signed = (n, d = 0) => (n < 0 ? "−" : "+") + fmt(Math.abs(n), d);
/**
 * The date formats the two time-series charts read in, declared once.
 *
 * en-US AND UTC, both load-bearing. `MMM D` in en-GB renders `21 Jun` rather than `Jun 21`, which
 * collides differently and reads as a different convention from the rest of the app; and every
 * date on these wires is a plain `YYYY-MM-DD` with no zone, so parsing it into the reader's local
 * day would shift a snapshot captured on the 1st onto the 31st for anyone west of Greenwich.
 *
 * `dayLabel` is an axis tick and the shortest thing that still identifies a snapshot; `monthLabel`
 * and `monthYearLabel` are the two branches of the composition chart's dense tick rule, where the
 * year rides on January alone; `fullDateLabel` is what a tooltip and a footnote say, since neither
 * is competing for width.
 */
const UTC_PARTS = { timeZone: "UTC" };
const DATE_FMT = {
  day: new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", ...UTC_PARTS }),
  month: new Intl.DateTimeFormat("en-US", { month: "short", ...UTC_PARTS }),
  monthYear: new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", ...UTC_PARTS }),
  full: new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric", ...UTC_PARTS }),
};
export const dayLabel = (t) => DATE_FMT.day.format(t);
export const monthLabel = (t) => DATE_FMT.month.format(t);
export const monthYearLabel = (t) => DATE_FMT.monthYear.format(t);
export const fullDateLabel = (t) => DATE_FMT.full.format(t);
/** A `YYYY-MM-DD` on the wire as epoch ms, read as UTC — never as the reader's local midnight. */
export const utcDay = (iso) => Date.parse(iso + "T00:00:00Z");
/** A `YYYY-MM` bucket as epoch ms at the start of that month, UTC, for the same reason. */
export const utcMonth = (ym) => Date.UTC(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)) - 1, 1);
// Unclassified spend — `category IS NULL` — as the app names it. Beside the formatters
// because that is what it is: the null is the value, this is how the value reads.
//
// `portfolio/spending.py` carries the same word for the same rows, and that is not a
// duplicate to collapse. Two endpoints hand the null over differently and only one of them
// can defer: `summary()` returns `category` as a *value* on a record, so it arrives here
// null and is named here; `trends()`' group strings are the *keys* of every series row, fed
// straight to `<Bar dataKey>`, and JSON has no null key — so that one must be named before
// it is serialized or it becomes the string "null". Change the word and change it in both.
export const catName = (c) => c || "Uncategorized";
/**
 * A `YYYY-MM` bucket as prose, and as a label with ~40px to live in.
 *
 * Beside the money formatters because that is what these are: the compute layer emits months
 * as `to_char(txn_date,'YYYY-MM')` strings and every surface that prints one has to turn it
 * into a word. Here rather than in the one chart that draws them so the suite can assert a
 * rendered label against the app's own formatter instead of restating the month names — a
 * restated table of abbreviations is a second formatter, free to disagree with the first, and
 * a spec file cannot import a module that imports React.
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const monthName = (ym) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;
export const monthTick = (ym) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} '${ym.slice(2, 4)}`;
