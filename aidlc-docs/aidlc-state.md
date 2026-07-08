# AI-DLC State Tracking

## Project Information
- **Project Type**: Brownfield
- **Start Date**: 2026-06-21T00:00:00Z
- **Current Stage**: INCEPTION - Requirements Analysis

## Workspace State
- **Existing Code**: Yes (Python / FastAPI backend, web frontend, SQLAlchemy + Alembic + Postgres)
- **Programming Languages**: Python, JavaScript/HTML (web/)
- **Build System**: uv (pyproject.toml), alembic migrations
- **Project Structure**: Monolith — `portfolio/` (domain), `api/` (FastAPI), `ingestion/`, `web/` (UI)
- **Reverse Engineering Needed**: Targeted only (relevant subsystems already mapped; full RE deferred by scope)
- **Workspace Root**: /Users/selwynyeow/personal/portofolio

## Code Location Rules
- **Application Code**: Workspace root (NEVER in aidlc-docs/)
- **Documentation**: aidlc-docs/ only

## Feature
Net-worth snapshot: maintain manual assets & liabilities (cash accounts, CPF, HDB, home loan + accrued interest), combine with live investment portfolio value, and answer: total assets, total liabilities, liquid assets, net worth, net worth excl. housing, net worth excl. housing & CPF.

## Extension Configuration
| Extension | Enabled | Decided At |
|---|---|---|
| Security Baseline | Yes | Requirements Analysis (auth unit) |
| Property-Based Testing | No | Requirements Analysis |

## Execution Plan Summary
- **Unit**: networth (single)
- **Execute**: Functional Design, Code Generation, Build and Test
- **Skip**: User Stories, Application Design, Units Generation, NFR Requirements, NFR Design, Infrastructure Design

## Stage Progress
### 🔵 INCEPTION PHASE
- [x] Workspace Detection
- [x] Reverse Engineering (SKIPPED)
- [x] Requirements Analysis
- [x] User Stories (SKIPPED)
- [x] Workflow Planning
- [ ] Application Design (SKIP)
- [ ] Units Generation (SKIP)

### 🟢 CONSTRUCTION PHASE
- [x] Functional Design (EXECUTE)
- [ ] NFR Requirements (SKIP)
- [ ] NFR Design (SKIP)
- [ ] Infrastructure Design (SKIP)
- [x] Code Generation (EXECUTE)
- [x] Build and Test (EXECUTE)

## Units
| Unit | Status |
|---|---|
| networth | Complete (5 snapshots; latest DBS ingest Apr/May/Jun 2026 -> id=3/4/5 month-end dated; scripts/snapshot_from_statements.py) |
| auth | Complete (24 tests pass; web build OK) |
| spending-tracker | Code Generation + Verify complete — see construction/spending-tracker/code/summary.md |

## Current Status
- **Current Stage**: spending-tracker unit — built & verified (`make spending` end-to-end,
  idempotent; 793 spend rows / S$141.7k / 17mo; invariant: 0 cc-payments counted as spend).
- **Open items (need user input)**: TMLS recurring GIRO biller, helper-salary PayNows,
  JB (MY) spend, DBS-card POS codes — currently Uncategorized (~35% of spend by value).
- **Next Stage**: refine `data/spending/categories.yaml` for the long tail; Deploy (DEPLOY.md).
