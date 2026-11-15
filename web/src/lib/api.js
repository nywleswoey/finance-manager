/**
 * The one HTTP client. Every call sends the session cookie; a 401 tells the AuthGate to drop
 * back to the login screen. Formatters live next door in `lib/format.js`.
 */
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
