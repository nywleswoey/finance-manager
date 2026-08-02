# Frontend verification — start here

**The definition of done for anything you change under `web/src` is [`../RESPONSIVE.md`](../RESPONSIVE.md).**
It is the checklist: ten viewports, the universal gates, the per-view gates, the traps, and
the handful of items that need a real iPhone. Read it before changing layout, not after.

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
before treating a green run as "verified on a phone"; it is not. Four things need a real
iPhone and are named there.

**Below 640px, "open a view" means different clicks**, and `tests/support/app.js` makes them:
the hamburger, then the section in the drawer, then the tab in the `<select>`. Every spec keeps
asking for `"Spending › Recurring"` and gets there the way a person on that viewport would. So
the phone half of the whole suite depends on the navigation shell — which is why that ticket
landed before the tables and the charts.

`tests/unconditional.spec.js` — the gates that hold at *every* width, checked at every width their
subject exists at, and only on the views that carry them: `.grid2`'s collapse, the wrapping tab
strip, the editors' 24px floor, the rule textarea's styling, the S2 list rows, the merged options
identity cell, and the labelled refresh control — that last one at 640 and up, because below it
the label does not render at all. Each one moved **out of** `RESPONSIVE.md` when it moved in here.

`tests/foundations.spec.js` — the mechanism every phone rule sits in: the shell's `100svh`, the
`viewport-fit=cover` opt-in, the `max(<literal>, env(...))` content gutter inside the one
`@media (max-width: 639.98px)` block, the `--tap` token, and sign-in's box. It is the one file
that asserts **declarations** as well as geometry, because the things it gates are on
`baseline.spec.js`'s "cannot check, ever" list and leave nothing measurable behind. It is also
the only spec that renders the app **signed out** — `loadSignIn` in `tests/support/app.js`
answers the session endpoint 401.

`tests/shell.spec.js` — the phone navigation shell: the drawer and its scrim, the native tab
picker at 16px, the icon-only refresh with its toast strip *displacing* content rather than
covering it and then leaving on its own, the `100svh` column, and — at 640 and above — that
none of it renders. It shares
`foundations.spec.js`'s CSSOM reader (`tests/support/css.js`) for the two criteria that are
about a notch and therefore have no geometric form in Chromium.

`tests/pinned.spec.js` — pattern A: seven tables across six views that pin an identity column and
scroll the rest sideways below **1024px**, not 640. It is the one spec whose tier is the pin tier,
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

`tests/inventory.spec.js` — the checks that read files rather than pixels: the table count, the
single donut implementation, that no `100vh` survives under `web/src`, the viewport meta's
`viewport-fit=cover`, the viewport list against `RESPONSIVE.md`, and the fixtures' own
integrity.

`tests/viewports.js` — the ten viewports, declared once. They mirror `RESPONSIVE.md`'s table
one-for-one and a test fails if the two lists drift apart.

`tests/fixtures/` — every API response, derived from the live database once by
`scripts/capture_web_fixtures.py` and committed. The seam is the HTTP API boundary,
intercepted in the browser: real Chromium, real layout, real media queries above it;
fixtures below it. No test touches Postgres or the network, and the auth gate is satisfied by
a mocked session endpoint, so Google's identity script never loads.

Fixtures are not hand-written and should not be hand-edited. They carry four deliberately
pathological rows — a 30-character subcategory name, a security with 73 option trades, a
65-character merchant string, and the null-category row — each with a comment saying why.
Plausible-looking data is what produced the 415px-vs-519px error that made fixtures
necessary in the first place.

## Where the reasoning lives

`RESPONSIVE.md` checks the decisions; it does not restate them. The argued detail — every
measurement, every rejected alternative — is in `.wayfinder/map-mobile-responsive.md` and its
tickets. Three prototypes live in `web/prototypes/`.

## Two things to know before you touch the suite

**`tests/hscroll-baseline.js` is a list of defects, not a specification.** The main pane
overflows horizontally at every viewport below 1024px today — that is the problem the
responsive work exists to fix. The suite ratchets against the measured numbers so it can run
green now and still catch a regression. Lower them as the work lands; never raise one to make
a test pass.

**No screenshots, ever.** Geometry and structure only. Visual-regression diffing is out of
scope by decision, and a test asserts that no `toHaveScreenshot` creeps in.
