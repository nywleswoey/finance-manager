# Dividends needing manual intervention

34 of 466 dividend payments can't have their per-share rate determined automatically.
Source: `GET /api/dividend-details` flags (regenerate after each parse with the snippet at
the bottom). Fill the blank columns, then we'll feed corrections back into the parser /
DB (`amount_per_unit`, `units`, `pay_date`).

## Why flagged

| Flag | Count | Cause |
|---|---|---|
| `no date` + `qty unknown` | 33 | **2017-18 CDP statement layout** prints no pay date and no `units @ rate` line, only a name + gross. Without a date the ledger can't be replayed for qty, and no rate is stated. |
| `qty unknown` (date known) | 1 | FSM U96 (Sembcorp Ind) 2022-05-10 — has a date but the ledger holds no position for it at that date (likely a missing/early-exited buy). |

## A. CDP 2017-18 — no date, no qty (33 rows)

Need: **pay date** + **units held** (or the declared per-share rate). Grouped by security.
`?` = to fill.

| Security | Ticker | Gross (SGD) | Pay date | Units held | Rate /unit |
|---|---|---|---|---|---|
| ADVANCER GLOBAL | 43Q | 25.80 | ? | ? | ? |
| ADVANCER GLOBAL | 43Q | 29.40 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 6.75 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 11.25 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 125.25 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 5.50 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 8.25 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 181.50 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 41.25 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 35.75 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 646.25 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 27.50 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 30.25 | ? | ? | ? |
| AIMS APAC REIT | O5RU | 629.75 | ? | ? | ? |
| Centurion | OU8 | 100.00 | ? | ? | ? |
| Centurion | OU8 | 200.00 | ? | ? | ? |
| DBS Group Holdings | D05 | 700.00 | ? | ? | ? |
| DBS Group Holdings | D05 | 840.00 | ? | ? | ? |
| DBS Group Holdings | D05 | 1080.00 | ? | ? | ? |
| GuocoLand | F17 | 350.00 | ? | ? | ? |
| HRnetGroup | CHZ | 230.00 | ? | ? | ? |
| Jumbo | 42R | 15.00 | ? | ? | ? |
| Jumbo | 42R | 21.00 | ? | ? | ? |
| QAF | Q01 | 680.00 | ? | ? | ? |
| QAF | Q01 | 170.00 | ? | ? | ? |
| STARHILLGBL REIT | P40U | 18.90 | ? | ? | ? |
| STARHILLGBL REIT | P40U | 20.25 | ? | ? | ? |
| STARHILLGBL REIT | P40U | 118.80 | ? | ? | ? |
| SingTel | Z74 | 267.50 | ? | ? | ? |
| SingTel | Z74 | 330.00 | ? | ? | ? |
| SingTel | Z74 | 748.00 | ? | ? | ? |
| SingTel | Z74 | 1829.70 | ? | ? | ? |
| Soilbuild Biz Reit | SV3U | 214.37 | ? | ? | ? |

**Likely source**: these all predate the 2019 CDP layout change. The pay dates + rates are
recoverable from the original 2017-18 CDP monthly PDFs (`data/cdp-statements/2017*.pdf`,
`2018*.pdf`) — the `rx_old` regex in `parse_dividends.py` catches the gross but not the
date/rate. Either hand-fill above or extend `rx_old` to capture them.

## B. FSM — date known, no ledger qty (1 row)

| Date | Account | Security | Ticker | Gross | Qty held | Rate /unit | Note |
|---|---|---|---|---|---|---|---|
| 2022-05-10 | FSM | Sembcorp Ind | U96 | 90.00 SGD | ? | ? | No U96 position in ledger at this date — missing buy or early exit. Add the qty (or the U96 acquisition) to resolve. |

## Regenerate this list

```bash
python3 build/parse_dividends.py            # re-parse sources
PYTHONPATH=. .venv/bin/python -m ingestion.load   # reload DB
PYTHONPATH=. .venv/bin/python -c "from api.main import dividend_details; \
d=dividend_details(); \
print('\n'.join('|'.join([str(r['pay_date'] or ''),r['account'],r['ticker'] or '', \
(r['name'] or '')[:28],f\"{r['gross']:.2f}\",'; '.join(r['flags'])]) \
for r in d['rows'] if r['flags']))"
```
