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

**Consolidated ticker row**:
The Holdings table's fold of every position sharing one canonical ticker into a single row — the
only place the app answers "how much of this name do I own, across every bucket". Units, cost,
market value, P/L, dividends and option premiums sum; price and currency pass through (one
security, one lookup); average cost pools as `Σcost_basis ÷ Σunits`, which is *exact* rather than
approximate because cost basis is average cost × units. The cost partition folds by addition —
each leg's entering units are its own — with `unknown_pct` recomputed over the merged counts
rather than averaged. **Derived at render, never stored and
never served** — no endpoint returns one — so it is a presentation of several positions and never
itself a Position. XIRR is deliberately not folded: an IRR over merged cashflows cannot be
averaged from its parts, so a consolidated row of two positions shows no return rather than a
plausible one.
_Avoid_: position (the fold's *input* is positions, and the whole point is that this is not one)

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
actually true of Q01: 17,000 of its 68,000 units entered with no recorded cost. Shipped nested
(`cost_partition`) so the counts cannot drift apart among ~25 flat siblings, with `unknown_pct`
pre-computed. The three:

- **Costed** — real money is recorded against these units: a priced trade, a CDP cost lot, a
  predecessor's cost carried by a corporate action, or a transfer in whose paired transfer out
  sits in the same position (the cost never left).
- **Free** — they cost nothing, and that is measured, not assumed. Free units carry a *price*,
  not only a count: their cost basis is `0.0`, never null.
- **Unknown** — the book does not know. The polarity is to refuse rather than invent a free lot.

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
be absent but never unmeasurable); `realised_pl_sgd`, `unrealised_pl_sgd`, `stock_pl_sgd`,
`avg_cost` and both cost-basis fields null mean *not known* (units always entered, so those can
be unmeasurable but never absent). `income_sgd` belongs on the first line by #143 §6 and does
**not** ship that way yet — it is still `0.0` on a name that never paid, so nothing can tell
*never paid* from *paid zero*.
_Avoid_: "n/a" (it reads as *not applicable*, i.e. impossible, on cells that mean *not known* —
the wording the detail page still uses, which #158 replaces with words), empty (says which pixels
are blank, not which of the four facts is being stated)

**Stock P/L**:
`realised + unrealised` — the whole result on the shares themselves, dividends and option
premiums excluded. Identically `proceeds − buy_cost + mv`, which needs no split of the cost
between the units sold and the units held: the **pair's sum is sound while neither member is**,
which is what lets a name the partition doubts still show a Net that is arithmetically exact.
Ships on every row (`stock_pl_sgd`), not only the doubtful ones — a field that appears only
where the split fails is a field nobody can add up.
_Avoid_: total P/L (that is stock P/L *plus* dividends and premiums — the Net)

### Returns

**Money-weighted return (XIRR)**:
The internal rate of return over a position's dated cashflows plus its current market value as a
terminal inflow. Sensitive to contribution timing. Computed per position and portfolio-wide.
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

### Money

**Native / SGD conversion**:
Every value is computed in the security's native currency, then converted to SGD for
aggregation. The single policy: SGD (or absent currency) is 1:1; a present foreign rate is used;
a *missing* foreign rate fails loud rather than silently converting at 1.0.
_Avoid_: currency conversion (name the direction — always native→SGD)

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
