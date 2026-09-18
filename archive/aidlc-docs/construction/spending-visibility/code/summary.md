# Code Summary — Spending Menu Visibility Gate

**Unit**: spending-visibility
**Stage**: CONSTRUCTION — Code Generation (Part 2) + Build and Test — COMPLETE
**Date**: 2026-07-10

---

## What shipped

The Spending feature is now a **capability**, not something every signed-in user gets. The rule lives in one server-side function; the SPA renders from its output.

| File | Change |
|---|---|
| `portfolio/config.py` | `spending_emails` field + `spending_email_set` property (strip/lower/comma, mirrors `allowed_email_set`) |
| `server/auth.py` | `FEATURE_SPENDING`, `can_view_spending()`, `features_for()`; `/api/auth/me` returns `features` |
| `server/main.py` | `_is_spending()` predicate + one `auth_gate` clause returning `403 {"detail": "forbidden"}` |
| `web/src/App.jsx` | `canSpend` from `user.features`; conditional nav item; `activeSection` fallback |
| `tests/test_spending_access.py` | New — 19 tests |
| `.env.example`, `DEPLOY.md` | Document `SPENDING_EMAILS` and its fail-closed behaviour |
| `web/src/auth.jsx` | **Unchanged** — `setUser(await r.json())` already forwards new fields into context |
| The 9 spending route handlers | **Unchanged** — gated centrally |

## Design decisions

**The 403 is the control; hiding the nav item is cosmetic.** SECURITY-08 forbids relying on client-side hiding. All nine routes are covered by one middleware clause, so a new spending route is gated the day it is added — nobody has to remember a decorator.

**The clause sits after authentication, before `call_next`.** After, so an anonymous caller still receives 401 and we do not advertise the feature's existence to strangers. Before, so a denied caller never reaches a handler or a database query.

**`_is_spending` matches exact-or-child.** A bare `startswith("/api/spending")` would also gate a future `/api/spending-export`. Tested explicitly.

**The capability is recomputed from env on every request**, never read back from the session JWT, so removing an email revokes access on the next request with no redeploy and no re-login. Same contract as the existing allowlist re-check in `user_from_request`.

**Fails closed.** Empty `SPENDING_EMAILS` denies everyone, including accounts in `ALLOWED_EMAILS`. The dev bypass is checked first (FR-7) and is force-disabled on Vercel, so it cannot leak into a deployment.

**The frontend never learns the authorized address.** It receives `features: ["spending"]` or `[]`. Verified: no email appears in the built JS bundle.

## Verification

- `tests/test_spending_access.py` — **19 pass**. Covers the rule (authorized / allowlisted-but-not / empty-config-denies-the-owner-too / `None` user / case-insensitivity / bypass precedence / revocation without re-login), the path predicate (exact-or-child, and that `/api/spending-export` and `/api/spendings` are not swallowed), the middleware (401 anonymous, 403 unauthorized, 404 authorized-through-the-gate on a routeless probe path, 403 when unset), and the `features` list including the no-address-leak assertion.
- Full suite: **108 pass** (was 89). The 6 `tests/test_auth.py` failures are pre-existing and unchanged — caused by the local `.env` setting `DEV_AUTH_BYPASS=true` while their fixture doesn't pin it. Not masked, not touched (see below).
- `npm --prefix web run build` — clean.
- **Live, against real routes and a real database, with `DEV_AUTH_BYPASS=false`:** all 7 acceptance criteria pass. Owner gets 200 on all six read routes; another allowlisted user gets 403 on all six plus `POST /api/spending/recurring`, `DELETE /api/spending/recurring/{id}`, `POST /api/spending/recurring/dismiss`; unset config gives 403 to the owner too; `/api/overview`, `/api/return`, `/api/networth/snapshots` still 200 for the unauthorized user; anonymous gets 401.
- No email in `web/dist/assets/*.js`.

## Security Baseline Compliance (extension ENABLED)

| Rule | Status | Evidence |
|---|---|---|
| SECURITY-08 Access Control | ✅ Compliant | Server-side function-level authz in the deny-by-default gate; client-side hiding explicitly not the control; write routes 403 before body validation; no new resource-ID route, so no IDOR surface |
| SECURITY-15 Fail-Safe Defaults | ✅ Compliant | Empty config denies everyone (tested); `can_view_spending` returns `False` on `None`/missing/empty rather than raising |
| SECURITY-06 Least Privilege | ✅ Compliant | A specific named capability scoped to a specific identity set; no wildcard; read and write gated identically |
| SECURITY-03 Logging | ✅ Compliant | `log.warning("spending denied path=%s", path)` — path only, no PII |
| SECURITY-05, 12, 04 | N/A | No new API parameter; no change to token minting/verification/TTL/cookie flags; `_CSP` untouched |
| SECURITY-01, 02, 07, 09, 10, 13, 14 | N/A | No persistence, network intermediary, infrastructure, dependency, integrity, or alerting surface touched |

**Blocking findings: none.**

## Deferred / known

- **Optional Step 8 not done.** Repairing the 6 pre-existing `test_auth.py` failures needs an explicit decision: pinning `dev_auth_bypass = False` in their `_cfg` fixture fixes 5, but the 6th (`test_bypass_off_by_default`) asserts the loaded instance, so pinning would make it tautological. It should instead assert `Settings.model_fields["dev_auth_bypass"].default is False`. Left untouched rather than silently masked.
- **Pre-existing SECURITY-03 deviation:** `server/auth.py:150` and `:155` log `email=%s` on login events. Flagged, not copied, out of scope for this unit.
- **Operational:** `SPENDING_EMAILS` must be set in the Vercel dashboard (Production **and** Preview) or Spending disappears in prod. That is the intended fail-closed trade-off. Locally, `.env` has `DEV_AUTH_BYPASS=true`, so Spending stays visible regardless.
