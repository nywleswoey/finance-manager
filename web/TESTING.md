# Frontend verification — start here

**The definition of done for anything you change under `web/src` is [`../RESPONSIVE.md`](../RESPONSIVE.md).**
It is the checklist — and since the sweep reconciled it against this suite, it holds **only what
this suite cannot assert**: five gates that need a real iPhone and one observation that needs an
iPad, the rest of the observations with their measured values, and the open calls. Its "Not built
yet" section — rules decided and never built — is **empty** since #44, and an entry belongs there
the moment that stops being true. Every gate that moved in here was deleted from there. Read it
before changing layout, not after.

**The command is `make test-web`** (from the repo root). It builds the frontend and runs the
Playwright viewport suite against the production build through vite's preview server.

```
make test-web                                   # everything
cd web && npx playwright test --project=design-width   # one viewport
cd web && npx playwright test --ui                     # pick through it interactively
```

First run on a machine also needs the browser: `cd web && npx playwright install chromium`.

## What the suite is

`tests/baseline.spec.js` — ten named viewports × thirteen views. Its header docstring is the
authority on what it asserts and, more importantly, **what it can never assert**. Read that
before treating a green run as "verified on a phone"; it is not. Five gates need a real iPhone and
one observation needs an iPad, all six named there — the fifth gate arrived with the tablet tier,
which put the navigation shell on a height guard the 44px tap floor deliberately did not follow.

**Where the shell is the phone's, "open a view" means different clicks**, and
`tests/support/app.js` makes them: the hamburger, then the section in the drawer, then the tab in
the `<select>`. Every spec keeps asking for `"Spending › Recurring"` and gets there the way a
person on that viewport would. So the phone half of the whole suite depends on the navigation
shell — which is why that ticket landed before the tables and the charts.

**That is not "below 640" any more.** The tablet tier put the shell on a *height* guard as well —
`(max-height: 500px)` — so 844×390 gets the drawer and the picker at 844px wide. `onPhoneShell` in
`tests/viewports.js` is the one place that question is answered, and only the *navigation* asks
it: the pin, the cards, the charts and the content gutter are all still width-only, which is the
split the tier was decided on. A spec that skips on `viewport.width < 640` when it means "where
the strip renders" will go looking for a control that is `display: none`.

`tests/unconditional.spec.js` — the gates that hold at *every* width, checked at every width their
subject exists at, and only on the views that carry them: `.grid2`'s collapse, the wrapping tab
strip, the editors' 24px floor, the rule textarea's styling, the S2 list rows, the merged options
identity cell, and the labelled refresh control — that last one wherever the tab strip renders,
because elsewhere the label does not exist to measure. Each one moved **out of** `RESPONSIVE.md`
when it moved in here.

`tests/foundations.spec.js` — the mechanism every phone rule sits in: the shell's `100svh`, the
`viewport-fit=cover` opt-in, the `max(<literal>, env(...))` content gutter inside the one
`@media (max-width: 639.98px)` block, the `--tap` token, and sign-in's box. It is the one file
that asserts **declarations** as well as geometry, because the things it gates are on
`baseline.spec.js`'s "cannot check, ever" list and leave nothing measurable behind. It is also
the only spec that renders the app **signed out** — `loadSignIn` in `tests/support/app.js`
answers the session endpoint 401.

`tests/shell.spec.js` — the phone navigation shell: the drawer and its scrim, the native tab
picker at 16px, the icon-only refresh with its toast strip *displacing* content rather than
covering it and then leaving on its own, the `100svh` column, and — wherever the rail survives —
that none of it renders. Since the height guard landed, its first group **runs at 844×390 too**,
so the guard is exercised eleven tests deep rather than asserted once; what did *not* travel with
the shell is the 44px tap floor, and that split is asserted both as geometry inside the drawer and
as a fact about which media block each rule sits in. It shares `foundations.spec.js`'s CSSOM
reader (`tests/support/css.js`) for the two criteria that are about a notch and therefore have no
geometric form in Chromium.

`tests/tablet.spec.js` — the tablet tier, 640–1024. The shortest spec with the strongest claim:
the tier holds **exactly one rule**, so most of this file asserts that things did *not* happen —
no card-per-row at 640 and above, no enlarged tap targets, no resized inputs, and no media block
of the tier's own in the shipped sheet (a `min-width` condition appearing at all is the second
design the brief forbids). What it does assert positively is the rule itself, as a sweep over the
eleven fully-responsive views: any table that overflows **its own container** gets a wrapper, the
wrapper holds the table and nothing else, it fits its parent, and — the part a scroll box alone
does not give you — the identity column inside it is `sticky`. That last gate is what found the
sixth table: `Dividends`' detail ledger had been inside an inline 520px scroll box since long
before this work, so it never appeared in the pane ratchet and read as done.

The sweep **names every table it did not put through all five gates** rather than passing over it
quietly, and there are three such annotations: `no-tables-here`, a view that renders no `<table>` at
that viewport (card-per-row replaces six of them below 640); `fits-outright`, a table that owes no
wrapper because it fits — gated on fitting, then recorded with its width against the room it had;
and `empty-tbody`, a wrapped table whose `tbody` holds no rows. The last is the one to read closely, because it is a hole rather than a
non-event: `Dividends` runs two independent fetches and gates its render on one of them, so between
them the ledger is on the page with its wrapper and nothing in it, and a table with no rows has no
identity column for the `sticky` gate to measure. That gate is skipped for that table on that run —
the other four still run — and the run says so by name. It is annotated rather than asserted because
the alternative was worse: until #111 the reader measured the `<table>` element as a stand-in for the
missing cell, and a table's computed `position` is `static`, so the sweep failed CI intermittently on
a pin nothing had touched. **An `empty-tbody` annotation on a view that should have had rows is a
question about that view's loading gate, not about the pin.** The window is asserted rather than
waited for: one test in the file stalls `/api/dividend-details` outright and checks that the ledger
comes back wrapped, alone, fitting and pinned, with `null` where the reading would be — so the
fallback cannot come back on a green suite.

`tests/tap.spec.js` — the phone tier's two rules about every fully-responsive *screen*: 16px form
controls and a 44px square tap floor, below 639.98px. **The only spec in the suite that is a sweep
rather than a list**, and the reason is the bug it exists for: both rules were decided in ticket 015,
built for the navigation shell alone, and went unnoticed for five tickets because every gate here
asserts a selector somebody named — and a named-selector gate cannot see a control nobody named.
This one asks the page what it renders and measures all of it, so a control added next year fails
without anyone remembering it. Three carve-outs, each with its own reason: the two editors are exempt
at 24px by decision and the exemption is **asserted as a band** rather than skipped, so it fails both
if their floor disappears and if the phone one leaks in; a checkbox is measured on the `<label>` that
wraps it, because clicking a label toggles the box and a 44px checkbox is not what a square floor
means; and sign-in's Google button is unreachable here at all — the seam aborts Google's script — and
has **no carve-out in the stylesheet because it needs none**: it is a `div[role="button"]` Google
injects, and sign-in carries no form control of its own, so no selector in the floor reaches that
screen. It was measured off-suite at 40px, which is why the number is written down rather than
shrugged at. It is width-scoped, so
844×390 gets the drawer and **no tap floor**, which is the same boundary `tablet.spec.js` asserts
from above.

`tests/pinned.spec.js` — pattern A: fourteen tables across ten views that pin an identity column and
scroll the rest sideways below **1024px**, not 640. Eight of them are tables you read *down* a
column; the other six arrived with the tablet tier, which extends the pin to anything that
overflows in it regardless of that table's phone assignment — and every one of those six is a card
list below 640, so the wrapper count in a view is a function of the viewport and `SecurityDetail`'s
pinned tables change *index* across the tier boundary. It is the one spec whose tier is the pin tier,
because the pin is worth more as the window narrows: the same gates run at seven viewports and the
other three assert the inverse — that the desktop table is untouched. It also carries the two gates
that have no geometry. **The column count of every pinned table is asserted**, because "no table
drops a column" is the criterion a build could satisfy every *geometric* gate while breaking. And
`overscroll-behavior` is asserted to be declared **nowhere**: the reflex on a capped scroll box is
`contain`, chaining is the decision, and a synthetic scroll does not chain, so there is nothing to
measure.

`tests/cards.spec.js` — pattern B: six tables across five views that stop being tables below **640px**
and become one card per row. The mirror image of `pinned.spec.js` in every way that matters: its tier
is the phone rather than the pin, its markup is *different* rather than restyled, and so the thing it
has to gate is that the tier lives in `usePhone()` and **nowhere in the stylesheet** — a media query
around those rules would be 640 written twice. It drives a rotation at one project, which is the only
gate that can tell a live `matchMedia` from a read at mount, and it names two things the fixtures
cannot reach: no captured spending row is excluded, and the security the suite drills into has no
dividends.

`tests/drill.spec.js` — the one view where both patterns land on the same thing. `By Category` is a
three-level drill, not two tables: categories and subcategories are rows and take the pin, and the
transactions behind a subcategory take cards — but they cannot stay nested, because a nested one
inherits a width that puts their amounts off the screen. So this spec gates the *structure* the two
patterns meet in, and leaves each pattern's own gates to the two files above. Its sharpest assertion
is the one that reads most like the others and is not: a card's right edge is compared in the pane's
**scroll space**, because clicking a row has already scrolled `.main` sideways, and in viewport
coordinates the rejected layout passes. It also carries the group header — the only one in the app —
and the chevron carve-out, which is the only place pattern A's affordance rule is deliberately not
applied.

`tests/charts.spec.js` — the six chart surfaces, plus the spend trend's four panels. Below 640 the donuts are not rendered and the
`.barrow` list beneath them becomes the chart, which is the one gate here that asserts an *absence*:
`display: none` starves a `ResponsiveContainer` to 0×0, so a hidden chart and a collapsed chart are
the same DOM and the treatment has to be a hook rather than a rule. Everything else it checks holds at
every width — that no container collapses in either dimension, that a multi-series chart names its
series in DOM rather than in a `<Legend>` that eats a quarter of the plot, and that no value label is
printed on top of an axis tick — the criterion stated as the collision it forbids rather than as the
prop that prevents it, which is what lets the same gate check that the reserved band is *absent* on a
window with no loss in it to reserve for. It waits for the bar animation before counting a single
label, because recharts renders a `LabelList` only once that has ended and a gate expecting none
would otherwise pass for the wrong reason. The stacked bar chart used to be the one surface it could
not reach — its fixture was a 500 — so its key was source-grepped in `inventory.spec.js` instead.
#35 fixed the endpoint, and the key is asserted here now, against the fixture's own `groups` rather
than a literal: those strings are `<Bar dataKey>`s, so a group that renders under a different name is
a group whose bar drew nothing. The grep stays for the charts no fixture happens to mount. It also
carries the **one-palette** gate, which is the key-versus-fill assertion's strict sibling: that one
compares two surfaces against *each other*, and both used to index one array at the same `i`, so it
passed by construction while the donut two cards up — indexing a differently sorted payload — coloured
Personal a different colour in the same viewport. The palette gate compares every spending surface
against the map declared in `src/palette.js`, which it **imports rather than restates**: a table of
hexes in the suite is a second palette, and the drift it would be blind to is the one it exists to
catch.

Since the two trajectory charts landed it also carries them, and **neither is dropped on a phone** —
the donut precedent is about redundancy rather than size, and nothing else on either page carries
trajectory, so both have gates at all ten viewports rather than a phone branch. For the **net-worth
composition** it asserts the payload's `bands` order (the literal bottom→top stacking order: three of
the four cumulative edges are summary tiles only because of it, and nothing else notices if it
moves), the composited fill opacity and the 2px surface gap the palette validator was run at, the x
axis's tick set and formats, that **no two tick labels overlap at any viewport** — which is the whole
reason the crossover is one constant rather than a function of width — that the curve is `linear`
read off the path commands rather than off the prop, that a dot lands on every band edge while the
series is sparse, and that the stack **never contradicts the tiles printed above it**. For the
**spend trend**, whose gates are shaped by what that chart would still look right while getting wrong,
its four series span two orders of magnitude, so the load-bearing claim is that **no series is flattened
onto the floor**: the file computes what the smallest of them would draw under one shared axis — under
3px of a 140px plot — and then measures what each one actually draws, so a regression to a shared scale
is caught by geometry rather than by a prop. The **caption** is gated for the same reason it exists:
newest is at the **left**, so every panel reads backwards and a panel has no y-axis at all, which makes
"latest value and signed delta, in words" the thing that keeps the slope from lying. The **footnote** is
checked against figures recomputed from `/api/spending/window`'s material-source flags rather than against
a sentence, because a typed "two of three sources" is right on today's ledger and wrong on the very payload
that ships with it — four sources, three material. The **dash** on Uncategorized is read only after the
line has finished drawing itself: recharts animates a line by rewriting `stroke-dasharray`, so mid-animation
every line is dashed and the declared pattern is unreadable — which is also why the settle helper here
samples the dash rather than `d`, the way the bar helper samples geometry. And the **grid** is asserted
against the rule rather than against ten literals: the column count is derived from the card's measured
inner width, and the one viewport that draws three panels and an orphan — 844×390, where the rail leaves
the flow but the 28px desktop gutter does not — is pinned **by name**, so a second orphan is a failure. It
asserts one panel per group with no cap and no fold, colour by name off the shared map with `Uncategorized`
dashed, one vertex per month **in the window** (which is what proves it slices rather than draws the whole
array), **newest at the left** read off the geometry against the payload's own direction, the 4 → 2 → 1
reflow (with an intentional three-panel row at 844×390, the one viewport where the constants produce that
orphan), and that the card adds no key, no bars and no control to a page whose existing
gates claim exactly one of the first and none of the last.

`tests/inventory.spec.js` — the checks that read files rather than pixels: the table count, the
single donut implementation, that no chart renders a `<Legend>` and that every multi-series chart that
needs a `<ChartKey>` carries one — the spend trend is deliberately *not* on that list, because its
panel headers are the key and a key under the grid would restate four names written four times
immediately above it, that **the composition's cumulative edges are the summary metrics to the
cent** — the anchor claim of that chart and the only place the cents survive, since every rendered
surface rounds to the dollar; it is checked over the dates the two fixtures share and fails loudly
if they share none — that **no source file names a net-worth catalogue item code** — the New
Snapshot form's headings and rows are derived from the catalogue's `band`, and the codes are read
out of the fixture so a recapture cannot leave the gate asserting a stale list (`srs` is held out,
because one word is a code, a band value *and* a funding bucket, so the claim is about the other
thirteen) — that **no spending surface mentions the `POSITIONAL_COLOURS` array** — only
`palette.js`, which declares it, and `charts.jsx`, whose portfolio donut slices by market and by
account and so has no taxonomy to key a map on — and that **the two colour maps agree about
Housing**, which is a deliberate coupling (spend Housing is the running cost of the same HDB whose
equity is the net-worth Housing band) that nothing renders side by side, so no viewport would look
wrong if one map drifted, that `640` is a literal in exactly four files **and that the two JavaScript
media queries say character for character what the stylesheet says** — counting the sites is not
checking they agree, and `(max-width: 640px)` would keep the count at four while moving the tier into
a 1px dead zone — that **no `vh` unit** survives under `web/src` — widened from `100vh` when the rule modal's `6vh`/`84vh` became `svh`, since `\dvh` does not match `100svh` and so does not catch the unit that is correct — the viewport meta's `viewport-fit=cover`,
the viewport list against `RESPONSIVE.md`, and the fixtures' own integrity.

`tests/editors.spec.js` — the two editors' floor. `Classify` and `NetWorth` are desktop-optimised by
decision and are checked against four criteria *instead of* the universal list, so this is the one
spec whose subject is a view the rest of the suite deliberately holds to a lower standard. It carries
two tiers rather than one, and neither is the other's: containment is asserted **below 1024**, because
an `overflow-x: auto` wrapper is the sticky scrollport for the header inside it and writing it
unconditionally would kill a header that works today; the hidden ⇅ Reorder and the neutralised nested
scroll are **below 640**, the phone tier. "A container that visibly is a table" is asserted as *the box
wraps the table and nothing else* — the rule modal's own `overflow: auto` absorbs its table's width and
would pass any weaker reading while sliding the buttons off the edge. It is also the only spec that
opens a modal to measure it, and the only one asserting a `title=` attribute is **absent**: a tooltip
does not exist on touch, so a gate on the five that existed would not stop a sixth. One thing it cannot
reach: `MatchTable` renders only after a POST the GET-captured fixtures do not carry, and that gap is
annotated on every run.

`tests/ticker.spec.js` — Holdings' **Group by: Ticker** fold, and the one spec here whose subject is
arithmetic rather than layout. A consolidated row folds several positions of one security into one
row, so it is either the right number or a wrong number rendered beautifully at ten viewports —
which is why it has a **project of its own at one viewport**, on the same reasoning the inventory
project runs once. Every expectation is **derived from the fixture**, never written as a literal, so
recapturing the fixtures cannot quietly turn the gate into a tautology; it also asserts the fixtures
still *carry* a split and a mixed open/closed split, because both gates are vacuous without one. The
defect it was written for is the one the responsive suite could never see: the P/L column resolves
per row — realised when closed, unrealised when open — so folding the raw fields read
`unrealised_pl_sgd` for a ticker open in one bucket and closed in another and silently dropped the
closed leg's realised result. What it deliberately does not check is anything responsive; the pin,
the column count and the row shape stay `pinned.spec.js`'s, because consolidated rows are ordinary
data rows and inherit those gates already.

`tests/composition.spec.js` — the four states of the **net-worth composition chart** the committed
fixture cannot reach, and the third spec here whose subject is not layout. An empty state is copy, a
tick crossover is a count, and whether a negative band lands above or below the zero line is
arithmetic; none of the three is a claim about width, so it runs at **one viewport in a project of
its own**. Two of them the live database can never hold again — this installation has five snapshots
and has permanently left the zero- and one-snapshot states — and a fixture cannot carry both sides of
a crossover, so this is the one file whose seam moves up a layer: it answers
`/api/networth/composition` itself and derives every expectation from what it served. It gates the
two empty strings (both **name** the New Snapshot card rather than pointing at it — the grid is one
column on a phone, where "beside" is false, and two above it, where "below" is), the dense tick
branch (month starts, `MMM`, the year on January — and the count is really asserting `interval={0}`,
without which recharts silently thins an explicit `ticks` array), and **sign-aware stacking**: a
negative band must hang below the zero line rather than be subtracted from the running total, which
is the assertion that separates the two stack offsets and matters because a negative value already
exists on an asset row on the first point the live chart draws.

`tests/catalogue.spec.js` — the New Snapshot form's **headings**, and the second spec here whose
subject is not layout. Which item a person types under which heading is either the catalogue's own
banding or it is a second banding that agrees with the first until the day it does not — and that is
the same partition at every width, so it runs at **one viewport in a project of its own**, on the
reasoning `ticker.spec.js` and the inventory project already carry. The defect it was written for is
one no responsive gate could ever see: the form rendered a frontend constant listing item codes, so a
**fifteenth seeded item was invisible in the entry form and silently absent from every snapshot
typed** — the creator's zeroing rule fabricating a $0 for it on every capture, forever, with nothing
on screen to say so. So the central test serves a catalogue this frontend has never heard of and
asserts the new item both renders a row and reaches the POST; the others assert the partition both
ways (one band per heading *and* one heading per band — either alone is satisfiable by a degenerate
layout) and that the payload is byte-for-byte the one the form always sent, prefill included. Every
expectation is derived from the fixtures, and nothing in it names a catalogue code or a real band
value: a gate that restated the constant would be the constant. Two more tests close the windows the
first four leave open — an item whose band the frontend has no heading for is still typed, under a
heading titled with the band itself, and a catalogue that GROWS while the form is open does not take
the view down (the view refetches `/items` after every save, and `rows` is re-seeded by an effect
that runs after that render). Three of the six would have passed against the deleted constant, which
listed exactly the fixture's fourteen codes in exactly its band order; they are characterization, and
the other three are the regression gates. What none of them check is the form's geometry, which stays
`editors.spec.js`'s at all ten viewports.

`tests/viewports.js` — the ten viewports, declared once. They mirror `RESPONSIVE.md`'s table
one-for-one and a test fails if the two lists drift apart.

`tests/fixtures/` — every API response, derived from the live database once by
`scripts/capture_web_fixtures.py` and committed. The seam is the HTTP API boundary,
intercepted in the browser: real Chromium, real layout, real media queries above it;
fixtures below it. No test touches Postgres or the network, and the auth gate is satisfied by
a mocked session endpoint, so Google's identity script never loads.

Fixtures are not hand-written and should not be hand-edited. They carry five deliberately
pathological rows — a 30-character subcategory name, a security with 73 option trades, a
65-character merchant string, the null-category row, and the two-orders-of-magnitude spread
across the four spend series inside the trend's window — each with a comment saying why.
Plausible-looking data is what produced the 415px-vs-519px error that made fixtures
necessary in the first place. The last of the five is the only one that is a claim about **two**
payloads at once, since the spread only exists inside the window a second endpoint defines, and
it is the one that keeps a gate from going vacuous rather than a measurement from being wrong:
a window whose four series happened to agree in magnitude would pass "no series is flattened
onto the floor" under a shared axis too.

## Where the reasoning lives

`RESPONSIVE.md` checks the decisions; it does not restate them. The argued detail — every
measurement, every rejected alternative — is in `.wayfinder/map-mobile-responsive.md` and its
tickets. Three prototypes live in `web/prototypes/`.

## Two things to know before you touch the suite

**`tests/hscroll-baseline.js` was a list of defects, not a specification.** The suite ratchets
against the measured numbers so it could run green on day one and still catch a regression. Lower
them as the work lands; never raise one to make a test pass. **It is done**: eight lowerings in,
`.grid2`'s track floor became `minmax(min(420px, 100%), 1fr)` under #44 and **every number in the
file is zero** — all thirteen views, all seven gated viewports. It is now a table of zeroes
standing in for `<= 0`, and its own header says what deleting it costs and why that is its own
ticket. Until then a raise is a plain regression, not a defect getting worse. `tablet.spec.js`
still asserts the table-shaped half separately, because the ratchet would go green on a build that
swapped one table's overflow for another's.

**No screenshots, ever.** Geometry and structure only. Visual-regression diffing is out of
scope by decision, and a test asserts that no `toHaveScreenshot` creeps in.
