const base = "";
export async function get(path) {
  const r = await fetch(base + path);
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
export const fmt = (n, d = 0) =>
  n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
export const pct = (n) => (n == null ? "—" : (n * 100).toFixed(1) + "%");
export const sgd = (n) => "S$" + fmt(n, 0);
export const cls = (n) => (n == null ? "" : n >= 0 ? "pos" : "neg");
