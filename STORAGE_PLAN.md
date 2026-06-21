# Transaction Storage Plan

How transaction records *should* be stored so the portfolio is reconcilable and
missing records are detectable automatically.

## Principle: event-sourced ledger

`Holdings.md` is **derived state**. The source of truth should be an append-only
**ledger of events**; current holdings = replay of all events per `(account, ticker)`.
This is exactly what `build/build_ledger.py` does today — the goal is to make the
ledger the *primary* artifact, not a throwaway.

## Directory layout

```
portofolio/
├── Holdings.md                      # DERIVED snapshot (regenerated, never hand-edited as truth)
├── ledger.csv                       # CANONICAL append-only event ledger  ← source of truth
├── symbols.csv                      # symbol alias / rename table
├── data/                            # RAW source files (immutable, as downloaded)
│   ├── tiger-prime/  tiger-cash-boost/
│   ├── fsm/  cdp-stocks/  cpf-stocks/  srs-stocks/
│   ├── moomoo/  dbs-consolidated-statements/   # PDFs → need extraction
│   ├── ibkr/  vickers-stocks/  .archive/        # legacy
└── build/
    ├── build_ledger.py              # parsers: raw/ → ledger.csv
    └── reconcile.py                 # ledger → positions, diff vs Holdings.md
```

Raw files stay **immutable**; every parsed row keeps a `source` pointer so any number
in the ledger traces back to an original statement.

## Canonical ledger schema (`ledger.csv`)

One row per economic event. Columns:

| Column | Meaning | Notes |
|---|---|---|
| `date` | ISO `YYYY-MM-DD` | trade/settle date |
| `account` | `Tiger Prime`, `Tiger Cash Boost`, `Moomoo`, `FSM`, `CDP`, `CPF`, `SRS`, … | the **logical** account, not the platform |
| `market` | `US` / `SG` / `HK` | |
| `ticker` | **canonical** exchange code (HK zero-padded to 5) | resolved via `symbols.csv` |
| `asset_type` | `stock` / `option` / `fund` / `forex` / `cash` | |
| `action` | `buy` `sell` `ipo` `rights` `bonus` `scrip_div` `cash_div` `transfer_in` `transfer_out` `corp_action` `deposit` `withdrawal` | controlled vocabulary |
| `qty_signed` | **signed** share delta (+ in, − out); `0` for pure cash | the field reconciliation sums |
| `price` | unit price | |
| `amount` | signed cash flow | |
| `currency` | ISO | |
| `fees` | total fees | |
| `source` | relative path to raw file | provenance |
| `raw` | original symbol/description | audit trail |

### Rules that prevent the bugs found in this pass

1. **`qty_signed` is the only quantity field, always signed.** The simple-CSV sources
   already sign `Qty` (sells negative); never re-derive sign from the cash amount
   (that flipped every buy in the first build).
2. **One row = one account.** Route co-mingled exports (iFast → Cash/SRS/CPFIS) to the
   correct logical account via their `Payment Method`/portfolio field; do **not** dump
   them all under one account.
3. **Corporate actions are first-class events**, not cash footnotes. Scrip dividends,
   rights subscriptions, bonus issues, and consolidations each get a `qty_signed`.
   (The current FSM shortfalls in A4 are because "Corp Action" quantities aren't summed.)
4. **Transfers are paired events.** A transfer out of Vickers and into CDP are two rows
   sharing a `transfer_id`, so legacy→current custody is auditable (fixes C3).

## Symbol alias table (`symbols.csv`) — generated

`symbols.csv` (60 rows) reconciles every name/code variant across all sources to one
canonical SGX ticker. Generated from the coded sources + the CDP name map. Examples:

```
canonical,alias_code,names
O5RU,O5RU,AIMS APAC REIT; AIMSAMP CAP REIT; AIMS APAC Reit
CWBU,CWBU,Cromwell Reit EUR; STONEWEG EUTRUST; STONEWEG REIT EU
CWBU,SET,(label alias)
Q01,QAF,(label alias)
C52,C,(label alias)
```

Key reconciliations (renames — same security, multiple identifiers, now one series):
`O5RU` = AIMSAMP CAP REIT → AIMS APAC REIT · `CWBU` = Cromwell European → Stoneweg
European REIT (= `SET`) · `BTOU` = Manulife US REIT · `ADQU` = Accordia Golf (+SUSP).
Corporate-action splits stay distinct (different share counts): `C31`→`9CI`+`C38U`
(CapitaLand 2021), `S51`→`5E2` (Sembcorp Marine→Seatrium 20:1).

The CDP parser snapshot-diffs **per canonical code** so a rename reads as continuity,
not a spurious sell + rebuy. Ledger and `Holdings.md` resolve through this table.

## Reconciliation = the missing-record detector

`reconcile.py` replays the ledger and flags, per `(account, ticker)`:

- `ledger < 0`  → **missing BUY** (impossible negative position)
- `Holdings > ledger > 0` → **missing BUY / corporate action**
- `ledger > Holdings` → **missing SELL**
- `Holdings present, ledger = 0` → **no transaction data** (PDF-only or post-statement gap)

Run it after every new statement import; a clean run = no missing records.

## Filling the remaining holes

| Gap | Action |
|---|---|
| Moomoo (PDF only) | Export trade confirmations to CSV, or write a `moomoo/*.pdf` parser (tables are `pdftotext -layout`-friendly). |
| DBS pre-2020 buys | Parse `dbs-consolidated-statements/*.pdf` for the CDP/CPFIS holding snapshots + corporate actions. |
| IBKR trades | Re-export as an IBKR **Flex Query** including the *Trades* section (current files have NAV/MTM only). |
| Statement lag | Holdings dated after the latest statement always shows phantom gaps; regenerate Holdings *from* the ledger so the two can't drift. |
```
