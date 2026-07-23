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

### Net worth

**Net-worth snapshot**:
A dated record of all manual assets/liabilities plus the frozen live portfolio value, with FX
frozen at the snapshot date. Snapshots are forward-delta: each carries values forward from the
prior one unless overridden.
_Avoid_: balance, statement

**Catalogue**:
The single source of truth for which net-worth line items exist and whether each is auto-pulled
from statements or entered manually.
