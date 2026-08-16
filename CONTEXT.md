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

**Uncosted units**:
Units that landed in a position via a transaction whose price the source never recorded. They
count toward market value, but their presence makes a money-weighted return meaningless (there
is no cost to weight against), so it is suppressed.

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
