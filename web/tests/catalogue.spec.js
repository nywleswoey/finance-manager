/**
 * The New Snapshot form's headings — and the item that must never be invisible.
 *
 * WHY THIS FILE IS NOT IN `editors.spec.js`. That file gates the two editors' *floor*: what
 * happens to their geometry below 1024. This gates a partition — which catalogue item is typed
 * under which heading — and a partition has no width. It is either the catalogue's own banding
 * or it is a second banding that agrees with the first until the day it does not, and that is
 * the same at ten viewports. So it runs at **one**, in a project of its own, on the reasoning
 * `ticker.spec.js` and the inventory project are both built on.
 *
 * WHAT IT EXISTS FOR. The form used to render a frontend constant listing item codes under four
 * headings — not the catalogue it is capturing. That is a latent bug rather than duplication: a
 * fifteenth seeded item is in no list, so it renders no row, so `save()` never sends it and the
 * zeroing rule fabricates a $0 for it on every capture, forever, with nothing on screen to say
 * so. `test("a newly seeded item…")` below is that bug, written down: it serves a catalogue the
 * constant could not have known and asserts the item both renders and reaches the payload.
 *
 * THREE OF THESE SIX ARE CHARACTERIZATION, and saying so is the honest framing: the constant
 * listed exactly the fixture's fourteen codes in exactly its band order, so the partition and the
 * payload tests would have passed against it too. They are here to hold the refactor to "a
 * rendering change and nothing else". The regression gates are the three that could not have
 * passed before: the newly seeded item, the unknown band, and the catalogue that grows while the
 * form is open.
 *
 * EVERY EXPECTATION IS DERIVED FROM THE FIXTURE, never written as a literal — the same
 * discipline `ticker.spec.js` and `charts.spec.js` hold, and here it is what stops the gate from
 * becoming a restatement of the constant it exists to forbid. Nothing below names a heading, a
 * *catalogue* item code or a band value; the fixture's own `band` is the only partition any of it
 * reads. The two strings written out are the fifteenth item's code and the band nothing has ever
 * returned — both invented here precisely because no catalogue and no frontend carries them.
 */
import { expect, test } from "@playwright/test";
import { mockApi, VIEWS } from "./support/app.js";
import catalogue from "./fixtures/api/networth-items.json" with { type: "json" };
import latest from "./fixtures/api/networth-latest.json" with { type: "json" };

const netWorth = VIEWS.find((v) => v.name === "Net Worth");

const BAND_OF = Object.fromEntries(catalogue.map((i) => [i.code, i.band]));
const BANDS = new Set(catalogue.map((i) => i.band));

/**
 * What the form starts every field at: the latest snapshot's figure where it has one, and the
 * catalogue's own default where it does not.
 *
 * Restated here rather than assumed, because the *prefill* is what makes the payload gate below
 * mean something. A form that rendered its rows correctly and then posted zeroes for all of them
 * would satisfy every other assertion in this file and wipe the snapshot.
 */
const PREFILLED = Object.fromEntries((latest.values ?? []).map((v) => [v.code, v]));
const startingValue = (it) => PREFILLED[it.code]?.native_value ?? 0;
const startingCurrency = (it) => PREFILLED[it.code]?.currency ?? it.currency_default;

/**
 * The form as rendered: one entry per headed section, in DOM order, with the codes typed under it.
 *
 * "Section" and not "group": `CONTEXT.md`'s Band entry names *group* as the word to avoid for this,
 * because it was the name of the constant this file exists to keep deleted. `.nw-group` is the
 * pre-existing class and is what the DOM is queried by.
 *
 * Read off `data-testid="input-<code>"` rather than off the visible label, because the code is
 * what `save()` posts — a heading holding the right *words* over the wrong row would pass a
 * label-keyed gate and still write the wrong snapshot.
 */
const renderedSections = (page) =>
  page.$$eval("[data-testid=networth-form] .nw-group", (sections) =>
    sections.map((g) => ({
      title: g.querySelector(".nw-grouptitle")?.textContent ?? null,
      codes: [...g.querySelectorAll("input[data-testid^='input-']")].map((i) =>
        i.getAttribute("data-testid").slice("input-".length)),
    })));

/**
 * Load the app with the seam installed, optionally serving a catalogue of our own, and open
 * Net Worth.
 *
 * `catalogueFor` is a function of the *fetch count*, not a constant, because the view refetches
 * `/items` after every save and delete — so "the catalogue grew while the form was open" is a
 * state this app reaches on its own and a test that could only answer the first fetch could
 * never reach it.
 *
 * `loadApp` is deliberately not used: it installs `mockApi` itself, and Playwright matches
 * routes in reverse registration order — so calling it after the override would put the
 * committed fixture back in front of it.
 */
async function openForm(page, baseURL, catalogueFor) {
  await mockApi(page, baseURL);
  if (catalogueFor) {
    let served = 0;
    await page.route("**/api/networth/items", (route) =>
      route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify(catalogueFor(served++)),
      }));
  }
  await page.goto("/");
  await expect(page.locator(".app")).toBeVisible({ timeout: 20_000 });
  await netWorth.open(page);
  await expect(page.getByTestId("networth-form")).toBeVisible();
}

/** The whole-app fallback `ErrorBoundary` renders when a render throws. */
const crashed = (page) => page.getByText("Something went wrong");

/**
 * Type a snapshot and capture what the form posted.
 *
 * The POST has no committed fixture — the captures are GETs from the live database — so this
 * both answers it and records it. `fallback()` on anything else hands the path back to
 * `mockApi`'s catch-all, which is what keeps the reload after a save working.
 */
async function saveAndCapture(page) {
  let posted = null;
  await page.route("**/api/networth/snapshots", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    posted = route.request().postDataJSON();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 1 }) });
  });
  await page.getByTestId("snapshot-save").click();
  await expect.poll(() => posted, { message: "the form never posted" }).not.toBeNull();
  return posted;
}

test("every catalogue item is typed exactly once", async ({ page, baseURL }) => {
  // The whole of the bug in one assertion: an item the form does not render is an item the
  // form cannot send. A set comparison rather than an ordered one on purpose — within a
  // heading the rows follow the catalogue's `sort_order`, but the headings themselves are not
  // required to interleave with it, so asserting the flattened order would be asserting that
  // no two bands ever alternate in the seed.
  await openForm(page, baseURL);
  const codes = (await renderedSections(page)).flatMap((g) => g.codes);
  expect([...codes].sort(), "a catalogue item with no row is silently $0 in every snapshot")
    .toEqual(catalogue.map((i) => i.code).sort());
});

test("each heading is one band, and each band is one heading", async ({ page, baseURL }) => {
  // The partition, both ways. "One band per heading" alone is satisfied by splitting a band
  // across two headings; "one heading per band" alone is satisfied by one heading holding
  // everything. Together they say the headings *are* the banding.
  expect(BANDS.size, "the fixture carries one band — both gates below are vacuous")
    .toBeGreaterThan(1);

  await openForm(page, baseURL);
  const rendered = await renderedSections(page);

  for (const g of rendered) {
    const bands = new Set(g.codes.map((c) => BAND_OF[c]));
    expect([...bands], `"${g.title}" holds rows from more than one band`).toHaveLength(1);
  }
  const headed = rendered.map((g) => BAND_OF[g.codes[0]]);
  expect(new Set(headed).size, "a band split across two headings").toBe(rendered.length);
  expect(new Set(headed), "a band with no heading").toEqual(BANDS);
});

/**
 * The fifteenth item, and the reason this file exists.
 *
 * Its code is in no list anywhere in the frontend and never will be — `inventory.spec.js`
 * forbids one. It inherits the first catalogue row's band, so the tests that use it are asking
 * about *membership* rather than about a new heading appearing; `UNBANDED` below asks the other
 * question.
 */
const HOST = catalogue[0];
const SEEDED = {
  ...HOST, id: 9_001, code: "seeded_after_the_frontend_shipped",
  label: "Seeded After The Frontend Shipped", sort_order: 9_001,
};

test("a newly seeded item appears in the form, and in what the form posts", async ({ page, baseURL }) => {
  const host = HOST;
  const seeded = SEEDED;
  await openForm(page, baseURL, () => [...catalogue, seeded]);

  const rendered = await renderedSections(page);
  expect(rendered.flatMap((g) => g.codes),
    "a catalogue item the frontend has never heard of renders no row").toContain(seeded.code);
  expect(rendered.find((g) => g.codes.includes(host.code)).codes,
    "the new item is under a heading of its own rather than its band's").toContain(seeded.code);
  expect(rendered, "a new item in an existing band grew a heading").toHaveLength(BANDS.size);

  const posted = await saveAndCapture(page);
  expect(posted.values.map((v) => v.code).sort(),
    "rendered but not posted is the same silent $0 by another route")
    .toEqual([...catalogue.map((i) => i.code), seeded.code].sort());
  // No snapshot has ever carried it, so its row is the one the zeroing rule would have
  // fabricated anyway — the difference is that a person can now see the field and type in it.
  expect(posted.values.find((v) => v.code === seeded.code))
    .toEqual({ code: seeded.code, native_value: 0, currency: seeded.currency_default });
});

test("a catalogue that grows while the form is open does not take the view down", async ({ page, baseURL }) => {
  // THE WINDOW THE OLD CONSTANT CLOSED BY BEING WRONG. The view refetches `/items` after every
  // save, and `rows` — the typed values, keyed by code — is re-seeded by an effect that runs
  // *after* the render the new catalogue causes. So there is one render in which the form is
  // asked to draw an item that has no row yet, and reading the row unguarded throws out of
  // render into the whole-app `ErrorBoundary`: the person who just saved a snapshot loses the
  // page, not the field.
  //
  // The constant never met this because it drew four fixed lists and skipped anything it did not
  // recognise — the same blindness this ticket removed. Deriving the layout is what puts the new
  // item on screen, and it has to survive being put there mid-session, not only on first load.
  await openForm(page, baseURL, (n) => (n === 0 ? catalogue : [...catalogue, SEEDED]));
  expect((await renderedSections(page)).flatMap((g) => g.codes)).not.toContain(SEEDED.code);

  await saveAndCapture(page);                            // the save is what refetches the catalogue

  await expect(crashed(page), "the form threw out of render on the refetched catalogue")
    .toHaveCount(0);
  await expect(page.getByTestId("input-" + SEEDED.code)).toBeVisible();
});

test("an item in a band the frontend has no heading for is still typed", async ({ page, baseURL }) => {
  // The fallback, gated rather than only claimed. `band()` returns one of four values today, so
  // a fifth is a server-side change — and the failure mode this whole ticket exists to remove is
  // fields nobody can find. So an unrecognised band gets a heading of its own, titled with the
  // band itself: ugly, visible, and reportable, which is the trade this file argues for.
  //
  // The one place a heading's *text* is asserted, and it costs nothing to derive: the claim is
  // precisely that the title falls back to the band string, so the band string is the expectation.
  const unbanded = { ...SEEDED, band: "a_band_the_frontend_has_never_seen" };
  await openForm(page, baseURL, () => [...catalogue, unbanded]);

  const rendered = await renderedSections(page);
  expect(rendered, "the unknown band grew no heading").toHaveLength(BANDS.size + 1);
  const its = rendered.find((g) => g.codes.includes(unbanded.code));
  expect(its, "the item vanished — the exact failure this ticket removed").toBeTruthy();
  expect(its.codes, "the unknown band was merged into a heading that is not its own")
    .toEqual([unbanded.code]);
  expect(its.title).toBe(unbanded.band);
});

test("the payload is the one it always was", async ({ page, baseURL }) => {
  // The other half of "derived, not restated": deriving the *layout* must not touch the *write*.
  // `save()` has always walked the catalogue rather than the rendered groups, so the order here
  // is `sort_order` — asserted in full, values included, because this is the gate that says the
  // refactor was a rendering change.
  expect(Object.keys(PREFILLED).length, "the latest fixture prefills nothing").toBeGreaterThan(0);

  await openForm(page, baseURL);
  const posted = await saveAndCapture(page);

  expect(posted.values).toEqual(catalogue.map((it) => ({
    code: it.code, native_value: startingValue(it), currency: startingCurrency(it),
  })));
});
