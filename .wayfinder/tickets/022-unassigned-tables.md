---
id: 22
title: The four tables no ticket ever assigned
type: grilling
status: open
assignee:
blocked_by: []
parent: map-mobile-responsive
---

## Question

Which pattern do the four tables that fell through the inventory take?

[Wide numeric tables on a phone](013-wide-tables-on-phone.md) inventoried **13** tables and
[The "doesn't break" floor](017-editors-dont-break-floor.md) found **5** more in the editors, for 18.
`grep -rn "<table" web/src/modules` returns **22**. The four nobody has looked at:

| table | cols | shape |
|---|---|---|
| `portfolio/Performance.jsx:18` | **9** | per-group performance: Capital, Current Value, Unrealised P/L, Realised P/L, Dividends, Options, Net P/L, Return |
| `portfolio/SecurityDetail.jsx:102` | **9** | options history for one security: Type, Qty, Strike, Opened, Closed, Premium, Buyback, Outcome, P/L |
| `spending/Overview.jsx:33` | 4 | Top Line Items — Category, Line item, Spend, % |
| `spending/ByCategory.jsx:168` | ~4 | the drilldown sub-table; **headerless** (no `<thead>`), `panel2` background, inline 12px cells |

The first two matter: **9 columns each, both in fully-responsive views**, and neither has ever been run
through 013's test. `Performance` is an entire Portfolio tab that no ticket in the map has examined.

Decide:

1. **Apply 013's test to each** — *does this table exist so you can compare a number down the column,
   or so you can read one row at a time?* Compare → A, read → B, under ~5 columns → neither. The
   mechanical reading is A for `Performance` (comparing returns across groups is its whole purpose) and
   B for `SecurityDetail`'s options history (a contract ledger read one row at a time) — but 013 itself
   flagged the heavy-card case as its least-certain call for `Options.jsx:71`, which is the *same shape*
   at 11 fields. Confirm or overturn rather than inheriting.
2. **The headerless drilldown sub-table.** Both of 013's patterns assume a header — A keeps the sticky
   `th`, B passes its job to group-header rows. `ByCategory.jsx:168` has no `<thead>` at all, and it is
   nested *inside* another table's expanded row. Decide whether it needs anything.
3. **Whether `spending/Overview.jsx:33` is really "unchanged".** It is 4 columns, so 013's third bucket
   applies — but [The tablet tier](018-tablet-tier.md) measured that bucket at **419px min-content
   against 384px of content at 640px**, so "needs nothing" does not survive the bottom of the tablet
   tier. Same question applies to `ByCategory.jsx:117`, which 013 did assign to that bucket.
4. **Why the inventory missed them**, briefly — enough to say whether anything else is missing. 013
   worked from a list of views; these four are the tables that are not the *main* table of their view.

Feeds [the verification checklist](019-verification-checklist.md), which currently lists all four under
**Open calls** with no assignment.
