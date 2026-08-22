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
 * A signed magnitude, with the typographic minus this app's copy uses rather than a hyphen.
 *
 * Beside `fmt` because it is the same job — how a number reads — and in ONE place because the
 * two charts that print deltas want different precision from the same idea: the composition's
 * per-band chips are whole dollars and its net-worth line is one decimal of a percent, while a
 * spend panel's caption is whole percent. Two local copies under one name, differing only in a
 * digit count, is how a reader comes to believe they are the same function.
 */
export const signed = (n, d = 0) => (n < 0 ? "\u2212" : "+") + fmt(Math.abs(n), d);
export const signedPct = (n, d = 1) => (n < 0 ? "\u2212" : "+") + fmt(Math.abs(n) * 100, d) + "%";

/**
 * How a date reads on a chart — en-US and UTC, both pinned, both deliberately.
 *
 * EN-US BECAUSE THE ORDER IS THE DECISION. `en-GB` renders "21 Jun" where these axes and
 * captions want "Jun 21", and the browser's own locale is whatever the reader's machine says —
 * so the format is pinned rather than inherited.
 *
 * UTC FOR A STRONGER REASON. A snapshot date and a spend month are *dates*, not instants.
 * Parsing "2026-06-21" and formatting it in a zone west of Greenwich renders June 20 — a
 * measurement silently attributed to the wrong day.
 *
 * Here rather than in either chart because both charts make the same two choices, and a second
 * copy is free to drift from the first: the `Intl` options are the claim, so they get one home.
 * Every one of these takes epoch milliseconds; a caller holding an ISO string parses it once.
 */
const at = (opts) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", ...opts });
const MONTH_DAY = at({ month: "short", day: "numeric" });
const MONTH_SHORT = at({ month: "short" });
const MONTH_YEAR = at({ month: "short", year: "numeric" });
const DAY_MONTH_YEAR = at({ month: "short", day: "numeric", year: "numeric" });
export const monthDay = (t) => MONTH_DAY.format(t);          // Jun 21
export const monthShort = (t) => MONTH_SHORT.format(t);      // Jun
export const monthYear = (t) => MONTH_YEAR.format(t);        // Jun 2026
export const dayMonthYear = (t) => DAY_MONTH_YEAR.format(t); // Aug 21, 2025


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
