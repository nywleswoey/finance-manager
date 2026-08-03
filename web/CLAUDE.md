# Frontend

**The definition of done for anything you change under `web/src` is
[`../RESPONSIVE.md`](../RESPONSIVE.md).** Read it before changing layout, not after.

**The regression trigger is the suite, and the command is `make test-web`** (from the repo root).
It builds the frontend and runs ten named viewports × thirteen views against the production build,
with every API call served from committed fixtures. A full run is ~8 minutes; one viewport is
`cd web && npx playwright test --project=design-width`. First run on a machine also needs
`cd web && npx playwright install chromium`.

`RESPONSIVE.md` holds only what the suite cannot assert: five gates that need a real iPhone and one
observation that needs an iPad, the rest of the observations with their measured values, the open
calls, and one section of rules that were decided and never built. Every
gate the suite covers has been deleted from it rather than struck through — so if a check is written
there, it is genuinely yours to run.

`TESTING.md` in this directory says what each spec claims and, more usefully, what it cannot.
`RESPONSIVE.md`'s **Traps** section is the list of things that look like tidying and are not.
