---
id: 22
title: The four tables no ticket ever assigned
type: grilling
status: closed
assignee: nywleswoey
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

## Resolution

**All four assigned, and the test that assigns them survives — but the *third* bucket's rule does not.**
Measured in Chrome against the real `styles.css` and real DB rows, at [015](015-touch-targets-type-scale.md)'s
phone cell padding (`11px 8px`). Phone `.card` inner at 390px = **330px** (`.main` 362 − card 32).
Harness: `scratchpad/t022-measure.html` (throwaway, not committed).

| table | cols | min-content | cols visible @330 | pattern |
|---|---|---|---|---|
| `Performance.jsx:18` | 9 | **921** | **2** | **A** |
| `SecurityDetail.jsx:102` options | 9 | 678 → **524** | 4 → 6 | **A** |
| `spending/Overview.jsx:33` top line items | 4 | **471** | 2 | **B** |
| `ByCategory.jsx:168` drilldown | 4 | **602** | **1** | **B**, lifted out of the table |
| `ByCategory.jsx:117` categories *(013 said "unchanged")* | 4 | 334 / **413** / 567 | 3 / 2 / 1 | **A** |
| `Options.jsx:103` by ticker *(ref)* | 4 | 273 | fits | unchanged, confirmed |
| `Options.jsx:119` by type *(ref)* | 4 | 261 | fits | unchanged, confirmed |
| `Options.jsx:71` ledger *(013's least-certain B)* | 11 | 862 | — | **A** — overturned |

### 1. `Performance.jsx:18` → A. The cheapest A in the map.

A whole Portfolio tab no ticket had examined, and the app's **second-widest table** after Holdings (1302):
921px, **2 of 9 columns visible**. 013's test answers itself — every one of its eight numeric columns is an
aggregate you rank, and "which market/bucket/account returned best" is the view's only purpose.

Two facts make A cost less here than anywhere it has been applied. **Row count is bounded by the grouping
dimension** — 4 markets, 3 buckets, 8 accounts, and it can never be more — so the whole table is on screen
at once and [020](020-scroll-ownership-on-phone.md)'s `max-height: 60svh` is a *permanent* no-op rather than
a conditional one. And B would be 8 cards × 9 fields ≈ two screens of scrolling to destroy the one thing the
view does. Pin is the grouping key, already the first `.l` column; note its header text is `{by}` — lowercase,
and it changes with the `<select>`.

### 2. `SecurityDetail.jsx:102` → A, and 013's least-certain **B for `Options.jsx:71` is overturned**

The mechanical reading was B (contract ledger → read one row at a time). It does not survive measurement:

- **Density.** A 9-field `.rowcard` built to 013's own prototype markup measures **121px** (+8 gap) →
  **4 rows** in the ~528px pane. Pattern A at 015's 44px pitch → **12 rows**. 013 rejected B for Holdings at
  **3** rows and accepted it for `spending/Transactions` at **9**. Four sits on the rejected side.
- **Ledger-sized and uncapped.** Real DB: PLTR **73** option trades, RIVN 64, BABA 53. Under B that is
  ~9,400px of scroll, ~18 screens.
- **The test itself pointed to A all along.** What you do with one security's wheel log is scan P/L and
  Outcome *down the column* — "did selling puts on this work". That is compare.

**013's `ledger → B` over-generalised on the word *ledger*.** The real discriminator is how many numbers a
row carries: `spending/Transactions` has **one** amount; an options row has **five** (qty, strike, premium,
buyback, P/L) plus two dates and an outcome. That reframe settles `Options.jsx:71` in the same stroke — 11
cols, 862px, cross-security comparison is even more plainly its job — and A is there the *smaller* change,
because `Options.jsx:70` already ships `overflowX: "auto", maxHeight: 480, overflowY: "auto"` **today**. B
would have removed existing behaviour.

**Recorded, not fixed:** `SecurityDetail.jsx:48` txn history (8 cols, **914px**, up to 71 rows, four numbers
per row) would measure the same ~4 rows under B. It is 013's, it is not one of this ticket's four, and it
sits on the borderline of the one-number test. SecurityDetail therefore reads **B, B, A** down the page —
deliberately, not by oversight.

### 3. The pin: 013's "first `.l` column" rule breaks on `SecurityDetail:102`

013's rule works everywhere it has been applied only because the first `.l` column happens to be an identity
— Security, Name, Date, Category, Underlying. Here it is **`Type`**: 46px of `Put / Put / Put / Call`. Pin it
and the landmark cannot tell you which row you are on, which is the pin's only job. And the precedent does
*not* carry: Holdings needed **no markup change** for its pin, because `Holdings.jsx:53` is already a two-line
identity cell at every width. This one is not.

| | width | pinned col |
|---|---|---|
| (a) pin `Type`, as-is | 678 | 46px, useless |
| (d) move `Opened` first, nothing else | 678 | 109px date |
| **(b) merge `Opened`+`Type`+`Strike`+`Qty` into a two-line `Contract` cell** | **524** | 109px, complete |

**(b), applied unconditionally at every width.** It **pays for itself** — −154px off the scroll region
against the 109px the pin costs, which is the difference between 4 and 6 columns behind the pin. The
precedent is the map's own: [014](014-charts-on-phone.md) killed the fixed 130px `.nm` column at *every*
width explicitly so there would be "one row shape and no conditional", and 015 fixed `.nw-del` at every width
because it was free; a phone-only column set here would be the React conditional both rulings avoided. And on
desktop it is a fix rather than a change — the other two tables on this same page both lead with Date, the
data is `ORDER BY open_date`, and `:102` is the odd one out today.

**Cost, stated plainly:** this is the **first decision in the map to alter a desktop read-only table's column
set**. "Desktop unchanged" was locked for *layout*; 014 and 015 have already broken it for content where the
change was free-and-better. This is that precedent's third use, not a new exception.

### 4. 013's third bucket: **column count was the wrong discriminator**

| ≤4-col table | min-content | widest column | verdict |
|---|---|---|---|
| `Options:103` by ticker | 273 | Ticker 62 | fits |
| `Options:119` by type | 261 | Type 58 | fits |
| `Overview:33` top line items | **471** | Line item **232** | fails |
| `ByCategory:117` categories | **413** | Category **212** | fails |

The two that fit hold tickers and numbers. The two that fail each have one column of **unbounded free text
from the DB** — `Life/Health/Surgical Insurance` is 30 chars, real, and ranks 3rd by spend. **The rule is
"does any column hold free text?", not "is it under 5 columns?"**; 013's proxy merely correlated on the
tables it happened to look at. So the bucket is not dead — it is half right, and it survives with a better rule.

This also **corrects [018](018-tablet-tier.md)**, which measured these two cards at 415/419 and set `.grid2`
to `minmax(420px, 1fr)`. Against real data `Overview:33`'s card needs **519**. 018 flagged this as a soft spot
in the abstract ("a longer category name than *Transport & Travel* still spills"); it now has a measured
instance in the live DB. The `auto-fit` behaviour is unchanged, so this is a number correction, not a
reopened decision.

### 5. `spending/Overview.jsx:33` → **B**, because A's pin is unaffordable

The identity column *is* the 232px `Line item` — **70% of a 330px viewport**. The B card measures **65px** →
**8 of its 14 rows** on screen, and the row count is permanently bounded by `.slice(0, 14)`. On second reading
the test agrees: "Top Line Items" is a ranked list where *position* carries the ranking; you read "what is my
biggest spend and what is it", not "scan this column". The resulting shape — name + hero amount + a muted
sub-line of category and % — is 014's phone bar-row minus the bar, and 014 already deleted the donut in the
*other* half of this same `.grid2`, so the phone view becomes two consistent ranked lists rather than a list
and a table.

### 6. `ByCategory` is not two tables — it is one three-level drill

`:168` is a `<table>` inside `<td colSpan={4}>` of `:117`, so **the child sets the parent's width**: `:117`
measures 334 collapsed, **413** with subcategories open, **567** once a subcategory is drilled. They cannot
take independent patterns.

**The child's pattern is forced by identity, not by measurement.** `:168` renders the same rows as
`spending/Transactions.jsx:41` — same `cash_txn`, same fetch, a strict subset of its columns (date, merchant,
subcategory, amount vs. six). 013 assigned that **B**. Same data, same pattern. That also disposes of the
ticket's headerless worry: B needs no `<thead>`, and 013 already passed B's header job to the group-header row
carrying the aggregate — here that is the subcategory row you tapped. Nothing new is required.

**But B cards cannot stay inside the colspan cell.** The cell is as wide as the table (413px), so the cards
would be 413 wide in a 330 viewport — hero amounts clipped, swipe required. That contradicts the exact
property B was chosen for: *nothing hidden, no interaction at all*. So **on phone the drilled transactions
render below the table** rather than as a nested row, headed by subcategory name + count + aggregate. Levels
1–2 stay as table rows; level 3 leaves the table. Rejected: leaving them nested and accepting horizontally
scrolled cards — cheaper, no conditional, but it guts B.

With the child out, `:117` drops to **413** — still over 330 in both states, so it takes **A**, pin = the name
column at 212px, leaving 118px of scroll region for Spend/%/Txns. Two riders:

- **It keeps its own `▸`/`▾` and does *not* get 013's persistent `›`.** 013's affordance rule assumes tapping
  navigates away; here it expands in place, and the coloured disclosure marker already says so. `›` would be
  a lie. **First carve-out from that rule.**
- The **26px indent at `ByCategory.jsx:133` is inline**, so CSS cannot reach it — third instance of the family
  015 (`Transactions.jsx:35`) and 020 (`Classify.jsx:126`) recorded. It is what makes the pin 212px rather
  than ~186px.

### 7. Why the inventory missed them — two causes, and the count is now closed

`grep -ro "<table" web/src | wc -l` = **22**, and 13 (013) + 5 (017) + 4 (here) = 22. **The inventory is complete.**

1. **The view list was short.** 013 enumerated **8 views**; the app has 13. `portfolio/Performance` and
   `spending/Overview` never entered it at all — which is why a whole Portfolio tab went unexamined.
   (`portfolio/Overview` was also absent but holds no table, so it cost nothing.)
2. **Conditionally-rendered tables inside views it did list.** `SecurityDetail:102` is behind
   `opts.length > 0`; `ByCategory:168` is behind two taps *and* lives in a helper component (`TxnList`) at the
   bottom of the file rather than in the view's JSX.

**The ticket's own hypothesis was wrong**: these are not "the tables that are not the *main* table of their
view" — 013 assigned seven non-main tables correctly (all three of Options', both of Dividends', both of
Recurring's). It was not blind to non-main tables, only to ones outside the main render path.

Handed to 019 as a regression trigger cheap enough to actually run: **`grep -ro "<table" web/src | wc -l` — if it is
not 22, the pattern table in `RESPONSIVE.md` is stale.** It is the check that would have caught this ticket's
existence a month earlier. The audit stops at tables; 017, 014 and 018 each closed their own non-table
surfaces (`.nw-row`, `.barrow`, `.tiles`).

### Checklist updated

[`RESPONSIVE.md`](../../RESPONSIVE.md) amended in place — the four ⚠ markers and the four-table Open call are
gone, `Options.jsx:71`'s open call is resolved to A, and the new traps are recorded. Amending the deliverable
is inside the map's plan-only lock; leaving it holed was not an option.
