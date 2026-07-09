# Dividend Income

Cash dividends / distributions parsed from every statement source by
`build/parse_dividends.py` → `build/dividends.csv` (549 records, 2017–2026). These were
**always in the statements** — the position parsers just didn't extract them. Now shown
per security in the viewer header.

## Sources

| Source | Section parsed | Rows | Markets |
|---|---|---|---|
| Tiger flex | `Dividends` (status = `Paid` only; accruals skipped) | 113 | HK, SG, US |
| FSM / iFast | `Stock Dividend` rows that are `Cash Dividend` / `Cash in Lieu` | 242 | SG (+ USD/EUR REITs) |
| CDP | `Summary of Payments` (2017-18 3-line block + 2019+ layout) | 102 | SG |
| Moomoo | `… CASH DIVIDEND` lines | 11 | SG, US |
| CPF / SRS | backfilled (no dividend lines in their transaction files) | 81 | SG (+ EUR REIT) |
| Endowus | — (Amundi fund accumulates; no distributions) | 0 | — |

### CPF / SRS backfill

The CPF-IS and SRS holdings (`data/cpf-stocks/`, `data/srs-stocks/`) record only
trades — no distributions — and are **distinct positions** from the iFast/Tiger/CDP lots
of the same counters (e.g. AIMS: SRS 3,700u vs the iFast 34,090u lot), so their dividends
appear in no statement. `build/fetch_cpf_srs_dividends.py` reconstructs them once into
`data/cpf-srs-dividends.csv` (read back by `cpf_srs()` in the parser). A dividend's
per-unit rate is account-independent, so it is sourced **locally first**, online only for
gaps:

1. **personal tracker** (`data/cdp-stocks/dividends.csv`) — hand-recorded declared rates, 2016–mid-2022.
2. **implied** — existing `dividends.csv` gross ÷ the paying account's `ledger.csv` units (2022–2026).
3. **SGX** corporate-actions API — official declared rate; also the ex/pay-date + currency spine.
4. **Yahoo** — last resort (its amounts are split/bonus/rights-adjusted; currently unused).

Units held at each ex-date are replayed from the CPF/SRS ledger; `gross = units × rate`.
Totals: **CPF SGD 17,648**; **SRS SGD 8,620 + EUR 7,803**.

## Totals (native currency, not FX-converted)

**By market**
- **HK: HKD ~199,877** (the dividend engine — HK REITs/telcos: 01310 51k, 01523 49k, 00010 31k, 01038 22k, 00101 19k …)
- SG: SGD ~136,334 · EUR ~3,137 · USD ~500
- US: USD ~803

**By account**
| Account | Dividends |
|---|---|
| Tiger Prime | HKD 198,837 · SGD 14,827 · USD 786 |
| FSM | SGD 60,684 · EUR 3,137 · USD 500 |
| CDP | SGD 58,963 |
| Moomoo | SGD 1,360 · USD 17 |
| Tiger Cash Boost | HKD 1,040 · SGD 500 |

## Per-dividend detail (qty held + declared rate)

`GET /api/dividend-details` returns one row per payment with:
- **declared rate** (`amount_per_unit`) — the per-share rate stated in the statement.
  Captured where the PDF prints it: CDP (`… <qty> units @ SGD <rate>`) and Moomoo
  (`… CASH DIVIDEND @ <CCY> <rate>` / US `<qty> SHARES DIVIDENDS`). Tiger / FSM / the
  2017-18 CDP layout don't print a rate → left null.
- **qty held** — units of the ticker held in the paying account at the pay date,
  replayed from the ledger (`txn` summed where `trade_date ≤ pay_date`). Falls back to
  the statement-stated units when present.
- **implied rate** = `gross / qty_held`. Cross-checks the declared rate (they match where
  both exist — e.g. 42R 0.005 declared = 0.005 implied).
- **flags** — `"qty unknown — needs manual input"` when neither a declared rate nor a
  ledger qty can be determined; `"no date"` (old CDP layout omits the pay date so qty
  can't be replayed); `"unmapped ticker"`. The Dividends tab surfaces a flagged count
  and a "flagged only" filter for manual entry. ~34 of 466 rows currently need input
  (mostly the dateless 2017-18 CDP payments).

## Notes / caveats (for the DB Phase-2 cleanup)

- **Currency**: Tiger has no dividend-currency column → inferred from market (HK→HKD,
  SG→SGD, US→USD). The EUR REIT (SET/Cromwell→Stoneweg) Tiger payouts are therefore
  labelled SGD; FSM's EUR ones are correct. Refine when prices/FX land.
- **US withholding tax**: Tiger `Paid` amounts are taken as received (likely net of WHT);
  a separate `Withholding Tax` section exists to net gross vs net later.
- **ADQU (Accordia Golf) SGD 28,264 on 2020-10-15** looks like a delisting/special capital
  distribution, not recurring income — flag when computing yield (exited position).
- **Scrip dividends** deliver shares, not cash → already handled in the position ledger,
  excluded here.

## Pipeline (end-to-end)

Statements are the only source of truth; everything downstream is regenerated, idempotent,
and safe to re-run. The `dividend` Postgres table is the store of record; the two CSVs are
a build cache (`build/dividends.csv`) and a derived reference (`data/dividends-master.csv`).

```
data/**  (broker statements: tiger-prime, fsm, cdp-stocks, moomoo, cpf/srs …)
  │
  ├─ make flat   build/parse_dividends.py  ──►  build/dividends.csv   (549 rows, all sources merged + deduped)
  │              (also parse_moomoo / parse_cdp / parse_endowus / build_ledger)
  │
  ├─ make load   ingestion.load  →  load_dividends()  ──►  Postgres `dividend` table
  │              │   idempotent upsert keyed on dedup_hash = h(account,ticker,date,gross,source,occ#);
  │              │   mutable fields (gross/net/currency/rate/units) refreshed in place;
  │              │   rows that vanish from the CSV are pruned.
  │              └─ build/export_dividends_master.py  ──►  data/dividends-master.csv
  │                  (one row per distinct dividend event: date, ex_date, ticker, rate_per_unit, currency;
  │                   rate = gross / qty-at-ex-date, account-independent, deduped across accounts)
  │
  └─ server/main.py   /api/dividends · /api/dividend-details · /api/dividends-annual
                      web/src/modules/portfolio/Dividends.jsx  (annual matrix + per-payment detail table)
```

`make ingest` runs `flat` then `load` in one shot. `make ingest-all` also folds in spending,
prices/FX, and net-worth snapshots. Everything is delta/idempotent — re-running never
double-counts (dedup_hash guards it).

### Adding a new dividend (statement arrives)

Normal case — the dividend **is already in a new statement**:

1. Drop the new statement into its `data/<broker>/` folder (same as any position update).
2. `make ingest` — reparse → `build/dividends.csv` → upsert into DB → re-export master.
3. Only genuinely new payments insert; corrected amounts update in place. Check the printed
   "NEW rows" count. Refresh the API/`app` to see it in the Dividends tab.

Manual case — a payment **no statement carries** (e.g. a CPF/SRS holding, whose transaction
files have no dividend lines):

1. Add the row to the relevant hand-tracker CSV — `data/cpf-srs-dividends.csv` for CPF/SRS,
   or `data/cdp-stocks/dividends.csv` for CDP — matching its column layout
   (`date, account, market, ticker, name, kind, gross, units, rate, currency, source`).
2. `make ingest` picks it up via the parser's `cpf_srs()` / `cdp()` readers.
3. If it's a brand-new ticker, seed it first (`make seed`) so the loader can map the alias —
   otherwise `load_dividends()` maps `security_id=null` and it shows as **unmapped ticker**.

Fixing a wrong amount: edit the source statement/tracker row and re-`make ingest`; the upsert
overwrites (same dedup_hash) — do **not** hand-edit `data/dividends-master.csv`, it's regenerated.

### Manual-input flags

`/api/dividend-details` flags rows that need a human: **qty unknown** (no declared rate and no
replayable ledger qty), **no date** (old CDP layout), **unmapped ticker**. The Dividends tab
has a "flagged only" filter. ~34 of 466 rows currently need input (mostly dateless 2017-18 CDP).
Resolve by adding the missing rate/date/units to the source tracker row and re-ingesting.

This is **Phase 2 (dividends) of [PLAN.md](PLAN.md) front-loaded** — `dividends.csv` maps
directly onto the `dividend` table and makes total-return computable.
