---
id: 13
title: Wide numeric tables on a phone
type: prototype
status: closed
assignee: nywleswoey
blocked_by: []
parent: map-mobile-responsive
---

## Question

What does a wide numeric table become at 390px? This is the core question of the map — eight
read-only views are built on one shared table style.

The shared style assumes desktop hard: `table { width:100% }` with
`th, td { padding:7px 10px; text-align:right; white-space:nowrap }` and **sticky headers**
(`styles.css:35-38`). Every column is nowrap, so the table simply exceeds the viewport.

The views, and the shape of each:

| View | File | Shape |
|---|---|---|
| Holdings | `portfolio/Holdings.jsx` (185) | widest — many numeric columns, row click → SecurityDetail |
| Dividends | `portfolio/Dividends.jsx` (127) | dates + native/SGD money pairs — **also a `BarChart` at :63** |
| Options | `portfolio/Options.jsx` (139) | contract identity + numerics — **also two `BarChart`s at :34,:52** |
| Transactions (portfolio) | `portfolio/Transactions.jsx` (51) | ledger rows |
| Transactions (spending) | `spending/Transactions.jsx` (61) | ledger rows |
| By Category | `spending/ByCategory.jsx` (191) | table + drilldown |
| Recurring | `spending/Recurring.jsx` (167) | derived cadence data |
| Security detail | `portfolio/SecurityDetail.jsx` (133) | drill-down target |

Dividends and Options are table **plus** chart — only the table half belongs here; their charts are
[Charts on a phone](014-charts-on-phone.md). Both views therefore need the two decisions to compose
in one screen.

Decide, by building a throwaway prototype to react to (`/prototype`) with at least two contrasting
variants over **real-shaped Holdings and Transactions data**:

1. **The pattern.** Card-per-row (each row becomes a stacked label/value block), a priority
   two-or-three-column summary that expands on tap, horizontal scroll of the real table with a
   pinned identity column, or a hybrid that differs by view. Name one default.
2. **Sticky headers.** Whether they survive the chosen pattern, and what replaces them if not.
3. **Row affordances.** Holdings rows are clickable (`tr:hover td`, styles.css:39) — hover doesn't
   exist on touch, so how is "this row is tappable" signalled, and how does the drilldown back-nav
   work.
4. **Number legibility.** `font-variant-numeric: tabular-nums` and right-alignment are what make
   these tables readable; state whether the pattern keeps them and, if the pattern breaks
   alignment, what preserves scannability.
5. **One pattern or several.** Whether all eight views take the same treatment, or the ledger-style
   views diverge from the position-style ones.

Link the prototype from the resolution. The answer must be specific enough that
[per-view column priority](../map-mobile-responsive.md) can be graduated out of the fog — or
declared unnecessary.

## Resolution

**Prototype** (primary source): [`web/prototypes/mobile-tables-prototype.html`](../../web/prototypes/mobile-tables-prototype.html)
— 3 patterns (A pinned column + horizontal scroll · B card per row · C priority summary + expand in
place) over **both** table shapes, switchable with `?variant=`/`?view=`, rendered inside the shell
from [The phone navigation shell](012-phone-navigation-shell.md) so the vertical budget is real.
Data carries the awkward cases: closed positions, the cost-unknown `~` marker, the `NetCell` bar,
grouping, and excluded/dimmed ledger rows. The bar reports **fully-visible data rows**, measured.

Measured at 390×844:

| | Holdings (13 cols) | Transactions (6 cols) |
|---|---|---|
| A — pinned + h-scroll | **15 rows**, table 1302px (3.3× viewport) | 13 rows, 803px |
| B — card per row | **3 rows** | 9 rows |
| C — priority + expand | 9 rows | 11 rows |

**Verdict: not one pattern — two, chosen per table by one test.**

> **Does this table exist so you can compare a number down the column, or so you can read one row
> at a time?** Compare → **A**. Read → **B**. Under ~5 columns → neither; it already fits.

Holdings went to A on the second reading of its phone job: *look up everything about one position*.
A is the only pattern where every column keeps its alignment across every row — you are reading the
real table through a 390px window, not a translation of it. B was rejected for positions on the
measurement: **3 rows per screen, and no two rows aligned on any number**. C was rejected as the
compromise that serves neither reading — it preserves comparison for exactly one promoted column and
charges a tap for the other twelve.

B still wins for ledgers, and that is why the answer is two patterns rather than one: a ledger row has
six fields, is read top-to-bottom rather than across, and fits a two-line card with **nothing hidden
and no interaction at all** — where A would make you swipe to see an amount.

**The third bucket was a surprise the inventory did not show: several of these tables are already
narrow enough to need nothing.** The ticket listed 8 views; the views actually hold **13 tables**,
and four of them are ≤4 columns.

| Table | Cols | Pattern |
|---|---|---|
| `Holdings.jsx:142` positions | 13 | **A** |
| `Dividends.jsx:32` bucket × year crosstab | 1 + n years | **A** — comparison is its entire purpose, and the column count *grows with time*, so h-scroll is the only option that doesn't expire |
| `Recurring.jsx:95` recurring monitor | 11 | **A** (least certain — see below) |
| `Recurring.jsx:127` candidates | 7 | **A** |
| `Dividends.jsx:91` payment ledger | 9 | **B** |
| `Options.jsx:72` contract ledger | 11 | **B** (least certain — see below) |
| `portfolio/Transactions.jsx:29` | 8 | **B** |
| `spending/Transactions.jsx:41` | 6 | **B** |
| `SecurityDetail.jsx:48` txn history | 8 | **B** |
| `SecurityDetail.jsx:74` dividend history | 6 | **B** |
| `ByCategory.jsx:117` | 4 | **unchanged** |
| `Options.jsx:103` by ticker | 4 | **unchanged** |
| `Options.jsx:119` by type | 4 | **unchanged** |

**Two calls the build session should sanity-check rather than trust**: `Options.jsx:72` (11 fields is
a heavy card — it may hit Holdings' 3-rows-per-screen problem and want A instead) and
`Recurring.jsx:95` (assigned A, but the map already suspects Recurring wants a different information
design entirely, not a reflow — that fog patch stays open).

The rest of the ticket's questions:

2. **Sticky headers survive under A, with a trap.** `th { position: sticky; top: 0 }` composes with a
   pinned `td { position: sticky; left: 0 }` as long as the z-indexes are layered — body cells, then
   pinned cells, then the header, then the pinned header corner (2/3/4 in the prototype). **The trap:
   `styles.css:35` sets `border-collapse: collapse`, under which sticky cells lose their borders.
   Variant A only works after switching that table to `border-collapse: separate; border-spacing: 0`.**
   Under B there is no header at all; its job passes to the group-header rows (which carry the group's
   aggregate) and the `(n)` count in the card title.
3. **Row affordances.** `tr:hover td` (`styles.css:39`) is dead weight on touch — replace with
   `tr:active` for tap feedback, plus a persistent `›` at the right edge of the **pinned** identity
   cell so tappability is visible without hovering and without being scrolled away. Back-navigation
   needs no new machinery: `Holdings.jsx:115` already passes `onBack` and `SecurityDetail.jsx:24`
   already renders a `← Holdings` link. There is **no router in this app**, so browser-back would
   leave it entirely — that link is the only way home and must become a real ≥44px target
   ([Touch targets & type scale](015-touch-targets-type-scale.md) owns the number).
4. **Number legibility.** A preserves it completely — `tabular-nums`, right-alignment and the sticky
   header are all untouched, which is most of why it won. B keeps the hero amount right-aligned and
   tabular, and renders the remaining fields as label/value pairs that align *within* a card but not
   across cards — acceptable precisely because B is only used where cross-row comparison is not the
   job. The `NetCell` magnitude bar survives under A unchanged.
5. **One pattern or several — several**, as above: A, B, and leave-alone, assigned by the compare-vs-read
   test rather than by view.

**Per-view column priority is now unnecessary — the fog patch is killed, not graduated.** No table in
any bucket ever drops a column: A scrolls to them, B lists them all, the narrow ones fit as they are.
What replaced it is two questions small enough to answer here: **which column is pinned** (the view's
existing first `.l` column — Security / Name / Date / Category), and **which field is the card hero**
(the SGD amount). Neither needs a ticket.
