# Workflow Plan — Spending Menu Visibility Gate

**Unit**: spending-visibility
**Stage**: INCEPTION — Workflow Planning
**Date**: 2026-07-10

---

## 1. Scope & Impact Analysis

**Transformation scope**: Single-component application change. No architectural transformation, no infrastructure change, no deployment-model change, no schema change, no migration, no new dependency.

**Risk level**: **Medium.** The diff is small, but it is the project's first authorization rule beyond the binary allowlist, and a mistake fails *open* — silently exposing every spending transaction to any allowlisted user. Mitigated by fail-closed defaults (FR-6) and server-side enforcement (FR-2).

**Cross-package impact**

| Package | Change | Why |
|---|---|---|
| `portfolio/config.py` | `spending_emails` field + `spending_email_set` property | FR-3 |
| `server/auth.py` | `can_view_spending(user)` helper; `features` in `/api/auth/me` | FR-2, FR-4, FR-5, FR-7 |
| `server/main.py` | One clause in the `auth_gate` middleware | FR-2, FR-6 |
| `web/src/auth.jsx` | Carry `features` through `AuthGate` → `useAuth()` context | FR-4 |
| `web/src/App.jsx` | Conditional nav item + guard the section render | FR-1, FR-9 |
| `tests/test_spending_access.py` | New | NFR-4 |
| `.env.example`, `DEPLOY.md` | Document `SPENDING_EMAILS` | FR-3, operability |

**Components NOT affected**: the nine spending route handlers themselves (gated centrally, not individually — preserving the existing single-chokepoint design); `ingestion/`, `portfolio/recurring.py`, all DB models; every non-spending route.

---

## 2. Stage Decisions

### 🔵 INCEPTION PHASE

| Stage | Decision | Rationale |
|---|---|---|
| Workspace Detection | ✅ **DONE** | Brownfield, existing `aidlc-state.md`, resumed |
| Reverse Engineering | ⏭️ **SKIP** | Artifacts exist per `aidlc-state.md` ("Targeted only"); the auth + spending subsystems were mapped directly this session |
| Requirements Analysis | ✅ **DONE** | Standard depth; 8 questions answered; `spending-visibility-requirements.md` |
| User Stories | ⏭️ **SKIP** | Single user, single persona, one binary capability. Acceptance criteria in requirements §6 already carry the scenarios; stories would add ceremony, not clarity |
| Workflow Planning | ✅ **THIS DOCUMENT** | Always executes |
| Application Design | ⏭️ **SKIP** | No new component or service. One helper function added to an existing module, inside an existing chokepoint |
| Units Generation | ⏭️ **SKIP** | Single cohesive unit; nothing to decompose |

### 🟢 CONSTRUCTION PHASE

| Stage | Decision | Rationale |
|---|---|---|
| Functional Design | ⏭️ **SKIP** | No new data model, no business logic. The design is fully specified by requirements §3 and the impact table above |
| NFR Requirements | ⏭️ **SKIP** | Tech stack fixed; NFRs already captured in requirements §4 |
| NFR Design | ⏭️ **SKIP** | NFR Requirements skipped |
| Infrastructure Design | ⏭️ **SKIP** | One env var in the existing Vercel project. No new cloud resource |
| **Code Generation** | ✅ **EXECUTE** | Always. Part 1 plan → approval → Part 2 generate |
| **Build and Test** | ✅ **EXECUTE** | Always. Backend tests + web build + manual verification of the 7 acceptance criteria |

**Net: 2 construction stages execute, 4 skip.**

---

## 3. Execution Sequence

```
Requirements (done)
      |
      v
Workflow Planning (this doc)  ---- approval gate ----
      |
      v
Code Generation
   Part 1: plan with checkboxes ---- approval gate ----
   Part 2: generate
      |
      +--> portfolio/config.py        (spending_emails + spending_email_set)
      +--> server/auth.py             (can_view_spending, features_for, /api/auth/me)
      +--> server/main.py             (auth_gate clause -> 403)
      +--> web/src/auth.jsx           (thread features through context)
      +--> web/src/App.jsx            (conditional nav + section guard)
      +--> tests/test_spending_access.py
      +--> .env.example, DEPLOY.md
      |
      v
Build and Test
      |
      +--> pytest tests/ (new tests pass; 6 pre-existing test_auth failures unchanged)
      +--> npm run build (web)
      +--> verify all 7 acceptance criteria, incl. a live 403 on /api/spending/*
```

---

## 4. Order of Implementation (server before client)

The server-side gate lands **first and independently**. If the frontend change were written first, or if the two were coupled, there would be a window in which the menu is hidden while the API is still open — the exact false-security posture SECURITY-08 warns about. The gate is the feature; the menu is cosmetic.

---

## 5. Security Baseline Compliance (extension ENABLED)

Carried forward from requirements §5. **Applicable**: SECURITY-08 (governs this unit), SECURITY-15, SECURITY-06, SECURITY-03. **N/A with rationale**: SECURITY-01, 02, 04, 05, 07, 09, 10, 12, 13, 14 — no persistence, network, header, input, infrastructure, dependency, integrity, or alerting surface is touched.

**Blocking findings: none.**

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Change fails open, exposing spending data | Fail-closed default (FR-6); explicit test that unset config denies *everyone* |
| Prefix match too broad/narrow (`/api/spending-foo`) | Match `path == "/api/spending" or path.startswith("/api/spending/")`, not a bare `startswith("/api/spending")` |
| Local `.env` (`DEV_AUTH_BYPASS=true`) leaks into new tests, as it already does for 6 existing ones | New tests set `settings.dev_auth_bypass` explicitly (NFR-4) |
| `SPENDING_EMAILS` forgotten on the Vercel deploy → feature silently vanishes | Documented in `DEPLOY.md` + `.env.example`; this is the intended fail-closed trade-off, accepted in Q6 |
| Session cookie carries a stale capability | Capability is recomputed per-request from env, never read from the JWT (NFR-1) |
