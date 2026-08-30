# Backend — Phase 0/1 (DB foundation + load)

Implements [PLAN.md](PLAN.md) Phase 0 (Postgres + schema + seed) and the first half of
Phase 1 (load the existing `build/*.csv` into the DB, idempotently).

## Stack in place

- **Postgres 16** via `docker-compose.yml` (host port **5544**).
- **SQLAlchemy 2.0** models (`portfolio/models.py`) + **Alembic** migrations (`migrations/`).
- **Seed** (`scripts/seed.py`): accounts, securities, aliases, corporate actions.
- **Loader** (`ingestion/load.py`): `build/ledger.csv` + `build/dividends.csv` → `txn` / `dividend`.

## Quick start

```bash
uv venv .venv && uv pip install --python .venv/bin/python \
    sqlalchemy alembic "psycopg[binary]" pydantic-settings python-dotenv
cp .env.example .env
make refresh        # db-up + migrate + seed + load   (idempotent)
make psql           # poke around
```

## What's in the DB now

| Table | Rows | Notes |
|---|---|---|
| `account` | 7 | Tiger Prime/Cash Boost, Moomoo, FSM, CDP, CPF, SRS (with funding_bucket) |
| `security` | 79 | canonical ticker + name + market + asset_type + currency |
| `security_alias` | 197 | every name/code variant → security (from `symbols.csv`) |
| `corporate_action` | 4 | CWBU→SET rename, S51→5E2 20:1, C31→9CI/C38U split |
| `txn` | 525 | all share-affecting events (stocks + Amundi fund) |
| `dividend` | 485 | cash dividends, all sources |

Views: `current_position` (units per account+security), `dividend_summary` (by
bucket/market/currency). Verified vs Holdings — e.g. SRS UD1U = 222,205, Tiger HK all match.

## Idempotency

Each row gets a `dedup_hash` = `sha256(account, ticker, date, action, qty, amount, occurrence)`.
The **occurrence** counter (nth identical row within a file) keeps two genuinely-identical
lots distinct (e.g. the two `2-Sep-20 UD1U 11100` SRS buys) while re-ingesting the same
file inserts nothing new (`ON CONFLICT (dedup_hash) DO NOTHING`).

## Next (rest of Phase 1 → Phase 4)

- Rewrite parsers to write **directly** to the DB + record `import_batch` per file —
  currently we load the pre-built `ledger.csv`/`dividends.csv` as the bridge.
- Load `position_snapshot` from statement holdings tables (Moomoo/CDP/Endowus parsers
  already produce these).
- Phase 3: `price` + `fx_rate` loaders (yfinance + statement NAVs).
- Phase 4: performance engine (avg cost, valuation, XIRR + TWR, dividends) as SQL views +
  a thin Python layer.

## Cost basis sources

Performance is computed **per funding bucket × security** (not per account): transfers
within the cash bucket (CDP→FSM) don't change ownership, so a position moved into FSM
keeps its original CDP purchase cost. CDP cost (which the CDP statements omit) is taken
from `data/cdp-stocks/transactions.csv` via `portfolio/performance.cdp_cost()` and pooled
into the cash-bucket position. Positions still come from the authoritative
CDP statements; `alloc_by_account()` gives the per-account MV split for charts.

CDP cost is matched at **position** level, not per row — a CDP `txn` row is a month-end
statement diff that routinely aggregates several trade-dated cost lots, and matching per row
invents shortfalls that do not exist. `performance.cost_partition` carries the detail.

## Cost truth is a partition of units

A boolean cannot say the thing that is actually true of Q01: *17,000 of its 68,000 units
entered with no recorded cost*. So every entering unit lands in exactly one of three
conditions, computed after the corporate-action carry and the switch rebasing run and shipped
as a nested `cost_partition` on every position row:

```json
"cost_partition": { "units_in": 68000, "costed": 51000, "free": 0,
                    "unknown": 17000, "unknown_pct": 0.25 }
```

The three **sum to gross units in** on every position — 73 of 73 in the live book, which totals
1,574,652 units in: 1,521,274 costed, 545 free, 52,833 unknown. Nested so the counts cannot
drift apart among ~25 flat siblings and the self-check is visible in one place.
`tests/test_performance_live.py` holds those figures to the ledger they were measured against.

- **A carried unit is `costed`** — its cost is known, it just came from a predecessor (9CI's
  2,700 from C31). Likewise a transfer in whose paired transfer out sits in the same position:
  the cost never left.
- **`free` units carry a price, not only a count** — `cost_basis = 0.0`, never `null`. They
  enter `buy_qty` at zero cost, which is what makes AAPL's basis a *measured* zero (and stops
  D05's 280 bonus shares inflating its cost basis past what was ever invested).
- **The action string cannot decide free from transferred.** Every unpriced carry-in is
  `open/transfer_in` on one account, covering a landed corporate-action carry, a real in-specie
  distribution and two windfalls. That distinction lives in a per-transaction annotation
  (`portfolio/cost_annotations.py`) defaulting to `unknown` — refuse rather than invent a free
  lot. `gifted stock in` and `bonus issuance` are mechanical and need no annotation.
- **`cost_known` is the partition read as a boolean**: false only when *every* entering unit is
  unknown. Not `unknown == 0`, which would flip C38U to false and delete its 7,756.75 Net.
  Live, the refusal set is ASTREA6B alone; the caveat set is S51 40.0%, SET 27.9%, Q01 25.0%,
  C38U 7.5%.

## The four cell states

A missing number on a position row means one of four things. The **fold names which** so a page
can render each differently; the rendering itself is not here — the detail page still says `n/a`
where it now means *not known*, and #158 / #159 land the words. The rule is *has this stream ever
existed*, not *is the number zero*.

| state | meaning | intended rendering |
|---|---|---|
| omitted | the stream has never existed for this ticker | row absent |
| `0` | the stream exists and measured zero | `0` |
| `—` | structurally impossible | `—` |
| not known | the stream exists but is unmeasurable | words |

So `null` means **exactly one thing per field**. `income_sgd` is named on the first line by
#143 §6 and is **not** done: it still ships `0.0` on a name that never paid a dividend.

- **`options_pl_sgd` null means the stream never existed** — a never-optioned ticker omits the
  row rather than carrying a permanent `Options 0` line (61 of 73 legs live). An optioned name
  still ships a number when that number is zero. Dividends and options can be *absent* but never
  *unmeasurable*: cash received is always known. The `—` state is leg-level — a non-cash leg of
  an optioned name — and is reconstructed where the ticker's own option book is in view, not here.
- **`avg_cost`, both cost-basis fields and the realised/unrealised pair null mean *not known***,
  and it is the **partition** that decides it, never the unit count. A leg holding `unknown`
  units cannot price the shares it still has, so all five go null together. A leg whose every
  unit entered priced *can* price them — even when it holds none left — and ships the measured
  zero: nulling on `units ≈ 0` would say *not known* of TSLA and of F34's closed cpf leg, whose
  Net (940.00) is exact and whose unrealised is a genuine zero, and F34's second bucket column
  would stop adding up. Realised and unrealised can be *unmeasurable* but never *absent*: units
  always entered.
- **`stock_pl_sgd` joins every row.** `realised + unrealised` is identically
  `proceeds − buy_cost + mv`, so the **pair's sum is sound while neither member is** — which is
  what lets a doubted name show an arithmetically exact Net. Where both members exist it is
  rounded *from* them, so §14's measured cent stays where it already is rather than opening a
  second gap between a sum and its parts.
- **The group says what its two columns do not reach.** `rollup()` accumulates `stock_pl_sgd` and
  `/api/performance` builds `net_pl_sgd` from it, so the four doubted legs' stock P/L stays in the
  group total instead of vanishing with the split — every group net is unchanged to the cent.
  Beside it, `unsplit_pl_sgd` is the part of that total no leg could attribute to either member,
  so `realised + unrealised + unsplit == stock_pl` on every group and the Performance table marks
  those two cells `~` instead of printing a short column beside a whole Net.

## Peak capital-at-risk, and the one percentage

One return figure per name, and the denominator that earns it. Shipped server-computed on every
position row as `peak_car_sgd`, `return_span_days`, `return_pct` and `return_verdict`.

```
CAR(t)       = costed stock basis at t
             + Σ strike × contracts × multiplier over short PUTS open at t,   at latest FX
peak_car_sgd = max CAR(t) over the span
span         = first event → today if still held, else → last resolution
return_pct   = Net ÷ peak_car_sgd          — a LIFETIME total, never annualised
```

Six rules, each with its own gate in `tests/test_peak_car.py`:

1. **Collateral is released when the contract resolves — `close_date or expiry_date`.** A put
   that expired worthless carries `close_date: null`; reading it naively leaves the collateral
   locked forever and puts one name at +348.9%. The release lands *on* the resolution date, so
   an assigned put's shares (which arrive the day after) meet a one-day trough, never a
   one-day double count.
2. **Covered calls contribute nothing; open contracts do.** A call's collateral *is* the
   shares, already in the stock term. An unresolved contract runs `[open_date, today]`.
3. **The stock term is the transaction fold + the `cdp_cost_lot` attach + the corporate-action
   carry, replayed in date order.** CDP qty counts toward `buy_qty` — omitting it inflates one
   peak 3.5×. A sell fee never touches `buy_cost`.
4. **An equal-and-opposite pair of stock-moving legs is one internal move** and contributes no
   net units on any date, so *both* legs drop — from the unit count *and* from the costed
   share's entering units, since the same units were held once and paid for once. Matching is
   **leg-level, not ticker-level**: one name holds an internal round-trip *and* an external
   leg, and netting swallows the exit. Legs pair by size, and every unpaired leg is untouched.
   `cost_partition` deliberately still counts them: it answers "every unit that ever came
   through a door", which is what makes it sum to gross units in.
5. **The span ends today only if the position is still held** — units remaining or a contract
   open, the same test `options._is_open()` makes.
6. **Units nobody paid for contribute nothing** — the term carries the costed share,
   `costed(t) / units_in(t)`. Dated like every other term: an undated ratio lets a lot arriving
   uncosted in 2021 shrink capital that was at risk in 2020, which reads 25,096 on one name
   against a measured 33,461.

`return_verdict` is a second axis, independent of the Net's: `no_capital` where peak CAR is
zero (the return does not *exist* — undefined, not unmeasured), `caveat` where some entering
units are unknown (the numerator is an upper bound and the denominator a lower one, so the
error compounds) **or where there is no Net to divide at all**, else `ok`. Never `ok` beside a
null percentage — that is the one pairing a renderer branching on the verdict cannot survive. **`peak_car_sgd` is always a number**, a measured zero where
nothing was at risk; the verdict, not a null, is what a renderer branches on.

`peak_car_date` is deliberately **not** on the wire — nothing renders it, and a field with no
consumer is how a rule gets re-derived wrongly. `performance.ticker_car()` returns it for the
ledger audit.

**Not annualised, and no XIRR on the ticker detail page.** Across the 58 non-optioned legs
carrying an XIRR, lifetime and annualised return differ by a median 20 points and up to 367,
and two names read a negative rate beside a five-figure positive Net. Holdings keeps its XIRR
column (it pairs XIRR with a Net column, not a lifetime hero percentage) and `/api/return`'s
portfolio-wide `xirr_annualised` is untouched.

`tests/test_performance_live.py` holds the settled peaks to the ledger they were measured
against, and records the one name where this build and the spec's settled table disagree.
