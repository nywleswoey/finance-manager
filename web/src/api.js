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
