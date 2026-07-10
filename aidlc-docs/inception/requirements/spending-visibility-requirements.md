# Requirements — Spending Menu Visibility Gate

**Unit**: spending-visibility
**Stage**: INCEPTION — Requirements Analysis (COMPLETE)
**Date**: 2026-07-10
**Depth**: Standard

---

## 1. Intent Analysis

| Field | Assessment |
|---|---|
| **User request** | "using ai-dlc, i want spendings menu option to only appear for 1 specific google account" |
| **Request type** | Enhancement (authorization) |
| **Scope estimate** | Multiple Components |
| **Complexity estimate** | Moderate — small diff, security-sensitive |
| **Requirements depth** | Standard |

### Answers received (spending-visibility-questions.md, all A)

| # | Question | Answer |
|---|---|---|
| 1 | Target account | `sgfjords@gmail.com` |
| 2 | Unauthorized API response | `403 Forbidden`, generic message |
| 3 | Config mechanism | New `SPENDING_EMAILS` env var |
| 4 | Frontend discovery | Extend `GET /api/auth/me` with a `features` list |
| 5 | `DEV_AUTH_BYPASS` dev user | Authorized (local dev unaffected) |
| 6 | Var unset/empty | Fail closed |
| 7 | CLI/ingestion path | Web app only |
| 8 | Extension config | Security Baseline **Yes**, PBT **No** |

---

## 2. Context

Access is currently **binary**: an email is in `ALLOWED_EMAILS` or it is locked out. The codebase has no roles, no permissions, and no per-user feature flags. Every allowlisted user sees Portfolio, Net Worth, and Spending alike. This unit introduces the first per-user capability.

Load-bearing existing code:

| Concern | Location |
|---|---|
| Authorization chokepoint | `user_from_request` — `server/auth.py:75-94` |
| Deny-by-default route gate | `auth_gate` middleware — `server/main.py:53-64` |
| Public paths (no session) | `_PUBLIC_PATHS` — `server/main.py:37` |
| Allowlist parsing | `allowed_email_set` — `portfolio/config.py:39-41` |
| Bypass hard guard | `auth_bypass_active` — `portfolio/config.py:29-37` |
| Nine spending routes | `server/main.py:506-646` |
| Menu item | `web/src/App.jsx:59` |
| Spending sub-tabs | `SPEND_TABS` — `web/src/App.jsx:24-28` |
| Frontend identity | `AuthGate` / `check()` — `web/src/auth.jsx:64-117` |
| `/api/auth/me` | `server/auth.py:158-163` |

The session JWT stores the **email** in the `sub` claim (`mint_session`, `auth.py:62-65`) — identity is the verified Google email, not the Google `sub`.

---

## 3. Functional Requirements

**FR-1 — Menu visibility.** The `Spending` nav item (`App.jsx:59`) renders only when the signed-in user holds the `spending` capability. Unauthorized users see Portfolio and Net Worth only.

**FR-2 — Server-side enforcement (MANDATORY).** Every route matching `/api/spending` or `/api/spending/*` returns `403 Forbidden` with a generic body when the caller is authenticated but lacks the `spending` capability. This is the actual access control; FR-1 is presentation only.

**FR-3 — Configuration.** A new env var `SPENDING_EMAILS` holds a comma-separated, case-insensitive email list, parsed exactly as `allowed_emails` is today (`config.py:39-41`). No schema change. No migration.

**FR-4 — Capability discovery.** `GET /api/auth/me` returns `{email, name, features}` where `features` is a list of capability strings, containing `"spending"` when authorized. The frontend never hardcodes an email address.

**FR-5 — Dev bypass.** When `auth_bypass_active` is true, the synthetic `dev@localhost` user holds every capability, so local development is unaffected. This flag is already force-disabled on Vercel (`config.py:29-37`), so it cannot unlock a deployed environment.

**FR-6 — Fail closed.** When `SPENDING_EMAILS` is unset or empty, **nobody** holds the capability: the menu item is hidden for all and every `/api/spending/*` call returns 403.

**FR-7 — Precedence (resolves the FR-5 / FR-6 interaction).** The bypass check runs **before** the fail-closed check. So on a local machine with `DEV_AUTH_BYPASS=true` and `SPENDING_EMAILS` unset, the dev user still sees Spending; in any deployed environment the bypass is inert and FR-6 governs. These two requirements do not conflict — they are ordered.

**FR-8 — Scope boundary.** The CLI and ingestion path (`make spending`, `ingestion/load_cash.py`) are unchanged. This unit gates *visibility of the web feature*, not *ownership of the data*. `cash_txn` and `recurring_spend` remain global tables with no owner column.

**FR-9 — Direct-navigation safety.** If an unauthorized user reaches the Spending section by any means other than the menu (stale state, manual manipulation), the UI must not render the spending tabs, and the underlying API calls would 403 regardless (FR-2).

---

## 4. Non-Functional Requirements

**NFR-1 — Revocability.** Removing an email from `SPENDING_EMAILS` revokes the capability on the next request, with no redeploy and no session invalidation. This mirrors how `user_from_request` re-checks `allowed_email_set` on every request rather than trusting the cookie's claims (`auth.py:92`).

**NFR-2 — Single source of truth.** The authorization rule lives in exactly one function, server-side. The frontend consumes its output and never re-implements it.

**NFR-3 — No new dependencies, no migration, no schema change.**

**NFR-4 — Testability.** New tests must set `settings.dev_auth_bypass` explicitly rather than inheriting it from the local `.env`, which is the documented cause of the 6 pre-existing `tests/test_auth.py` failures.

---

## 5. Security Baseline Compliance (extension ENABLED — blocking)

| Rule | Status | Rationale |
|---|---|---|
| **SECURITY-08** Application-Level Access Control | **Applicable — governs this unit** | Function-level authorization enforced server-side in the `auth_gate` middleware. Client-side hiding (FR-1) is explicitly *not* the control. Deny-by-default preserved. No object-level/IDOR surface added: no new route takes a resource ID. |
| **SECURITY-15** Exception Handling / Fail-Safe Defaults | **Applicable** | FR-6: unset config denies. The capability check returns `False` on any missing/malformed user or empty config — it never throws its way into an open state. |
| **SECURITY-06** Least Privilege | **Applicable** | The capability is a specific named permission (`spending`) scoped to a specific identity set, not a wildcard. Read and write spending routes are gated identically because both expose the same private data. |
| **SECURITY-03** Application-Level Logging | **Applicable** | A denied spending request logs at WARNING with the request path and no email, because SECURITY-03 forbids PII in log output. *Observation:* existing code at `auth.py:150` and `auth.py:155` already logs `email=%s` on login events — a pre-existing deviation, out of scope for this unit, flagged here rather than silently copied. |
| **SECURITY-05** Input Validation | **N/A** | No new API parameter, body, or query field is introduced. |
| **SECURITY-12** Authentication / Credential Management | **N/A** | No change to token minting, verification, TTL, or cookie flags. |
| **SECURITY-04** HTTP Security Headers | **N/A** | No change to `_CSP` or the header middleware. |
| **SECURITY-01/02/07/09/10/13/14** | **N/A** | No persistence store, network intermediary, infrastructure, dependency, integrity, or alerting surface is touched. |

**Blocking findings: none.**

---

## 6. Acceptance Criteria

1. Signed in as `sgfjords@gmail.com` → Spending menu item renders; all nine `/api/spending/*` routes return 200.
2. Signed in as any other allowlisted email → menu item absent; every `/api/spending/*` route returns 403 with a generic body.
3. `SPENDING_EMAILS` unset → menu absent and 403 for **every** user, including the one in `ALLOWED_EMAILS`.
4. `DEV_AUTH_BYPASS=true` locally → `dev@localhost` sees Spending regardless of `SPENDING_EMAILS`.
5. `GET /api/auth/me` returns `features: ["spending"]` for the authorized account and `features: []` otherwise.
6. Non-spending routes (`/api/overview`, `/api/networth/*`, `/api/return`) are unaffected for every allowlisted user.
7. The 6 pre-existing `tests/test_auth.py` failures neither worsen nor are masked; new tests pass independently of the local `.env`.

---

## 7. Summary

Add one env var, one server-side capability function, one middleware clause, one API field, and one frontend conditional. The menu hiding is cosmetic; the 403 is the security control. Fail closed when unconfigured. No database change.
