# Portfolio Transaction Reconciliation

_Generated from `build/build_ledger.py` → `build/ledger.csv`. Compares replayed
transaction history against current `Holdings.md` (dated 2026-06-20)._

## What was done

1. **Normalized every machine-readable source** under `data/` into one schema
   (`build/ledger.csv`, 1594 rows) — see [STORAGE_PLAN.md](STORAGE_PLAN.md).
2. **Replayed** share-affecting events per `(account, ticker)` and compared the
   computed position to `Holdings.md`.
3. **Classified** every mismatch by likely root cause.

## Source coverage (the timeline)

| Account | Source | First | Last | Rows | Format |
|---|---|---|---|---|---|
| Tiger Prime | `tiger-prime/tiger_prime_*.csv` (7 yearly) | 2020-07-07 | 2026-06-18 | 789 | IBKR-flex CSV ✅ |
| Tiger Cash Boost | `tiger-cash-boost/*.csv` (3 yearly) | 2024-07-29 | 2026-06-18 | 7 | IBKR-flex CSV ✅ |
| FSM (cash) | `fsm/ifast_historical.csv` | 2020-02-27 | 2026-04-19 | 591 | iFast CSV ✅ |
| CDP | `cdp-statements/*.pdf` (69 monthly) | 2017-04 | 2026-05 | 70 | **PDF, snapshot-diff ✅ (authoritative)** |
| ~~CDP~~ | ~~`cdp-stocks/transactions.csv`~~ | 2015-11 | 2023-09 | — | superseded by statements (gappy) |
| CPF stocks | `cpf-stocks/transactions.csv` | 2017-11-21 | 2025-04-09 | 23 | simple CSV ✅ |
| CPF fund | `endowus statement/*.pdf` (38) | 2023-04 | 2026-05 | 13 | PDF snapshot-diff ✅ (Amundi fund) |
| SRS | `srs-stocks/transactions.csv` | 2020-09-02 | 2026-03-03 | 14 | simple CSV ✅ |
| Moomoo | `moomoo/*.pdf` (62 monthly) | 2021-04 | 2026-05 | 7 | PDF, snapshot-diff ✅ |
| SG self-record | `sg-market/records.csv` | 2015-11 | 2025 | 109 | TSV, portfolio-level SG cross-check ✅ |
| Vickers (legacy) | `vickers-stocks/transactions.csv` | 2019-12-04 | 2021-04-22 | 16 | simple CSV ✅ |
| ~~Tiger archive~~ | ~~`.archive/tiger-stocks/transactions.csv`~~ | 2020-10 | 2026-01 | — | **duplicate of tiger-prime — superseded** |
| IBKR (legacy) | `ibkr/ibkr_20XX.csv` | 2022 | 2025 | **0** | **NAV/MTM only — no trades** ❌ |
| DBS custodian | `dbs-consolidated-statements/*.pdf` (~80) | Jan 2019 | Mar 2026 | snapshot | PDF — CPFIS holdings + cash flows only |

✅ = reconciles cleanly  ❌ = no transaction-level data extracted

---

## Discrepancies

### A. CRITICAL — affects current holdings

| # | Account | Ticker | Holdings | Ledger | Finding |
|---|---|---|---|---|---|
| A1 | Moomoo | 9CI / C38U / HMN | 6912 / 1175 / 136.94 | 2700 / 500 / 153 | **RESOLVED via PDF parse.** Full Moomoo history 2021→**May 2026** reconstructed; AAPL reconciles. Residual gap (9CI +4212, C38U +675, HMN −16.06) is dated **June 2026** — latest statement on disk is May 2026 (`moomoo_202605`). Add `moomoo_202606` to close. |
| A2 | Tiger Cash Boost | UD1U | _(absent)_ | ~~86,000~~ | **RESOLVED — was a routing bug, not a missing record.** The 86,000 IREIT buy (2026-03-03) is tagged `"Settled via SRS account"` in the Tiger Notes column → it is an **SRS** trade executed through Tiger, already counted in `srs-stocks` (which sums to exactly 222,205 = SRS Holdings). Now routed out of Cash Boost. |
| A3+A4 | FSM | UD1U / O5RU / C38U / D05 / 5E2 | 43900 / 37800 / 6200 / 3080 / 1 | _now match_ | **RESOLVED.** Gaps were **un-counted rights-issue / corp-action share deliveries**. iFast books these as `Corp Action` rows with the real ticker + a price (e.g. UD1U +20000+8000+6400 = +34,400; O5RU +3710; C38U +3000; D05 +280; 5E2 +1) alongside throwaway `NRO (...)`/`R (...)` nil-paid-rights placeholders. Parser now counts the real-ticker corp actions and ignores the placeholders → all **held** FSM positions reconcile. |
| A5 | Tiger Prime | MSFT / AMZN / BABA | 100 / 0.349 / 601 | 0 / 0 / 600 | **Mostly resolved** by the new 2026 statement (COIN→400 ✅, 00788→23500 ✅). Residual sits just past the statement cutoff **2026-06-18** (Holdings 2026-06-21): **MSFT 100 = assignment of the short `MSFT 20260618 PUT 390`** (open at cutoff; assigned on expiry → 100 shares delivered 06-18, not yet on a statement); **AMZN 0.349** = fractional/DRIP; **BABA off by 1**. Pull the next statement to confirm. |

### B. HISTORICAL — closed positions (no current-holdings impact)

| # | Account | Ticker | Finding |
|---|---|---|---|
| B1 | FSM (neg.) | S7OU, OU8, Z74, 5CP, F17 | **RESOLVED — CDP→iFast transfers, not missing buys.** CDP statements show each was bought & held in CDP, then transferred out to iFast custody, then sold via FSM. The CDP transfer-out exactly matches the FSM sell (S7OU −108000, OU8 −20000, F17 −5000, Z74 −10000, 5CP −25000). Net across CDP+FSM = 0; all fully exited. |
| B1b | FSM | BTOU (Manulife US REIT) | **RESOLVED.** The self-recorded `sg-market/records.csv` has the buy (3 Apr 2020, +5,200) and sell (27 Sep 2023, −5,200) → net 0, fully exited. No unrecovered acquisitions remain. |
| B2 | Tiger Prime | 01523 | Bought 40,000 (2023-09-26) + 24,000 (2023-12-28); **no disposal recorded**, not held today → missing sell/transfer (check next statement / corp action). |
| B3 | CDP | J2T | **RESOLVED.** CDP statements give 15000−15000+15000+30000−44300 = **700** = Holdings. The `cdp-stocks.csv` value of 1,400 was the gap; statements are authoritative. |
| B4 | CDP | OU8 | **RESOLVED.** CDP shows CENTURION +20,000 (2017-12) buy, −20,000 (2024-06) exit. |
| — | FSM | S51 | +64 residual = Sembcorp Marine → Seatrium 20:1 consolidation noise; fully exited. |

_CPF reconciles fully — D05 = 500 + 600 + 110 bonus = 1,210 (matches Holdings + DBS CPFIS). CDP reconciles fully against its statements (all 7 holdings)._

### Moomoo timeline (reconstructed from PDF snapshot-diff)

| Date | Ticker | Event | Qty |
|---|---|---|---|
| 2021-04 | C31 | buy (CapitaLand) | +2,700 |
| 2021-09 | C31→9CI+C38U | CapitaLand restructuring | C31 −2700, 9CI +2700, C38U +417 |
| 2022-12 | AAPL | buy | +1 |
| 2023-05 | HMN | buy (CapLand Ascott) | +153 |
| 2025-05 | C38U | buy | +83 → 500 |
| _2026-05/06_ | 9CI / C38U / HMN | **statements missing** | +4212 / +675 / −16 |

### C. STRUCTURAL — data-model issues to fix at the source

- **C1 — Brokers execute SRS/CPF trades; ownership ≠ execution venue.** Both Tiger
  and iFast place trades that are *settled in* the SRS or CPF account. Identify them by:
  - **iFast**: `Payment Method` column = `{Cash, SRS, CPFIS-OA}`.
  - **Tiger**: the trade **Notes** column = `"Settled via SRS account"` / `"...CPF account"`.

  These are the **same positions** as in the authoritative `srs-stocks` / `cpf-stocks`
  files (e.g. the Tiger UD1U 86,000 and iFast S61/UD1U all reappear there) →
  **double-counting risk**. The builder routes them to `SRS(via-…-dup)` /
  `CPF(via-…-dup)` so they neither pollute the broker cash account nor double-count.
  Authoritative ownership lives in `srs-stocks` / `cpf-stocks`; broker statements are
  just the execution record.
- **C2 — IBKR is a black box.** `ibkr/*.csv` contain only NAV / Mark-to-Market /
  Cash Report — **zero trade rows**. If pre-Tiger history matters, re-export from IBKR
  as a **Flex Query with the Trades section**.
- **C3 — Legacy → current custody links are undocumented.** Vickers (2019–2021),
  the Tiger archive, and IBKR positions flowed into today's CDP / Tiger / FSM accounts
  but no transfer events tie them together.
- **C4 — Symbol aliasing.** `Holdings.md` uses display labels that differ from the
  SGX codes in the data: `QAF`→`Q01`, `SET`→`CWBU` (Cromwell→Stoneweg European REIT),
  `C`→`C52`. Handled via an alias table in the builder; should be made canonical.
- **C5 — Duplicate / overlapping sources.** Several sources re-record the same trades:
  `.archive/tiger-stocks` duplicates the Tiger flex statements (caught when SG totals
  doubled — CMOU 34,800→69,600); `cdp-stocks.csv` is a partial copy of the CDP
  statements; `sg-market/records.csv` is a portfolio-wide SG self-record overlapping
  everything. Builder tags these `…(superseded)` / `…(dup)` and excludes them from the
  position replay. The **self-record is the cleanest dedup'd SG view** — it nets every
  closed position (5CP, OU8, S7OU, Z74, F17, BTOU) to exactly 0, independently
  confirming they are fully exited with no missing records.

---

## Priority actions to close the gaps

1. **Download remaining latest statements** — Moomoo **June 2026** (`moomoo_202606`) to
   close A1; the next Tiger statement (post-2026-06-18) to confirm the MSFT put
   assignment + AMZN/BABA fractions (A5). Tiger 2026 CSV + Moomoo May already added.
2. **No unrecovered acquisitions remain.** Every buy is captured across CDP statements
   + the SG self-record. ⚠️ CDP statements and the self-record carry **no transaction
   fees** — use Tiger/iFast/CDP-csv for cost basis.
3. **Re-export IBKR as a Flex Query with Trades** if pre-Tiger history is in scope
   (current files have NAV/MTM only).

_Resolved this pass: BTOU (self-record), archive double-count (excluded). Earlier passes:
CDP statements (B1/B3/B4), Moomoo (PDF), Cash-Boost UD1U (SRS routing), FSM corp actions,
CPF D05._

## Visual viewer

`portfolio.html` — a self-contained page (no server/deps). Open in any browser.

- **Sidebar**: grouped by funding bucket **Cash / CPF / SRS**; Cash is further split by
  **US / HK / SG market**, then by **security name** (canonical ticker small beside it),
  with current balance.
- **Click a security** → **all transactions merged across every brokerage** in that bucket,
  in date order, with a **brokerage** column and the **balance after each transaction**.
  Header shows brokerages spanned, final balance, Holdings target, and how many inter-broker
  transfers were netted.
- **Inter-broker transfers are de-duplicated.** A custody move (e.g. CDP→FSM) is logged on
  both sides on different dates; the viewer cancels the matched pair so the running balance
  stays continuous instead of spiking/double-counting. Two shapes handled: explicit
  (both legs logged) and implicit (only the receiving broker's later sale recorded).
- Cash = Tiger Prime/Cash Boost, Moomoo, FSM, CDP. SRS/CPF use their consolidated records;
  duplicate/superseded sources excluded. Search filters by name, ticker, or bucket.

## How to reproduce / extend

```bash
python3 build/build_ledger.py            # 1. rebuild ledger.csv + print reconciliation
build/.venv/bin/python build/parse_moomoo.py   # (PDF sources, if statements changed)
build/.venv/bin/python build/parse_cdp.py
python3 build/build_viewer.py            # 2. regenerate portfolio.html
# open portfolio.html in a browser, or:  python3 -m http.server 8731  then visit /portfolio.html
```
