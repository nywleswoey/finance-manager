# Backend — Phase 0/1 (DB foundation + load)

> **Live vs historical**: this file is a Phase 0/1 build write-up from early in the project.
> The stack description and cost-partition notes below are still accurate; the "Quick start"
> command has been corrected to match the current `Makefile`. For current setup/ingest
> instructions, see the root [README.md](../../README.md).

Implements [PLAN.md](../archive/PLAN.md) Phase 0 (Postgres + schema + seed) and the first half of
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
make setup          # db-up + migrate + seed + ingest + prices  (idempotent; see `make ingest` for load-only)
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
into the cash-bucket position **when that position itself holds a CDP `txn` row**. Positions
still come from the authoritative CDP statements; `alloc_by_account()` gives the per-account MV
split for charts.

CDP cost is matched at **position** level, not per row — a CDP `txn` row is a month-end
statement diff that routinely aggregates several trade-dated cost lots, and matching per row
invents shortfalls that do not exist. `performance.cost_partition` carries the detail.

The CDP-row precondition is what #146 added: a ticker held only at a broker (H78, at FSM) can
still carry a `cdp_cost_lot` row, and attaching it by ticker alone counted the broker's own
priced buy a second time. Such a lot is now dropped rather than attached — the cash leg keeps
only the broker's cost. A dropped lot is a ledger defect, not a steady state, so
`scripts/audit_ledger.py`'s tier-3 invariant *cost lots only on tickers CDP holds* names every
ticker in that shape.

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
can render each differently. The rule is *has this stream ever existed*, not *is the number zero*.
The ticker detail page renders all four since #156 — `not known` in words, never a glyph and never
a tooltip; #158 lands the prose the hero slot itself needs.

| state | meaning | intended rendering |
|---|---|---|
| omitted | the stream has never existed for this ticker | row absent |
| `0` | the stream exists and measured zero | `0` |
| `—` | structurally impossible | `—` |
| not known | the stream exists but is unmeasurable | words |

So `null` means **exactly one thing per field**. `income_sgd` is named on the first line by
#143 §6 and is **not** done: it still ships `0.0` on a name that never paid a dividend. The detail
page answers the question off the dividend rows it already has — no rows and a zero is a stream
that never existed — which is a render-side workaround for a wire-side gap, not a substitute for
closing it: every other consumer still cannot tell *never paid* from *paid zero*.

### `income_sgd` converts once, at the wrong rate, on a name paid in two currencies

**Open defect, unfixed, and now on more surfaces than before.** `_accumulate_positions` adds each
dividend's `gross` to `p["income"]` as a **native amount with its currency discarded**
(`performance.py:1120`), and `_build_row` converts that sum once at the **security's** rate
(`:1038`). A dividend paid in a currency other than the security's is therefore converted at the
wrong rate — or, for an SGD-quoted security, not converted at all.

Two names are live, and the error is not a rounding one:

| ticker | currencies | `income_sgd` ships | true SGD | short by |
|---|---|---:|---:|---:|
| UD1U | EUR + SGD | 12,735.80 | 17,870.29 | **5,134.49** |
| SET | SGD + EUR | 10,653.40 | 10,960.48 | **307.08** |

It reaches `net_pl_sgd`, so Holdings' Net, `/api/performance`'s groups and the ticker detail
page's hero are all understated on those two names by those amounts. The detail page used to be
the one surface that escaped it, because it re-summed the rows' own `gross_sgd` client-side; #143
§1 kills that reduce ("the frontend renders and never derives"), and keeping it would have put a
second dividend total in the app and left the reconciliation ledger not adding up to its own Net.

**The fix is one place**: accumulate the SGD amount per dividend, at the dividend's own currency's
rate, rather than converting the native sum. It is deliberately not made here — it moves
`/api/positions`, `/api/performance` and `/api/holding` together and wants its own ticket with its
own numbers. **Neither name is a captured fixture**, so no gate in either suite sees it; a capture
that adds one would be the cheapest way to make this fail loudly.

- **`options_pl_sgd` null means no leg of this ticker has resolved yet** — a never-optioned ticker
  omits the row rather than carrying a permanent `Options 0` line (61 of 73 legs live). That is
  one state short of §6's *never existed*, and knowingly so: the field is attached from
  `options.realized_by_ticker()`, which keys only on `_closed_trades()`, so an optioned name whose
  every leg is still open has no key and ships null too. A name with at least one resolved leg
  ships its number even when that number is zero. Until a zero is emitted for the
  optioned-but-unresolved case, **do not read null as *never optioned***, and the field's two
  readers differ on purpose: `Holdings.jsx` renders `—`, because a holdings row cannot tell the
  two apart, while `SecurityDetail.jsx` zero-fills to `S$0`, because the legs are listed on the
  same page (`web/tests/security-detail-options.spec.js` pins that). Dividends and options can be
  *absent* but never *unmeasurable*: cash received is always known. The `—` state is leg-level —
  a non-cash leg of an optioned name — and is reconstructed where the ticker's own option book is
  in view, not here.
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

```text
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

## Two verdicts on two axes, and Net on the wire

The server ships the Net and what it can claim, so a page renders them rather than composing them
from `cost_known === false` plus a fan of nulls. Both land on every position row:

```text
net_verdict:    "hero | caveat | refuse | bounded"   whole-ticker, rides every leg (bounded: below)
return_verdict: "ok | caveat | no_capital"    whole-ticker, rides every leg (above)
net_pl_sgd:     per leg — a bucket column adds up on its own, and the columns add up to the name
```

**Two enums, because the axes are independent.** AAPL is hero on Net *and* `no_capital` on return
(`unknown == 0` grants the hero, peak CAR 0 kills the percentage); ASTREA6B fires `refuse` and
`no_capital` together. A combined enum has no value for either.

`net_verdict` reads the ticker's **summed** partition counts:

```text
refuse   ⟺  costed == 0 ∧ unknown > 0
caveat   ⟺  costed > 0  ∧ unknown > 0
hero     ⟺  unknown == 0
```

- **Summed, not per-leg.** #130's `every()` rule is superseded: leg A costed-only beside leg B
  unknown-only is `refuse` by `every()` and `caveat` by summed counts, and one bucket with real cost
  is a Net that should stand. Zero-instance today; gated in `tests/test_net_verdict.py`.
- **`cost_known` is not the signal.** It is false on the divergence case's leg B (a caveat) and on
  a refusal alike. Of the six positions #143 §8 measured it false on — ASTREA6B, AAPL, HMN, AMZN
  and the emptied predecessors C31 and 0P00006FYT — only ASTREA6B refuses.
- **Free units are not costed units.** A gift beside an unannotated carry-in refuses.

`net_pl_sgd` is the **sum of the components as shipped, with zero tolerance**:

```text
net_pl_sgd  ≡  realised_pl_sgd + unrealised_pl_sgd + income_sgd + options_pl_sgd
            ≡  stock_pl_sgd + income_sgd + options_pl_sgd     (where a caveat collapsed the pair)
```

- **Rounding policy.** Every component is computed at full precision and rounded **once**, where it
  ships; Net adds the shipped figures. It is never rounded independently beside them — that is
  `pl_sgd`, and it is §14's real cent, which exists only against `pl_sgd + options_pl_sgd`, a
  pairing no page displays. (§14 named UD1U, 00468, 01310, 01523 and 00101, reading `pl_sgd`
  against its own components; against Net — options included — today's book drifts on 00010,
  BABA, PLTR, RIVN and 00788.)
- **`refuse` ships `null`** on every leg — including a leg of a refusing ticker whose own components
  are known. There is no partial Net on the wire under any name.
- **A caveat nets every leg.** A leg whose every unit is unknown, inside a ticker that does not
  refuse, keeps `stock_pl_sgd` (its unknown units read as free — the upper bound the caveat already
  declares, exactly as Q01's partly-unknown leg does). `stock_pl_sgd` is therefore null only where
  the leg is all-unknown *and* the name refuses.
- **Known gap, zero-instance: `/api/performance`'s group `net_pl_sgd` is not this field.**
  `rollup()` is untouched and still adds a leg's `stock_pl_sgd` only where `cost_known` is true,
  so in the divergence case the group Net drops leg B while the row Nets include it. No live
  ticker has that shape; the group-vs-ticker identity belongs to #155, which should close it.

**`return_pct` divides the Net that ships** — `Σ net_pl_sgd` over the ticker — and #152's inline
`Σ pl_sgd + Σ options_pl_sgd` is gone: one numerator, one definition. A refused Net beside real put
collateral reads `return_verdict: "caveat"` with `return_pct: null`, never `ok`. Against the live
book no existing field on any row moved.

## `GET /api/holding?ticker=X` — the whole-ticker contract

The detail page's one read, covering the ticker across **every** funding bucket (#153, spec #143
§2–§3, §16–§17). **There is no `bucket` parameter** — dropped, not made optional; a stale
`&bucket=` is ignored, not honoured. The hardcoded bucket→accounts literal is deleted: bucket
attribution is the join onto `account.funding_bucket`, so an account the literal never listed is
no longer silently missing from the page.

```text
{ as_of, fx_as_of, summary, buckets: [leg, …], transactions: [...], dividends: [...], options: [...] }
```

- **Two dates.** `as_of` is `valuation_as_of()` verbatim — `/api/positions`' date, so both pages
  state the same freshness for the same market value. `fx_as_of` is `max(fx_rate.date)`
  (`portfolio.db.fx_as_of`), what "at latest FX" is actually as of.
- **Computation is `performance.fold_ticker`**, pure; the handler fetches (`ticker_ledger`) and
  enriches the tables. The three folds (`fold_positions`, `rollup()`, Holdings' `mergeTicker`) stay
  three.
- **`summary`** carries identity, position, the components, `net_pl_sgd` / `net_verdict`, the four
  return fields, `cost_partition` (counts summed, `unknown_pct` recomputed), `invested_*`,
  `fees_sgd` and `cost_known` (AND). **Absent, not null:** `xirr`, `simple_return`, `pl_sgd`, and the
  singular `bucket` / `status`.
- **`buckets`** is a list, largest MV first, of `{bucket, status, units, avg_cost, realised_pl_sgd,
  unrealised_pl_sgd, stock_pl_sgd, income_sgd, options_pl_sgd, net_pl_sgd}`. Every key but the two
  labels is a summary key. A single-bucket ticker ships one element.
- **Fold rules.** Figures sum. `realised` / `unrealised` / `stock_pl` / `cost_basis_*` /
  `invested_sgd` are null if **any** leg's is — the spec's "null only when every leg is null" was
  written when a closed leg shipped null; since #149 a leg's null means only *not known*, and a
  partial sum would ship a Realised + Unrealised short of the Stock P/L beside it. `options_pl_sgd`
  sums the legs that have the stream and is null where none does. `avg_cost` is `Σ cost_basis_native
  ÷ Σ units` (D05 → the exact weighted average); a single leg passes its own through, which is also
  the only answer a closed one has. Several legs holding zero units between them ship null — zero
  instances today.
- **Legs.** Kept if `units > 1e-6 or invested_native or income_native or cost_partition.unknown > 1e-6`
  (`performance.is_leg`, `/api/positions`' drop rule). **No leg kept → 404**, which is also the
  emptied predecessor's (C31, 0P00006FYT) answer: a sum over nothing would ship
  `net_pl_sgd: 0, net_verdict: "hero"`. `/api/positions?closed=true` drops by the same `is_leg`, so a
  404 is never a ticker Holdings lists. 0P00006FYT, emptied since its switch carry fires (#164), 404s
  the same way.
  **The fourth clause is the refusal (#155).** `invested_native: 0.0` means two different things —
  no money went in, or the amount is not recorded — and the first three clauses read the second as
  the first. ASTREA6B's 15,000 units entered and left at an unrecorded cost, so it failed every
  entry point at once: no Holdings row, and a 404 from `/api/holding`. Unknown and zero must not be
  the same thing in the rule that decides whether the reader sees the row. A husk's partition is
  entirely `costed`, so §13's ruling is untouched; measured on the live book, the clause adds
  exactly one row.
- **Tables.** Transactions and dividends carry `bucket` on every row, single-bucket names included;
  CDP rows from `cdp_cost_lot` take theirs from the account table by name. The running balance runs
  across buckets. `options` is fetched unconditionally, carries **no** bucket, and each trade ships
  `realised` — `options._is_open()`'s answer, not its inputs (also on `/api/options-trades`).
  **Stated assumption, named trigger:** options are cash-bucket by construction (Tiger Prime); if one
  is ever booked elsewhere, the table needs a bucket column and `realized_by()`'s hardcoded `cash` is
  a bug.
- **Premiums sit inside the split** — a cash-column `Options` line — so bucket Nets add up to the
  hero. The distortion (cash Net not reconciling to its own stock cost) needs a ticker both optioned
  and multi-bucket; there are none.

Gated in `tests/test_fold_ticker.py` (pure), `tests/test_holding_endpoint.py` (TestClient, stubbed)
and `tests/test_holding_pg.py` (the ledger SQL and `fx_as_of`). Frontend: the only caller and the
fixture key lose `&bucket=`; the fixture itself is recaptured by #155.

## The dated carry, `bounded`, and provenance

`_carry_corporate_actions` moves a closed position's cost onto its successor — emptying the
predecessor — as **dated** cost
events, so a successor's capital counts as at-risk from when it was actually paid. `compute()`
hands the fold **every** `corporate_action` row; the fold carries along `CARRY_TYPES` (`rename`,
`split`, `consolidation`, `merger`, `switch`) and counts a split over all of them.

**The carry's leg (#164).** A carry costs the successor's pending arrivals in by the predecessor's
close — or, where none landed in time, the first `switch_in` after it, however many settlement
days later (0P00006FYT redeemed 2023-04-24; 0P0001OOJG's switch-in landed 2023-04-27). Anything
pending after the leg stays `unknown`. No tolerance window, so no unargued N.

**`bounded` — a split carry (#143 §12).** A predecessor with more than one `corporate_action` row
(`split_predecessors`, the `HAVING count(*) > 1` query over data — exactly one live: C31, split to
9CI and distributed in specie to C38U) puts its whole cost on one successor and none on the other.

```text
refuse   ⟺  costed == 0 ∧ unknown > 0
bounded  ⟸  a split carry reached the name — overrides hero; overrides caveat only where the
            carry's direction agrees with it (upper); never refuse
caveat   ⟺  costed > 0  ∧ unknown > 0
hero     ⟺  unknown == 0
```

| | cause | tiles | direction |
|---|---|---|---|
| `caveat` | some units have **no** cost | **null** | always upper |
| `bounded` | the **total is mis-attributed**, and the partition does not point the other way | **kept** | lower *or* upper |

- **Tiles follow the partition, not the verdict**, so 9CI keeps `avg_cost: 3.73` while C38U — the
  one name carrying both doubts — still nulls its cost-basis family and reads `return_verdict:
  caveat` on its unknown 500.
- **`bound` is one claim over both axes**, not a third axis: the return axis keeps its own three
  values.

**`provenance`** ships on every row — null unless a carry reached the name, and whole-ticker like
the verdict, so it rides every leg:

```json
"provenance": {
  "from_ticker": "C31", "from_name": "CapitaLand Ltd", "type": "split",
  "carried_on": "2021-09-28", "carried_sgd": 10071.0,
  "split_with": [{ "ticker": "C38U", "units": 417.0 }],
  "bound": "lower"
}
```

- `carried_on` is the successor's own leg date; `carried_sgd` is `0.0` on a sibling that took
  units and no cost, at latest FX otherwise.
- `split_with` names only siblings Holdings **lists** — never a page that does not exist.
- `bound`: `lower` on the name the cost went to, `upper` on a sibling, `null` on a single-successor
  carry. **Asserted, not computed** — nothing in the book bounds the magnitude.
- Ships on the exact 1:1 carry too (0P0001OOJG): an exact number is not an accounted-for one.
- `/api/holding`'s `summary` carries it (read off the first leg, **omitted** when null), so the detail page
  renders its `≥` / `≤` on the figures and the carry sentence from the wire, not from a second query.

Live: 9CI `bounded`/lower, C38U `bounded`/upper, 0P0001OOJG `hero` with `bound: null`. No numeric
field on any row moved.

**The emptied predecessor (#143 §13).** A husk fails `is_leg` — `/api/positions`' listing rule —
so Holdings never lists one, and `/api/holding` answers **404** by the same rule (`fold_ticker`
keeps no leg) rather than a summary that would read `hero` with a Net of zero. ASTREA6B used to
fail it too (#153) and no longer does (#155): it is a refusal, not a husk, and the rule now asks
about unknown entering units as well — so it lists with `net_pl_sgd: null` and its page is served.
`is_emptied_predecessor` names the husks among the remaining misses
(`tests/test_holding_husk.py`, `tests/test_performance_live.py`). No verdict value, no successor
link. **Trigger:** if the detail page gains a URL, a bookmark or a search box, a husk becomes
reachable and a redirect to the successor is the obvious answer.

`tests/test_performance_live.py` asserts the one-row `HAVING count(*) > 1` result as an
**invariant**, and that the fold's bounded names are exactly that row's successors.
