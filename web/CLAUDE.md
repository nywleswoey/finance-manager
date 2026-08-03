# Frontend

**The definition of done for anything you change under `web/src` is
[`../RESPONSIVE.md`](../RESPONSIVE.md).** Read it before changing layout, not after. It holds only
what the suite cannot assert, so a check written there is genuinely yours to run.

**The regression trigger is the suite: `make test-web`**, from the repo root, on any change under
`web/src`. [`TESTING.md`](TESTING.md) beside this file says what it runs, what each spec claims, and
what none of them can.

Nothing else about the suite is repeated here on purpose — this file points, it does not restate.
