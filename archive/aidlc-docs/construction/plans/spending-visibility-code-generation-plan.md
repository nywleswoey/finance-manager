# Code Generation Plan — Spending Menu Visibility Gate

**Unit**: spending-visibility
**Stage**: CONSTRUCTION — Code Generation (Part 1: Planning)
**Date**: 2026-07-10

Server first, client last. The 403 is the control; the hidden menu is cosmetic.

---

## Findings that shrink the plan

Two things I verified while reading the code, which change the scope from what the workflow plan assumed:

1. **`web/src/auth.jsx` needs no change.** `check()` does `setUser(await r.json())` (`auth.jsx:73`), so whatever `/api/auth/me` returns lands in the context verbatim. Adding `features` server-side makes `user.features` appear in `useAuth()` for free.
2. **The 6 pre-existing `test_auth.py` failures have a one-line cause.** The autouse `_cfg` fixture (`test_auth.py:14-21`) pins four settings but never pins `dev_auth_bypass`, so the local `.env` (`DEV_AUTH_BYPASS=true`) leaks in. Fixing it is *adjacent*, not required. See optional Step 8 — it needs your call, because one of those tests asserts the default and pinning it naively would make that test tautological (masking, not fixing).

---

## Step 1 — `portfolio/config.py`: the config surface

- [x] Add field `spending_emails: str = ""` beside `allowed_emails` (`config.py:24`), commented as fail-closed when empty
- [x] Add property `spending_email_set` mirroring `allowed_email_set` (`config.py:39-41`) — same strip/lower/comma parsing

```python
spending_emails: str = ""            # comma-separated; empty => nobody (fail closed)

@property
def spending_email_set(self) -> set[str]:
    return {e.strip().lower() for e in self.spending_emails.split(",") if e.strip()}
```

**Satisfies**: FR-3, FR-6.

---

## Step 2 — `server/auth.py`: the single authorization rule

- [x] Add module constant `FEATURE_SPENDING = "spending"`
- [x] Add `can_view_spending(user: dict | None) -> bool`
- [x] Add `features_for(user: dict | None) -> list[str]`

```python
FEATURE_SPENDING = "spending"


def can_view_spending(user: dict | None) -> bool:
    """Whether this principal may see the Spending feature.

    Recomputed from env on every request — never read from the session cookie — so removing an
    email from SPENDING_EMAILS revokes access immediately, with no redeploy and no re-login
    (same contract as the allowlist re-check in user_from_request).

    Fails closed: no user, no email, or an empty SPENDING_EMAILS all deny (SECURITY-15).
    The dev bypass is checked FIRST (FR-7) and is already force-off on Vercel.
    """
    if settings.auth_bypass_active:
        return True
    if not user:
        return False
    return (user.get("sub") or "").lower() in settings.spending_email_set


def features_for(user: dict | None) -> list[str]:
    """Capability list handed to the frontend. The client renders from this; it never
    re-implements the rule and never sees the authorized address."""
    return [FEATURE_SPENDING] if can_view_spending(user) else []
```

Note: the session JWT stores the **email** in `sub` (`mint_session`, `auth.py:62-65`) — not the Google `sub`.

- [x] Extend `GET /api/auth/me` (`auth.py:158-163`) to return `features`

```python
return {"email": user["sub"], "name": user.get("name"), "features": features_for(user)}
```

**Satisfies**: FR-2 (rule), FR-4, FR-5, FR-6, FR-7, NFR-1, NFR-2.

---

## Step 3 — `server/main.py`: enforcement in the existing chokepoint

- [x] Add the prefix predicate above the middleware

```python
def _is_spending(path: str) -> bool:
    # exact-or-child only: a bare startswith would also match a future "/api/spending-export"
    return path == "/api/spending" or path.startswith("/api/spending/")
```

- [x] Add one clause to `auth_gate` (`main.py:53-64`), immediately after the `if not user` check

```python
if _is_spending(path) and not auth.can_view_spending(user):
    log.warning("spending denied path=%s", path)   # no email: SECURITY-03 forbids PII in logs
    return JSONResponse({"detail": "forbidden"}, status_code=403)
```

Placement matters: it runs *after* authentication (so an anonymous caller still gets 401, not 403, and we don't leak feature existence to strangers) and *before* `call_next` (so no handler and no DB query ever executes for a denied caller).

All nine spending routes are covered by this one clause. None of the route handlers change.

**Satisfies**: FR-2, FR-6, FR-9, SECURITY-08, SECURITY-03, SECURITY-15.

---

## Step 4 — `web/src/App.jsx`: presentation only

- [x] Derive the capability from context: `const canSpend = (user?.features || []).includes("spending");`
- [x] Render the nav item conditionally: `{canSpend && navItem("Spending", "nav-spending")}`
- [x] Guard the section render so stale state can't blank the page:

```jsx
const activeSection = section === "Spending" && !canSpend ? "Portfolio" : section;
```
then switch the three `section === …` comparisons to `activeSection`, and pass `activeSection` to `navItem` for the `on` highlight.

Without this, a user who loses the capability mid-session (env edited, `check()` re-runs) would sit on an empty `<div className="main">`. With it, they fall back to Portfolio. Either way the API returns 403, so no data leaks — this is purely so the UI doesn't look broken.

**Satisfies**: FR-1, FR-9. Explicitly **not** a security control.

- [x] `web/src/auth.jsx` — **no change** (see Findings)

---

## Step 5 — `tests/test_spending_access.py` (new)

- [x] Autouse fixture pinning `session_secret`, `google_client_id`, `allowed_emails`, `cookie_secure`, **and `dev_auth_bypass = False`** (NFR-4 — do not inherit the local `.env`)
- [x] Unit tests on `can_view_spending` / `features_for`, no HTTP:
  - authorized email → `True`, `["spending"]`
  - allowlisted-but-not-spending email → `False`, `[]`
  - `SPENDING_EMAILS` empty → `False` **even for the allowlisted user** (fail closed, AC-3)
  - `None` user → `False`
  - case-insensitive match (`Owner@Gmail.com` vs `owner@gmail.com`)
  - `auth_bypass_active` true → `True` regardless of empty `SPENDING_EMAILS` (FR-7 precedence)
- [x] HTTP tests through the middleware, probing `/api/spending/__probe__` (a path that matches the gate but has no route, so a permitted caller falls through to **404** and a denied caller is stopped at **403** — no DB, no handler):
  - no session → `401` (authentication precedes authorization; existence not leaked)
  - session for a non-spending allowlisted email → `403`
  - session for the authorized email → `404` (gate passed)
  - `SPENDING_EMAILS` empty + authorized session → `403`
- [x] Prefix-boundary test: `/api/spending-export` must **not** be caught by `_is_spending` (guards the risk logged in the workflow plan)
- [x] `/api/auth/me` returns `features: ["spending"]` for the authorized email and `[]` otherwise

---

## Step 6 — `.env.example`

- [x] Document `SPENDING_EMAILS` under the auth block, stating the fail-closed default

```
# comma-separated list of emails allowed to see the Spending section (subset of ALLOWED_EMAILS).
# Empty or unset => nobody sees it and /api/spending/* returns 403 (fail closed).
SPENDING_EMAILS=you@gmail.com
```

---

## Step 7 — `DEPLOY.md`

- [x] Add `SPENDING_EMAILS` to the Vercel env-var table (`DEPLOY.md:29-37`)
- [x] One line warning that omitting it hides Spending from everyone — the intended fail-closed trade-off you accepted in Q6

---

## Step 8 — OPTIONAL, needs your decision: repair the 6 pre-existing `test_auth.py` failures

Out of scope for this unit; I will **not** do it unless you say so. Recording the correct shape so the decision is informed:

- `_cfg` (`test_auth.py:14-21`) should pin `settings.dev_auth_bypass = False`, which repairs 5 of the 6.
- The 6th, `test_bypass_off_by_default` (`test_auth.py:148`), asserts `settings.dev_auth_bypass is False` on the *loaded instance*. Pinning that in the fixture would make the assertion vacuous. It should instead assert the **class default** — `Settings.model_fields["dev_auth_bypass"].default is False` — which is what "off by default" actually means and is what the test's name claims.

Doing this makes the suite green for the right reason. Leaving it keeps this unit's diff honest. Your call.

- [ ] (only if approved) Repair `_cfg` and `test_bypass_off_by_default`

---

## Verification (feeds Build & Test)

- [x] `PYTHONPATH=. .venv/bin/pytest tests/test_spending_access.py -v` — all pass
- [x] `PYTHONPATH=. .venv/bin/pytest tests/ -q` — no new failures; the 6 `test_auth` failures unchanged (unless Step 8 approved)
- [x] `npm --prefix web run build` — clean
- [x] Live check with `DEV_AUTH_BYPASS=false`: authorized session → 200 on `/api/spending/summary`; other allowlisted session → 403; `SPENDING_EMAILS` unset → 403 for both
- [x] `curl /api/auth/me` shows the right `features` for each session
- [x] Confirm `/api/overview`, `/api/networth/*`, `/api/return` still 200 for a non-spending user (AC-6)

---

## Security Baseline Compliance (extension ENABLED)

| Rule | Status | Where |
|---|---|---|
| SECURITY-08 Access Control | ✅ Compliant | Step 3 — server-side function-level authz in the deny-by-default gate; Step 4 is explicitly not the control; no new resource-ID route, so no IDOR surface |
| SECURITY-15 Fail-Safe Defaults | ✅ Compliant | Steps 1–3 — empty config denies; `can_view_spending` returns `False` on `None`/missing/empty rather than raising |
| SECURITY-06 Least Privilege | ✅ Compliant | Step 2 — a specific named capability scoped to a specific identity set; no wildcard |
| SECURITY-03 Logging | ✅ Compliant | Step 3 — denial logs the path, never the email. (Pre-existing deviation at `auth.py:150,155` noted, not copied, not in scope) |
| SECURITY-05 Input Validation | N/A | No new parameter, body, or query field |
| SECURITY-12 Auth / Credentials | N/A | No change to minting, verification, TTL, cookie flags |
| SECURITY-04 HTTP Headers | N/A | `_CSP` untouched |
| SECURITY-01/02/07/09/10/13/14 | N/A | No persistence, network intermediary, infra, dependency, integrity, or alerting surface touched |

**Blocking findings: none.**

---

## Files touched

| File | Change |
|---|---|
| `portfolio/config.py` | +1 field, +1 property |
| `server/auth.py` | +2 functions, +1 constant, `/api/auth/me` returns `features` |
| `server/main.py` | +1 predicate, +1 middleware clause |
| `web/src/App.jsx` | conditional nav item + section guard |
| `tests/test_spending_access.py` | new |
| `.env.example`, `DEPLOY.md` | document `SPENDING_EMAILS` |
| `web/src/auth.jsx` | **unchanged** |
| the 9 spending route handlers | **unchanged** |
