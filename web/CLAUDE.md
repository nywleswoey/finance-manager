# Frontend

**The definition of done for anything you change under `web/src` is the suite: `make test-web`**,
from the repo root. [`TESTING.md`](TESTING.md) beside this file says what it runs, what each spec
claims, and what none of them can.

**[`../RESPONSIVE.md`](../RESPONSIVE.md) covers what the suite cannot assert** — real notch
behavior, Safari's focus-zoom, whether a tap target is comfortable. Read it before changing
layout, not after; it's a human checklist, not a second test suite.

Nothing else about the suite is repeated here on purpose — this file points, it does not restate.
