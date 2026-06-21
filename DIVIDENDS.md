# Dividend Income

Cash dividends / distributions parsed from every statement source by
`build/parse_dividends.py` → `build/dividends.csv` (485 records, 2017–2026). These were
**always in the statements** — the position parsers just didn't extract them. Now shown
per security in the viewer header.

## Sources

| Source | Section parsed | Rows | Markets |
|---|---|---|---|
| Tiger flex | `Dividends` (status = `Paid` only; accruals skipped) | 113 | HK, SG, US |
| FSM / iFast | `Stock Dividend` rows that are `Cash Dividend` / `Cash in Lieu` | 242 | SG (+ USD/EUR REITs) |
| CDP | `Summary of Payments` / `Cash Transaction` (both PDF layouts) | 100 | SG |
| Moomoo | `… CASH DIVIDEND` lines | 30 | SG, US |
| Endowus | — (Amundi fund accumulates; no distributions) | 0 | — |

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

## Re-generate

```bash
python3 build/parse_dividends.py     # -> build/dividends.csv
python3 build/build_viewer.py        # viewer shows dividends per security
```

This is **Phase 2 (dividends) of [PLAN.md](PLAN.md) front-loaded** — `dividends.csv` maps
directly onto the planned `dividend` table and makes total-return computable.
