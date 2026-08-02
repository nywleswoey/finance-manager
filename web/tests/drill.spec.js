/**
 * The spending drill: one three-level structure, not two tables.
 *
 * `By Category` is the one view where both patterns land on the *same* thing. Categories and
 * their subcategories are levels one and two and stay table rows — pattern A, the name column
 * pinned. Level three, the transactions behind a subcategory, is pattern B by identity rather
 * than by measurement: they are the same `cash_txn` rows `spending/Transactions` renders, from
 * the same endpoint, a strict subset of its columns, and that table is already B.
 *
 * WHY LEVEL THREE LEAVES THE TABLE, which is the whole reason this view needed its own slice.
 * A nested table inherits its parent's width and therefore *sets* the parent's min-content:
 * the category table measures 334px collapsed, 413px with subcategories open and 567px once a
 * subcategory is drilled. Cards left in that `colSpan` cell would be 413px wide in a 330px
 * card — hero amounts off the edge, a swipe to read them — which is the exact property cards
 * were chosen for. So on a phone they render BELOW the table instead, headed by the
 * subcategory, its count and its aggregate. The gate for that is not `scrollWidth` on a card:
 * a card that is wider than the pane fits its own contents perfectly. It is the card's right
 * edge against the pane's, below.
 *
 * WHAT THIS FILE DOES NOT COVER, deliberately. Every pattern-A gate on the category table —
 * the pin, the sticky header, the border model, the 60svh cap — belongs to `pinned.spec.js`,
 * which carries this view in its `PINNED` list like the other six. Every pattern-B gate that
 * is a fact about the sheet — no truncation, no media query — belongs to `cards.spec.js`.
 * What is here is the structure those two patterns meet in, plus the group header and the
 * chevron carve-out, neither of which exists anywhere else in the app.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW, PIN_TIER_BELOW, VIEWPORTS } from "./viewports.js";
import { openView } from "./support/app.js";
import { readFixture } from "./fixtures/index.js";
import { declarationsFor } from "./support/css.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/**
 * The one drill path the fixtures can walk, and it is not an arbitrary one: `Personal` is the
 * largest category of the default year and `Life/Health/Surgical Insurance` is the
 * 30-character subcategory name the fixtures exist to carry — the string that makes the
 * category table 413px and the top-line-items card 519px. Drilling anywhere else would test
 * the structure against the easiest row in the data rather than the hardest.
 *
 * `spending/transactions?…&group=Personal&subcategory=Life/Health/Surgical Insurance` is the
 * only drilled response the capture script recorded, so this is also the only path that
 * answers with rows rather than a 404 through the seam.
 */
const CATEGORY = "Personal";
const SUB = "Life/Health/Surgical Insurance";
const drilled = () => readFixture("spending-transactions-drilled.json");

/** The subcategory row's own aggregate, as the summary states it — see `groupHeader` below. */
const subTotal = () =>
  readFixture("spending-summary-2026.json").by_subcategory
    .find((r) => r.category === CATEGORY && r.subcategory === SUB).v;

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * A level-one or level-two row, found by its own disclosure marker plus its name.
 *
 * Matched on the identity *cell* rather than on the row, because a row's text is its name
 * with three numbers run onto the end of it and nothing to anchor against. The marker is part
 * of the pattern here — `▸` shut, `▾` open, `·` for the rows that are not drillable — so
 * matching it also means this locator cannot accidentally find the "Personal Taxes"
 * subcategory when it is asked for the "Personal" category.
 */
const rowFor = (page, name) =>
  page.locator(".main tbody tr").filter({
    has: page.locator("td.l").filter({ hasText: new RegExp(`^[▸▾] ${escapeRe(name)}$`) }),
  });

/** Open the view and drive all three levels: category, subcategory, transactions. */
async function drill(page, baseURL) {
  await openView(page, baseURL, "Spending › By Category");
  await rowFor(page, CATEGORY).click();
  await expect(rowFor(page, SUB), "the category did not expand into its subcategories")
    .toHaveCount(1);
  await rowFor(page, SUB).click();
  // The third level is a fetch, so wait for whichever rendering this viewport gets rather
  // than for a timeout: the cards below the table on a phone, the nested rows above it.
  const landed = page.viewportSize().width < PHONE_TIER_BELOW
    ? page.locator(".main .cards .rowcard")
    : page.locator(".main table table tbody tr");
  await expect(landed.first(), "the drilled transactions never arrived").toBeVisible();
}

test.describe("Spending › By Category", () => {
  test("levels one and two are one table and level three is not in it",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      await drill(page, baseURL);

      const phone = vp.width < PHONE_TIER_BELOW;
      // Counting the view's tables is what separates "the cards replaced the nested table"
      // from "the cards rendered next to it" — the same gate `cards.spec.js` holds with
      // `tablesBelow`, and here it is the whole claim of the ticket.
      expect.soft(await page.locator(".main table").count(),
        phone ? "level three is still a table inside the table" : "the view changed above the tier")
        .toBe(phone ? 1 : 2);
      expect.soft(await page.locator(".main .cards").count(), "card lists in this view")
        .toBe(phone ? 1 : 0);

      if (!phone) return;

      expect.soft(await page.locator(".main .cards > .rowcard").count(),
        "one card per drilled transaction").toBe(drilled().length);
      // Not merely "below" in source order: `.cards` must not be a descendant of the table
      // at all, because the width a nested element inherits is what the lift exists to shed.
      expect.soft(await page.locator(".main table .cards").count(),
        "the cards are still nested inside the table they were lifted out of").toBe(0);
    });

  test("the second level is pinned too, and its pinned cell keeps the row's own tint",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      await openView(page, baseURL, "Spending › By Category");
      await rowFor(page, CATEGORY).click();

      // `pinned.spec.js` carries this view, but `openView` does not drill — so every gate it
      // holds runs against level-one rows only, and level two is where this pattern is at its
      // most fragile. The subcategory row is the one row in the app with a background of its
      // own, and an opaque pinned cell paints over it: the cell has to restate the tint or the
      // name column renders a different colour from its own three numbers. That was an inline
      // style CSS could not reach, which is the third instance of a family `RESPONSIVE.md`
      // already names — and it failed silently, because nothing drilled.
      // The pinned cell is compared against a SIBLING CELL rather than against the `<tr>`.
      // The tint sits on the cells — it has to, because `border-collapse: separate` and an
      // opaque pin both ignore a background declared on a row — so the row itself is
      // transparent and comparing to it would pass whenever the pin was transparent too,
      // which is the failure. The two cells either match or the column is visibly wrong.
      const seen = await rowFor(page, SUB).evaluate((tr) => ({
        position: getComputedStyle(tr.children[0]).position,
        left: getComputedStyle(tr.children[0]).left,
        pin: getComputedStyle(tr.children[0]).backgroundColor,
        sibling: getComputedStyle(tr.children[1]).backgroundColor,
      }));

      if (vp.width >= PIN_TIER_BELOW) {
        expect.soft(seen.position, "the pin reached desktop").toBe("static");
        return;
      }
      expect.soft(seen.position, "the subcategory row's identity column is not pinned")
        .toBe("sticky");
      expect.soft(seen.left, "the subcategory row's pin is not at the left edge").toBe("0px");
      expect.soft(seen.pin, "the pinned cell paints over the second level's tint")
        .toBe(seen.sibling);
    });

  test("the lifted cards carry a header with the subcategory, its count and its aggregate",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.width >= PHONE_TIER_BELOW, "above the tier the drill stays in the table");
      await drill(page, baseURL);

      // Pattern B ships no `<thead>`, so the two things a header carried besides its labels
      // have to land somewhere. In the flat B tables that is the card title's count; this is
      // the one grouped B table in the spec, so it is the only place the *aggregate* half of
      // that job is actually visible.
      const header = page.locator(".main .cards .cardgroup");
      await expect(header, "the lifted cards have no group header").toHaveCount(1);
      const text = await header.innerText();

      expect.soft(text, "the header does not name the subcategory it is showing").toContain(SUB);
      // The count is what is ON SCREEN — the same reading `cards.spec.js` takes for the card
      // titles, because the number the missing header owes you is the number of cards under
      // it. The aggregate is the tapped row's own, so the two renderings of one group agree.
      expect.soft(text, "the header's count is not the number of cards under it")
        .toContain(String(drilled().length));
      expect.soft(text.replace(/,/g, ""), "the header does not carry the group's aggregate")
        .toContain(String(Math.round(subTotal())));
    });

  test("nothing in a drilled card is clipped or has to be swiped to reach",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.width >= PHONE_TIER_BELOW, "above the tier there are no cards");
      await drill(page, baseURL);

      // TWO MEASUREMENTS, because either alone passes the case the other exists for.
      //
      // `scrollWidth > clientWidth` catches a field that overflows its own card. It does NOT
      // catch the failure this ticket is about: a card sitting in a box wider than the pane
      // fits its contents perfectly and reports nothing, while its right edge — where the
      // hero amount is — sits off the screen behind a horizontal swipe. That is precisely
      // what a card left inside the drill's own grid would do at 390px.
      //
      // So the second measurement is the card's right edge against the pane's client width,
      // TAKEN IN THE PANE'S SCROLL SPACE rather than in viewport coordinates — and that is
      // the difference between a gate and a coincidence. `.main` is already scrolled
      // sideways by the time this runs, because clicking a row scrolled it into view, so a
      // viewport-coordinate comparison measures a card that has been dragged back on screen
      // by the very scroll the criterion forbids. Adding `scrollLeft` back is what asks the
      // question the ticket asks: is the whole card reachable *without* swiping. Verified by
      // building the rejected layout and watching this fail by 27px.
      const bad = await page.evaluate(() => {
        const main = document.querySelector(".main");
        const origin = main.getBoundingClientRect().left - main.scrollLeft;
        const found = [];
        // THE GROUP HEADER IS MEASURED WITH THE CARDS, not left out as chrome. It is the only
        // new markup this ticket adds, it holds the 30-character subcategory name beside an
        // aggregate, and it is a sibling of the cards rather than one of them — so a selector
        // that said `.rowcard` alone would skip the widest string on the screen.
        for (const card of main.querySelectorAll(".cards > .rowcard, .cards > .cardgroup")) {
          const box = card.getBoundingClientRect();
          const right = box.right - origin;
          if (right > main.clientWidth + 1) {
            found.push(`a card runs ${Math.round(right - main.clientWidth)}px past the pane`);
          }
          for (const el of [card, ...card.querySelectorAll("*")]) {
            if (el.scrollWidth > el.clientWidth + 1) {
              found.push(`${el.className || el.tagName} hides ` +
                `${el.scrollWidth - el.clientWidth}px: ${el.textContent.trim().slice(0, 40)}`);
            }
          }
        }
        return [...new Set(found)].slice(0, 10);
      });
      expect(bad, "a drilled card hides part of its row").toEqual([]);
    });

  test("the category rows keep their own marker and get no chevron",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      await openView(page, baseURL, "Spending › By Category");

      // THE ONE CARVE-OUT from the affordance rule pattern A ships. Everywhere else, a
      // tappable row in a pinned table carries a persistent `›` in its pinned cell, because
      // hover is dead on touch and the state between taps needs to say "this opens
      // something". Here the row does not navigate anywhere — it expands in place — and the
      // coloured `▸`/`▾` already says so. A `›` beside it would be a lie about where the tap
      // goes, so this view is the only place the chevron is deliberately absent.
      const marker = await page.locator(".main tbody td.l").first().evaluate((el) => ({
        text: el.textContent.trim(),
        chevron: getComputedStyle(el, "::after").content,
      }));
      expect.soft(marker.text, "the category row lost its disclosure marker")
        .toMatch(/^[▸▾·]/);
      expect.soft(marker.chevron, "the category table got the chevron — it expands in place")
        .toBe("none");

      if (vp.width >= PIN_TIER_BELOW) return;
      // The chevron's absence is not permission to leave a tappable row with no feedback at
      // all: hover is still dead here. `.rowtap` is what these rows take instead — the
      // `:active` half of the affordance without the half that claims a destination.
      const rules = await declarationsFor(page, "tr.rowtap:active > td");
      expect(rules, "no `:active` feedback — with no chevron this row says nothing on touch")
        .toHaveLength(1);
      expect(rules[0].media, "the tap feedback was scoped to a tier").toBeNull();
      // The token rather than a literal, for the reason `pinned.spec.js` gives at length: the
      // opaque pinned cell has to restate this colour, and two literals is how one feedback
      // state drifts into two.
      expect(rules[0].text, "the row flashes nothing on tap").toContain("var(--hover)");
    });
});

test("the group header is the hook's, like the rest of pattern B, and truncates nothing",
  async ({ page, baseURL }) => {
    await openView(page, baseURL, "Spending › By Category");
    // Both halves of what `cards.spec.js` asserts for the card itself, for the one part of
    // the pattern that landed with this ticket rather than with that one. The truncation half
    // is not theoretical here: the group header's name is `Life/Health/Surgical Insurance`,
    // the 30-character string the fixtures exist to carry, in a 362px pane.
    for (const sel of [".cardgroup", ".cardgroup .cg-nm", ".cardgroup .cg-n",
                       ".cardgroup .cg-total"]) {
      const rules = await declarationsFor(page, sel);
      expect(rules.length, `no rule ships for \`${sel}\``).toBeGreaterThan(0);
      for (const r of rules) {
        expect(r.media, `\`${sel}\` is scoped to a tier the hook already owns`).toBeNull();
        expect(r.decls["text-overflow"], `\`${sel}\` truncates`).toBeUndefined();
        expect(r.decls["white-space"], `\`${sel}\` refuses to wrap`).not.toBe("nowrap");
      }
    }
  });

test("the whole drill survives a rotation, in both directions", async ({ page, baseURL }, testInfo) => {
  // 390x844 and 844x390 are the two orientations the ticket names, and they are on opposite
  // sides of the tier: a rotated phone is 844px wide, so it has left the phone block and must
  // get the nested table back — with the drill still open, without a reload, and without
  // re-fetching. This is the same gate `cards.spec.js` holds for its own hook, driven through
  // a structure that has state in it.
  //
  // Run once rather than ten times: it sets its own two viewports.
  test.skip(testInfo.project.name !== "design-width", "this test drives its own viewport");

  await drill(page, baseURL);
  await expect(page.locator(".main .cards > .rowcard")).toHaveCount(drilled().length);
  await expect(page.locator(".main table")).toHaveCount(1);

  await page.setViewportSize({ width: 844, height: 390 });
  await expect(page.locator(".main .cards")).toHaveCount(0);
  await expect(page.locator(".main table")).toHaveCount(2);
  await expect(page.locator(".main table table tbody tr")).toHaveCount(drilled().length);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".main .cards > .rowcard")).toHaveCount(drilled().length);
  await expect(page.locator(".main table")).toHaveCount(1);
});
