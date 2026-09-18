# Requirements Clarification — Spending Menu Visibility Gate

**Unit**: spending-visibility
**Stage**: INCEPTION — Requirements Analysis
**Date**: 2026-07-10

Please answer each question by filling in the `[Answer]:` tag. Reply with the letter (A/B/C…) or use `X` and describe.

---

## Intent Analysis (my reading of your request)

| Field | Assessment |
|---|---|
| **User request** | "using ai-dlc, i want spendings menu option to only appear for 1 specific google account" |
| **Request clarity** | Incomplete — the target account, the enforcement level, and the config mechanism are unspecified |
| **Request type** | Enhancement (authorization) |
| **Scope estimate** | Multiple Components — `portfolio/config.py`, `server/auth.py`, `server/main.py`, `web/src/App.jsx`, `web/src/auth.jsx`, tests, deploy docs |
| **Complexity estimate** | Moderate — small diff, but security-sensitive |
| **Requirements depth** | Standard |

### What exists today

The app is single-tenant with **binary** access: your email is in the `ALLOWED_EMAILS` env var or you are locked out entirely. There are **no roles, permissions, or per-user feature flags** anywhere in the codebase. Once signed in, every allowlisted user sees every section — Portfolio, Net Worth, and Spending.

- Authorization chokepoint: `user_from_request` (`server/auth.py:75-94`)
- Route protection: one deny-by-default middleware, `auth_gate` (`server/main.py:53-64`); no route has its own dependency
- Nine spending routes: `/api/spending/*` (`server/main.py:506-646`)
- The menu item: `{navItem("Spending", "nav-spending")}` (`web/src/App.jsx:59`)
- Frontend identity: `GET /api/auth/me` → `{email, name}`, consumed via `useAuth()` (`web/src/auth.jsx:64-117`)

So this request introduces the codebase's **first per-user capability**. That is the main design decision below.

---

## ⚠️ Security constraint (not a question — a blocking rule)

The **Security Baseline extension is ENABLED** for this project (`aidlc-state.md` → Extension Configuration). Rule **SECURITY-08: Application-Level Access Control** states:

> **Function-level authorization**: Administrative or privileged operations MUST check the caller's role/permissions server-side — **never rely on client-side hiding**.

Hiding the menu item in React does **not** restrict access. Anyone signed in could still call `GET /api/spending/transactions` directly and read every transaction. Therefore the server-side gate on `/api/spending/*` is **mandatory**, not optional. Question 2 exists only to confirm the failure mode you want, not whether to enforce it.

---

## Question 1
Which Google account should see the Spending section?

A) `sgfjords@gmail.com` (the account configured in this environment)
B) A different single account — specify the exact email after the `[Answer]:` tag
C) A small set of accounts, not just one — specify the emails
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 2
When a signed-in but **unauthorized** user calls a `/api/spending/*` endpoint directly (bypassing the hidden menu), what should the server return?

A) `403 Forbidden` with a generic message — honest, and the standard choice
B) `404 Not Found` — additionally conceals that the feature exists
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 3
Where should the authorization list live?

A) A new env var `SPENDING_EMAILS` (comma-separated), mirroring how `ALLOWED_EMAILS` already works — no schema change, no deploy coupling, revocable by editing Vercel env
B) Reuse `ALLOWED_EMAILS` and treat the **first** entry as the privileged owner — no new config, but order-dependent and surprising
C) A database table of per-user permissions — most extensible, biggest change, introduces the first real roles model
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 4
How should the frontend learn whether to render the Spending menu item?

A) Extend `GET /api/auth/me` to return a capability list, e.g. `{email, name, features: ["spending"]}` — the server stays the single source of truth, and the frontend never hardcodes an email
B) Add a separate `GET /api/features` endpoint
C) The frontend compares `user.email` against a hardcoded email in the JS bundle — simplest, but ships the address to every visitor and duplicates the rule
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 5
Local development uses `DEV_AUTH_BYPASS=true`, which short-circuits `user_from_request` and returns the synthetic user `dev@localhost` (`server/auth.py:32,83-84`). Should that dev user see Spending?

A) Yes — the bypass already grants full local access; treat `dev@localhost` as authorized so local dev is unaffected
B) No — the dev user must also be listed in `SPENDING_EMAILS` to see it, keeping local behaviour identical to prod
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 6
If `SPENDING_EMAILS` (or whichever mechanism you pick in Q3) is **unset or empty**, what should happen?

A) Fail closed — nobody sees Spending, and the API returns 403 for everyone. Matches SECURITY-15 ("on error, deny access — never fail open")
B) Fail open — everybody sees Spending, preserving today's behaviour when the var is absent
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 7
The Spending data itself (`cash_txn`, `recurring_spend`) is currently global — not owned by any user. This change gates *visibility*, not *ownership*. Do you also want the ingestion/scripts path (`make spending`, `ingestion/load_cash.py`) restricted, or is gating the web app enough?

A) Web app only — CLI scripts run on your own machine, so they need no gate
B) Also add a check to the CLI/ingestion path
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 8 — Extension Configuration (confirm or change)
`aidlc-state.md` already records these from an earlier unit. Confirm they still hold for this unit.

| Extension | Currently |
|---|---|
| Security Baseline | **Yes** — enforced as blocking constraints |
| Property-Based Testing | **No** — skipped |

A) Confirm both — keep Security Baseline enforced, keep PBT skipped
B) Change — describe the change after the `[Answer]:` tag
X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## My recommendation (for reference — you still choose)

**A, A, A, A, A, A, A, A**: gate on a new `SPENDING_EMAILS` env var; enforce server-side on `/api/spending/*` returning 403; expose a `features` list from `/api/auth/me`; let `dev@localhost` through locally; fail closed when unset; leave the CLI alone.

That keeps the blast radius to roughly: one config property, one helper in `server/auth.py`, one middleware clause in `server/main.py`, one conditional in `App.jsx`, and tests.
