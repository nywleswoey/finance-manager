# Dividend Income

Cash dividends / distributions parsed from every statement source by
`build/parse_dividends.py` → `build/dividends.csv`. These were
**always in the statements** — the position parsers just didn't extract them. Shown
per security in the web app (the Dividends tab and the security page).

## Sources

| Source | Section parsed | Markets |
|---|---|---|
| Tiger flex | `Dividends` (status = `Paid` only; accruals skipped) | HK, SG, US |
| FSM / iFast | `Stock Dividend` rows that are `Cash Dividend` / `Cash in Lieu` | SG (+ USD/EUR REITs) |
| CDP | tracker sheet `data/cdp-stocks/dividends.csv` (`cdp()`); a row with a rate but no amount is backfilled as rate × the CDP position in `ledger.csv`, except on pay dates inside a CDP statement gap | SG (+ USD/EUR) |
| Moomoo | `… CASH DIVIDEND` lines | SG, US |
| CPF / SRS | backfilled (no dividend lines in their transaction files) | SG (+ EUR REIT) |
| Endowus | — (Amundi fund accumulates; no distributions) | — |

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

## Display currency

The `dividend` table stores the **native** amount the statement paid (`gross` + `currency`) —
that never changes. Every read shape adds a `gross_sgd` converted at the latest FX rate
(`portfolio.money.to_sgd`), and the UI leads with SGD everywhere, because the rest of the app
(cost basis, market value, P/L, Net) is SGD and a native-currency dividend column made HKD
199k read as SGD 199k. The native amount stays visible — muted underneath the SGD figure in the
Dividends detail + security history, and as the row tooltip in Holdings — so any figure can
still be reconciled against the statement. Per-unit rates (declared and implied) stay
**native**: a declared rate is a statement fact, not a converted one.

The dividend read path converts every year at the latest `fx_rate` for that currency, so
prior-year SGD figures are an approximation — the `SGD · latest FX` pill in the UI says so.
Dated FX is stored (`fx_rate` is keyed on `(date, currency)` and `ingestion/prices.py` writes
those rows); this path does not read the rate on the pay date. A currency with no row in
`fx_rate` is never passed through at 1:1: `/api/dividend-details` returns `gross_sgd: null` and
flags the row `no FX rate for <CCY>`; the other endpoints raise (BR4, no silent fallback).

## Per-dividend detail (qty held + declared rate)

`GET /api/dividend-details` returns one row per payment with:
- **gross** (native, as paid) and **gross_sgd** (latest FX; null + flagged when the currency has
  no rate). `total_sgd` / `flagged_sgd` are the SGD totals of all rows / the flagged rows,
  summed at full precision and rounded once (docstring: `details()` in `portfolio/dividends.py`).
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
  and a "flagged only" filter for manual entry. The count moves with the book; the tab is
  where it is read.

## Notes / caveats (for the DB Phase-2 cleanup)

- **Currency**: Tiger's flex file carries the cash currency in its last column
  (`tiger_currency`); a blank cell still infers from market (HK→HKD, SG→SGD, US→USD).
  The EUR-named REIT (SET/CWBU) is not thereby EUR: the live Tiger rows are SGD, and the
  amount equals quantity times the SGD gross rate. EUR distributions on SET and UD1U
  arrive from CDP, FSM and SRS with their own currency already set. `gross_sgd` and
  `income_sgd` both convert off that label.
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
  ├─ make flat   build/parse_dividends.py  ──►  build/dividends.csv   (all sources merged + deduped)
  │              (also parse_moomoo / parse_cdp / parse_endowus / build_ledger)
  │
  ├─ make load   ingestion.load  →  load_dividends()  ──►  Postgres `dividend` table
  │              │   idempotent upsert keyed on dedup_hash = h(account,ticker,date,gross,source,occ#);
  │              │   currency/rate/units refreshed in place; a changed gross is a new hash, so the
  │              │   old row is pruned and a new one inserted; rows that vanish from the CSV are
  │              │   pruned; unknown accounts are named.
  │              ├─ backfill_ex_dates()  ◄──  data/dividends-master.csv   (restores ex_date on
  │              │   rows that have none, e.g. one just re-inserted)
  │              └─ build/export_dividends_master.py  ──►  data/dividends-master.csv
  │                  (one row per distinct dividend event: date, ex_date, ticker, rate_per_unit, currency;
  │                   rate = gross / qty-at-ex-date, account-independent, deduped across accounts)
  │
  ├─ server/routes/portfolio.py   /api/dividend-details · /api/dividends-annual
  │                               web/src/modules/portfolio/Dividends.jsx  (annual matrix + per-payment detail table)
  │
  └─ make dividend-announcements   ingestion.dividend_announcements  ──►  Postgres
                 `dividend_announcement` table (SGX-declared rates for current SG holdings)
                 /api/dividends-projected  ──►  Dividends.jsx's `<year> expected` card — see
                 "`<year> expected`" below
```

`make ingest` runs `flat` then `load` in one shot. `make ingest-all` also folds in spending,
prices/FX, and net-worth snapshots. Everything is delta/idempotent — re-running never
double-counts (dedup_hash guards it).

### Adding a new dividend (statement arrives)

Normal case — the dividend **is already in a new statement**:

1. Drop the new statement into its `data/<broker>/` folder (same as any position update).
2. `make ingest` — reparse → `build/dividends.csv` → upsert into DB → re-export master.
3. Only genuinely new payments insert (plus any re-inserted with a corrected amount — see
   below). Check the printed "NEW rows" count. Refresh the API/`app` to see it in the Dividends tab.

Manual case — a payment **no statement carries** (e.g. a CPF/SRS holding, whose transaction
files have no dividend lines):

1. Add the row to the relevant hand-tracker CSV — `data/cpf-srs-dividends.csv` for CPF/SRS,
   or `data/cdp-stocks/dividends.csv` for CDP — matching its column layout
   (`date, account, market, ticker, name, kind, gross, units, rate, currency, source`).
2. `make ingest` picks it up via the parser's `cpf_srs()` / `cdp()` readers.
3. If it's a brand-new ticker, seed it first (`make seed`) so the loader can map the alias —
   otherwise `load_dividends()` maps `security_id=null` and it shows as **unmapped ticker**.

Fixing a wrong amount: edit the source statement/tracker row and re-`make ingest`. `gross` is part
of the dedup_hash, so the corrected row gets a new hash: the old row is pruned and the new one
inserted, not updated in place. That is deliberate — the statements are the source of truth, and
the DB row is rebuilt from them. The new row's `ex_date` is restored by `backfill_ex_dates()` from
`data/dividends-master.csv`, which `make load` re-exports after every load, so only an ex-date set
in the DB since the last export would be lost. Do **not** hand-edit `data/dividends-master.csv`,
it's regenerated.

### Manual-input flags

`/api/dividend-details` flags rows that need a human: **qty unknown** (no declared rate and no
replayable ledger qty), **no date** (old CDP layout), **unmapped ticker**. The Dividends tab
has a "flagged only" filter. Dateless 2017-18 CDP payments are the usual case.
Resolve by adding the missing rate/date/units to the source tracker row and re-ingesting.

This is **Phase 2 (dividends) of [PLAN.md](../archive/PLAN.md) front-loaded** — `dividends.csv` maps
directly onto the `dividend` table and makes total-return computable.

## `<year> expected` (the full-year projection)

The Annual Dividend Income table's current-year column is **payments received so far**, not a
forecast — see the rest of this doc. `GET /api/dividends-projected`
(`portfolio.dividends.projected()`) adds a separate, non-replacing figure: received so far
(exactly `annual()`'s current-year total) **plus**, for each CURRENTLY HELD security, the rest
of the year's expected payments. Per holding, in order of preference:

1. **announced** — `dividend_announcement` rows paid (pay_date, else ex_date) between today and
   year end — bucketed like received money, by pay date — and not already received, rate ×
   TODAY's units (not the units at ex-date, since the rate is account/time-independent and the
   question is "what would I get now").
2. **last_year_pattern** — last year's distinct payments (one per pay date, however many
   accounts or statement lines carried it — `_payments()`) not yet matched by this year's (`unreceived_last_year()`): each payment
   received this year consumes at most one last-year payment, the one whose anniversary is
   nearest within ±45 days (`DRIFT_DAYS`); an unmatched one is projected if its anniversary is no
   more than 45 days before today — so a monthly payer's receipt cancels exactly one payment, a
   payment running late is kept, and one further behind is not projected (it is **overdue**,
   below). Each row's rate (declared, else gross/units-held-then — reuses `details()`'s per-row
   computation rather than re-replaying the ledger) × TODAY's units.
3. **none** — neither exists (e.g. a security that already paid its only distribution for the
   year, or pays no cash dividend at all).

**Overdue** — an unmatched last-year payment whose anniversary is more than `DRIFT_DAYS` before
today is almost always money already paid but not yet ingested, so it is reported, never
projected: each held security's `overdue` list (`expected_date` = the anniversary, `amount_sgd`)
and the top-level `overdue_sgd` / `overdue_count`, shown as the card's "Overdue (not in totals)"
figure and an amber per-row tag. It is priced at the units held on the anniversary of last year's
ex_date (else pay_date) via `units_at`, and dropped when none were held then. It is never added to
`expected_remaining_sgd` or `projected_total_sgd`.

It always projects the current SGT year (`sg_today()`); there is no year parameter. A ticker
that received a payment this year but is no longer held keeps its `received_sgd` with basis
`"not held"` and no projected remainder; dividends with no mapped security are one `ticker: null`
row with basis `"unmapped"`, so the per-holding `received_sgd` column sums to the headline. A
currency with no `fx_rate` row degrades to a flagged, unpriced row (`_sgd_or_none`) rather than
raising — unlike `annual()` (BR4) — because an estimate must not crash the page over one
unpriced holding.

**The online source**: `dividend_announcement` is filled by `ingestion.dividend_announcements`
(`make dividend-announcements`, folded non-fatally into `make ingest-all` beside `prices`),
cached rather than fetched per page load. SGX's corporate-actions API
(`api.sgx.com/corporateactions/v1.0?cat=DIVIDEND&name=`) filters only by a security's *exact*
legal name — there is no ticker/code parameter, and an unrecognized name silently returns the
WHOLE unfiltered history rather than nothing (`portfolio.sgx.sgx_schedule`'s docstring). There is
no curated name table: each currently-held SG security (excluding funds) tries its own
`security.name` and every `security_alias` as a candidate and keeps the first SGX actually
recognizes, since broker statement text routinely already echoes the exchange's registered name
on a dividend line. A security with no matching candidate — or outside SG, or a cash/scrip
election SGX's regex-summed rate can't be trusted for — simply has nothing in
`dividend_announcement`, and `projected()` falls back to `last_year_pattern` for it. That is the
graceful degradation, not a special case.
