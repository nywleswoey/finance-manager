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

`tests/unconditional.spec.js` — the gates that hold at *every* width, checked at every width and
only on the views that carry them: the refresh control's size, `.grid2`'s collapse, the wrapping
tab strip, the editors' 24px floor, the rule textarea's styling, the S2 list rows, and the merged
options identity cell. Each one moved **out of** `RESPONSIVE.md` when it moved in here.

`tests/foundations.spec.js` — the mechanism every phone rule sits in: the shell's `100svh`, the
`viewport-fit=cover` opt-in, the `max(<literal>, env(...))` content gutter inside the one
`@media (max-width: 639.98px)` block, the `--tap` token, and sign-in's box. It is the one file
that asserts **declarations** as well as geometry, because the things it gates are on
`baseline.spec.js`'s "cannot check, ever" list and leave nothing measurable behind. It is also
the only spec that renders the app **signed out** — `loadSignIn` in `tests/support/app.js`
answers the session endpoint 401.

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
