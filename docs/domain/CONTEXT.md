# Portfolio Tracker

A personal investment + spending tracker. Statement PDFs/CSVs are parsed to flat files
(`build/`), loaded into Postgres (`ingestion/`), and served as portfolio metrics
(`portfolio/`) to a React SPA. This glossary pins the domain terms the compute layer repeats;
it is a glossary only, not a spec.

## Language

### Identity & instruments

**Canonical ticker**:
The one exchange code a security is known by after collapsing renames (Cromwell→Stoneweg is
`CWBU`→`SET`). Applying the rename map is `canon`; the raw-symbol normaliser that strips
suffixes and paren-codes without renaming is `norm_ticker`.
_Avoid_: symbol, code (ambiguous about whether the rename is applied)

**Funding bucket**:
The pool a position is grouped into for cost purposes — `cash`, `CPF`, or `SRS` — derived from
the account. A security transferred between custodians inside the same bucket keeps one
position, so its original cost carries across.
_Avoid_: account (an account maps INTO a bucket; several accounts share one bucket)

**Position**:
The running state of one (funding bucket, security) pair: units held, cost, cashflows, income.
Building it up by replaying transactions in order is the **position fold**.
_Avoid_: holding (reserve for the current non-zero units specifically), lot

**Dated accumulator**:
A position's own record of what changed and *when*, kept beside the undated running totals it
mirrors: a **unit event** per unit change (signed quantity, plus whether the leg moved stock
rather than trading it) and a **cost event** per cost-basis addition (money paid; units bought on
normal buys, or the re-split cost-basis quantity after a switch rebase). A running
total answers only "where did this end"; reading an *intermediate* state of the fold — which peak
capital-at-risk and the corporate-action carry both need — requires a date to hang each change
on. Every series ends exactly where the scalar it mirrors ends.
_Avoid_: lot (a lot is a purchase the book identifies and sells against; these are the fold's own
arithmetic, dated), history (the ledger is the history — this is the fold's reading of it)

**Stock-moving leg**:
A unit change that moved stock rather than trading it — a custody transfer, a fund-switch
arrival, a gift. An equal-and-opposite *pair* of them is one internal move and contributes no net
units on any date, which is why a dated replay has to tell one from a trade.
_Avoid_: transfer (only some stock-moving legs are transfers, and only some transfers pair)

**Carry**:
A corporate action moving a closed position's cost onto its successor (C31 → 9CI, 0P00006FYT
→ 0P0001OOJG), as **dated** cost events at the dates the money was actually paid. It costs the
successor's **leg** — the pending arrivals in by the predecessor's close or, where none landed in
time, the first `switch_in` after it (a switch settles days later) — and nothing that arrives
after the leg. `rename`, `split`, `consolidation`, `merger` and `switch` carry; a `distribution`
does not.
_Avoid_: transfer (a transfer keeps one position; a carry joins two)

**Split carry**:
A carry from a predecessor with **more than one** `corporate_action` row, detected by that count
and nothing else. The whole cost lands on one successor and none on the others, so every unit on
both pages can be priced while the *total* is mis-attributed — an event-level doubt the cost
partition cannot express. Its **bound** is asserted, never computed: `lower` on the name the cost
went to (too much cost, so its Net and percentage are floors), `upper` on a sibling that took
units and no cost.
_Avoid_: caveat (a caveat is units with no cost; a split carry has cost in the wrong place)

**Emptied predecessor** (husk):
The position a carry emptied — units 0, cost carried away. Every rule reads it as a `hero` with a
Net of zero, so nothing may serve one: Holdings never lists it and `/api/holding` answers 404. Its
history is disclosed on the successor's page, through **provenance**.
_Avoid_: closed position (a closed position still has its own result; a husk's moved)

**Provenance**:
The disclosure a carried successor ships beside its verdict: predecessor ticker and name, action
type, carry date, carried amount in SGD, the **reachable** siblings it was split with, and the
bound. Owed on the exact 1:1 carry too — an exact number is not an accounted-for one when most of
the denominator has no visible origin on the page. Null on every name no carry reached.

**Consolidated ticker row**:
The Holdings table's fold of every position sharing one canonical ticker into a single row — the
only place the app answers "how much of this name do I own, across every bucket". Units, cost,
market value, P/L, dividends and option premiums sum; price and currency pass through (one
security, one lookup); average cost pools as `Σcost_basis ÷ Σunits`, which is *exact* rather than
approximate because cost basis is average cost × units. The cost partition folds by addition —
each leg's entering units are its own — with `unknown_pct` recomputed over the merged counts
rather than averaged. **Derived at render, never stored and
never served** — Holdings folds it client-side — so it is a presentation of several positions and
never itself a Position. Not the **ticker fold** below, which is the server's, narrower, and the
one the detail page reads; the two stay separate folds on purpose (#143 §3). XIRR is deliberately not folded: an IRR over merged cashflows cannot be
averaged from its parts, so a consolidated row of two positions shows no return rather than a
plausible one.
_Avoid_: position (the fold's *input* is positions, and the whole point is that this is not one)

**Leg**:
One funding bucket's position inside a ticker — one column of the bucket split, and one stacked
block of it below 640 (#160). Only a position
that holds units, had money go in, or had income come out is a leg; the rest is noise, or an
emptied predecessor whose cost carried to its successor.
_Avoid_: bucket (the pool, not this ticker's position in it); not a **stock-moving leg**, which is
a unit change, nor an option leg

**Ticker fold**:
A ticker's legs folded server-side into one whole-ticker summary plus its legs, for the detail
page. A ticker with no legs has no ticker fold at all.
_Avoid_: consolidated ticker row (Holdings' client-side fold, wider and with different fields)

### Cashflows & their classification

**External flow**:
A unit change that is real money in or out (a buy, a sell, a cash rights issue) — the only kind
that belongs in a return's cashflow series. Also called a **contribution** when signed as money in.
_Avoid_: transaction (a transaction may be an external flow, a return-in-kind, or neither)

**Return-in-kind**:
A unit change that is part of the *return*, not an external contribution: units received free
(stock dividend, bonus, scrip). Kept inside the return, never in the cashflow series.

**Cost-in-kind**:
Units redeemed to pay a fee (Endowus). No cash leaves the investor, so the market-value drop
already carries the cost — booking a cash outflow too would charge the fee twice.

**Cost partition**:
The split of a position's **entering units** — gross units in, so a sale subtracts nothing —
into exactly three **conditions**, summing to that total. A boolean cannot say the thing that is
actually true of C38U: 500 of its 6,700 units entered with no recorded cost. Shipped nested
(`cost_partition`) so the counts cannot drift apart among ~25 flat siblings, with `unknown_pct`
pre-computed. The three:

- **Costed** — real money is recorded against these units: a priced trade, a CDP cost lot, a
  predecessor's cost carried by a corporate action, or a transfer in whose paired transfer out
  sits in the same position (the cost never left).
- **Free** — they cost nothing, and that is measured, not assumed. Free units carry a *price*,
  not only a count: their cost basis is `0.0`, never null.
- **Unknown** — the book does not know. The polarity is to refuse rather than invent a free lot:
  the partition never counts one as free. What a Net may claim from that doubt is **Net verdict**
  (`net_verdict` in `portfolio/performance.py`).

`cost_known` is this partition read as a boolean: false only when *every* entering unit is
unknown. Not "no unknown units" — a name with some cost still answers "did I make money on
this"; only a name with none has to refuse.
_Avoid_: uncosted units (the retired boolean-era term; it named only the unpriced-trade slice of
`unknown` and has left the wire), cost-unknown position (a position is rarely all-or-nothing)

**Cost annotation**:
The free/transferred distinction, per transaction, defaulting to `unknown`. Every unpriced
carry-in in the book shares one action string, which covers a corporate-action carry, a real
in-specie distribution and two windfalls at once — so neither the action nor the account can
decide it, and the knowledge lives beside the code (`portfolio/cost_annotations.py`) rather than
in the ledger, which has nowhere to put it. Scope is `open/transfer_in` and zero-priced
`corp action`; `gifted stock in` and `bonus issuance` are mechanical and need none.
_Avoid_: per-security override (rejected — it breaks the day one ticker holds both a gift lot
and a real transfer-in)

**Cell state**:
Which of **four** things a missing number means. The rule is *has this stream ever existed*, not
*is the number zero* — a closed position keeps its `Realised 0` while a name that never traded an
option loses the row outright.

- **Omitted** — the stream has never existed for this ticker; the row is absent.
- **Zero** — the stream exists and measured zero.
- **Impossible** — structurally cannot exist for this leg; renders `—`.
- **Not known** — the stream exists but is unmeasurable; renders in words.

`null` therefore means **exactly one** of these per field, and the contract says which:
`options_pl_sgd` null means *omitted* (cash received is always known, so an options stream can
be absent but never unmeasurable) — as shipped it also covers an optioned name whose every leg
is still open, which the runbook's "four cell states" records as the one state still short;
`realised_pl_sgd`, `unrealised_pl_sgd`, `stock_pl_sgd`, `avg_cost` and both cost-basis fields
null mean *not known* (units always entered, so those can be unmeasurable but never absent).
`income_sgd` belongs on the first line by #143 §6 and does **not** ship that way yet — it is
still `0.0` on a name that never paid, so nothing can tell
*never paid* from *paid zero*.
_Avoid_: "n/a" (it reads as *not applicable*, i.e. impossible, on cells that mean *not known*;
the detail page says the words instead since #156), empty (says which pixels
are blank, not which of the four facts is being stated)

**Stock P/L**:
`realised + unrealised` — the whole result on the shares themselves, dividends and option
premiums excluded. Identically `proceeds − buy_cost + mv`, which needs no split of the cost
between the units sold and the units held: the **pair's sum is sound while neither member is**,
which is what lets a name the partition doubts still show a Net that is arithmetically exact.
Ships on every row (`stock_pl_sgd`), not only the doubtful ones — a field that appears only
where the split fails is a field nobody can add up. Null only on a leg whose every unit is
unknown *and* whose name refuses; under a caveat that leg still ships `stock_pl_sgd`.
Direction: `net_verdict` in `portfolio/performance.py`.
_Avoid_: total P/L (that is stock P/L *plus* dividends and premiums — the Net)

**Net**:
`realised + unrealised + income + options` — or `stock P/L + income + options` where a caveat
collapsed the pair — summed from the components **as shipped**, with zero tolerance. Each component
is rounded once, where it ships; Net never rounds independently beside them, which is how `pl_sgd`
drifts a cent. Per leg on the wire (`net_pl_sgd`), so bucket columns add up to the name; null on
every leg of a name whose Net verdict is `refuse`, because there is no partial Net under any name.
_Avoid_: `pl_sgd` (the older, independently rounded spelling other endpoints still read), total P/L

**Net verdict**:
What the Net can claim, read from a ticker's **summed** cost-partition counts: `refuse` (nothing
costed, something unknown), `caveat` (some costed, some unknown) or `hero` (nothing unknown).
Summed, not per-leg: a costed-only leg beside an unknown-only leg is a caveat, not a refusal.
One input is not a count: a **split carry** can make it `bounded`, never overriding `refuse`,
and `bounded` keeps the cost-basis tiles a caveat nulls. Which carry overrides, and which way
the Net runs, is `net_verdict` in `portfolio/performance.py`; the page reads that in
`web/src/modules/portfolio/bound.js`. **Not `cost_known`** — that flag is false on
a caveat's all-unknown leg and on a refusal alike.
_Avoid_: return verdict (a different axis — AAPL is hero-on-Net and no-capital-on-return at once)

**Breakeven price**:
The native-currency price at which a column's **Net** reaches zero, per leg and per ticker
(`breakeven_price`, quoted at 4dp like `avg_cost`). Defined against the Net and **not** against
avg cost: avg cost is the price that undoes the unrealised column alone, so reading a breakeven
off it asks the market to pay a second time for dividends and realised gains already banked (on
UD1U, a breakeven of 0.3564 under an avg cost of 0.4166). Null means there is no such price — a
refused Net, nothing held, or units that cannot be costed — a negative one is a real answer and
is never clamped, and a `bounded` Net bounds it the other way, since a floor on the Net is a
ceiling on the price. The arithmetic, the three nulls and the FX rate it is solved at are
`docs/runbooks/BACKEND.md`'s.
_Avoid_: break-even (unqualified — it is read as avg cost, which is a different price), avg cost

### Returns

**Peak capital-at-risk (CAR)**:
The most a name ever had exposed at once: the **costed stock basis** at a moment plus the
collateral locked behind short **puts** open at that moment, converted at latest FX, maximised
over the position's span. Covered calls contribute nothing — their collateral *is* the shares,
already in the stock term. Every term is read at the date it applies, including the costed
share, so a lot that arrives uncosted years later cannot shrink capital that was genuinely at
risk before it. Where nothing was ever paid for and no collateral was ever locked it is a
**measured zero**, not a null.
_Avoid_: cost basis (a peak is a maximum over a span, not a current holding), invested (total
money ever deployed, which double-counts capital that was recycled)

**Peak-CAR return**:
`Net ÷ peak capital-at-risk`, a **lifetime total** and never annualised. Annualising a ratio
whose denominator is a *peak* asserts the capital sat at peak for the whole span, when it may
have touched that on a single day — so the figure is a lifetime total return on worst-case
exposure and is always rendered with its span beside it. Whole-ticker only. There is no minimum
span and no materiality floor.
_Avoid_: return (unqualified), annualised return (it is deliberately neither)

**Span**:
The time a peak-CAR return is measured over: the days the ticker was **held** — units in some
leg or a contract open — counted once where holdings overlap and not at all in a gap between
them. A still-held position runs to **today**; a closed one stops the date the last unit left
or the last contract resolved. Units are dated by trade date wherever a CDP cost lot gives one,
not by the month-end statement that reported them. "Always today" overcharges closed names;
"always last activity" undercharges open ones; "first date to last date" bills the gaps.

**Return verdict**:
What the percentage can claim, on its own axis rather than the Net's: `ok`, `caveat` (some
entering units are unknown, or no Net exists for the division; direction: `net_verdict` in
`portfolio/performance.py`, read for both sides of the ratio in
`web/src/modules/portfolio/bound.js`), or `no_capital` (peak CAR is zero, so the return does not exist —
undefined, not unmeasured). The **verdict**, not a null, is what decides how the figure renders.
_Avoid_: net verdict (a different axis — one name can be hero-on-Net and no-capital-on-return
at once)

**Money-weighted return (XIRR)**:
The internal rate of return over a position's dated cashflows plus its current market value as a
terminal inflow. Sensitive to contribution timing. Computed per position and portfolio-wide.
**Not on the ticker detail page** — an annualised rate and a lifetime return are different
claims and no label reconciles them: across the 58 non-optioned legs carrying one, the two
differ by a median 20 points and up to 367, and two names read a negative rate beside a
five-figure positive Net. Holdings keeps its column, because it pairs XIRR with a Net column
rather than with a lifetime hero percentage.
_Avoid_: IRR, return (unqualified)

**Time-weighted return (TWR)**:
The chain-linked product of daily sub-period returns with external flows removed, so
contribution timing is stripped out and the number is comparable to an index. Portfolio-wide only.
_Avoid_: return (unqualified)

### Income

**Dividend attribution**:
Assigning a dividend to the units that earned it — *units held at pay_date*, replayed from the
transaction ledger, with an *implied rate* (gross ÷ units) when a statement omits it. This is the
cash-landed view. Return math deliberately folds dividends on **ex_date** instead (the day the
price drops); the two dates are a real distinction, not a discrepancy.
_Avoid_: dividend date (name the basis — pay_date or ex_date — explicitly)

**Income**:
Dividends received, the third term of the Net. On the wire as `income_sgd`, per leg. **Known
defect**: the fold sums the native `gross` amounts and converts once at the *security's* rate, so
a name paid in a second currency is converted at the wrong one — UD1U is short 5,134.49 and SET
307.08. It reaches every Net in the app; the runbook has the table and the fix.
_Avoid_: dividends (the rows are dividends; this is their folded SGD total), yield

### Money

**Native / SGD conversion**:
Every value is computed in the security's native currency, then converted to SGD for
aggregation. The single policy: SGD (or absent currency) is 1:1; a present foreign rate is used;
a *missing* foreign rate fails loud rather than silently converting at 1.0. One figure runs the
other way — the **breakeven price**, an SGD shortfall quoted back in native — and it must divide
by the very rate its row's SGD figures were converted at, never a fresher read, or it stops
zeroing the Net beside it (`docs/runbooks/BACKEND.md`).
_Avoid_: currency conversion (name the direction — native→SGD everywhere but that one figure)

### Spending

**Spend**:
The positive magnitude of a *counted* cash outflow. Transfers, card-bill payments, and income
are excluded from every spend metric though they remain inspectable.
_Avoid_: expense, cash-out, outflow (an outflow may be an excluded transfer)

**Unclassified spend**:
Counted spend whose `category` is NULL — real money, no bucket yet. It is a category's worth of
rows, not a data error, so every read shape carries it rather than filtering it out. The compute
layer names it **Uncategorized** where the name has to be a key (`trends()`, whose group strings
are the series keys the chart reads); `summary()` leaves the NULL as a value and the frontend
names it at render. One word, two places, because only one of them can hold a null.
_Avoid_: uncategorised (the app spells it with a z), missing, unknown

**Date window**:
The `frm`/`to` range a caller passes to `summary()`, `trends()` or `transactions()` — a filter
the reader chooses, and the only thing "window" meant before the spend-trend window existed.
_Avoid_: window, unqualified (see below — the two are not interchangeable)

**Spend-trend window**:
The months the spend-trend chart may draw, derived by `window()` from source coverage rather
than chosen: `[start, last drawable month]`, where **start** is the first month beginning after
the latest first-transaction among *material* sources and a month is **drawable** when it is at
or after start, is not the month holding `MAX(txn_date)`, and every material source reported in
it. Non-drawable months inside it are **gaps**. It is a rule, not a control — the grounds are
data defects, so there is deliberately no UI to widen it.
_Avoid_: window, unqualified; date range; the chart window

**Material source**:
A statement source whose dated counted spend is at least 1% of all dated counted spend. Decides
which sources a month must have heard from before it is drawable. **First-appearance only** —
a source that stops reporting never shortens the window, because the rule exists to exclude
months a source had not started yet, not months it had finished. Immaterial sources are carried
in the payload and flagged, never filtered out.
_Avoid_: primary source, main account, significant source

### Net worth

**Net-worth snapshot**:
A dated record of all manual assets/liabilities plus the frozen live portfolio value, with FX
frozen at the snapshot date. Snapshots are forward-delta: each carries values forward from the
prior one unless overridden.
_Avoid_: balance, statement

**Catalogue**:
The single source of truth for which net-worth line items exist and whether each is auto-pulled
from statements or entered manually. Its flags reach **line items only** — the frozen portfolio
value is not a catalogue row — so every flag-excluding metric excludes only the catalogue side of
what its name implies.

**Band**:
The partition of the catalogue the composition chart stacks — derived from the item flags by
precedence (`is_housing` → `is_cpf` → `is_liquid` → else), never stored. A stored band column
would be a fourth grouping free to disagree with the three that exist. Four values — `housing`,
`cpf`, `cash`, `srs` — plus a synthetic `portfolio` that is not a catalogue item at all and is
synthesised from the snapshot's frozen portfolio value.
_Avoid_: group (frontend form furniture, deleted), category (that is spending's)
