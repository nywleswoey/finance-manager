/**
 * Pattern B: card per row, for the tables you read one row at a time.
 *
 * Six tables across five views. Below 640px each of them stops being a table and becomes a
 * column of cards — identity and the row's one amount on line one, its textual fields muted
 * underneath, and a two-column key/value block only where the row carries more numbers than
 * its hero. At 640px and above every one of them is the table it always was.
 *
 * WHY THE TIER IS 640 AND NOT 1024, WHICH IS THE OTHER PATTERN'S. Cards trade density for
 * readability on a 390px measurement. One of these ledgers is 803px natural and fits outright
 * at 900, so cards there would cost rows and buy nothing — which is why the tablet tier
 * extends the *pin* to anything that overflows and leaves this pattern on the phone.
 *
 * WHY THE TIER IS IN JAVASCRIPT AND NOT IN CSS, and why that is asserted here. Pattern A
 * restyles markup that renders at every width, so its tier has to be a media query. This one
 * is different markup: `usePhone()` in `cards.jsx` picks between two renders of the same
 * rows. So the gate below reads the *stylesheet* to check no media query wraps these rules —
 * a second copy of 640 around the CSS would be a second place to get the same number wrong —
 * and reads the *DOM* at ten viewports to check the hook draws the line where it says it
 * does. The rotation test is the one that separates a live hook from a read at mount: a
 * rotated phone is 844px wide and must get its table back without a reload.
 *
 * WHAT THE FIXTURES CANNOT REACH. Two things, both annotated on every run rather than
 * quietly narrowed away. The dimmed treatment for excluded spending rows has no row to land
 * on — every captured transaction is counted spend — so it is asserted as a declaration and
 * the gap is named. And PLTR, the security the suite drills into because it has the longest
 * options history, has no dividends at all, so `SecurityDetail`'s dividend-history cards
 * never mount. The fixtures are derived from the live database and are not hand-edited; the
 * honest move is to say so rather than to invent a row.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW, VIEWPORTS } from "./viewports.js";
import { openView } from "./support/app.js";
import { readFixture } from "./fixtures/index.js";
import { declarationsFor } from "./support/css.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/**
 * Every table assigned the pattern, in the order it appears in its view.
 *
 * `rows` reads the committed fixture rather than counting what rendered, because "one card
 * per row" is a claim about the *data*: a build that dropped every other row would agree
 * with itself perfectly if the expected number came from the DOM.
 *
 * `cols` is the header count of the table this becomes above the tier, and it is here for
 * the same reason `pinned.spec.js` carries one — no table drops a column. Cards list every
 * field a row has; the count above the tier is what says none of them went missing on the
 * way through.
 *
 * `fields` is the size of the key/value block, and it is the pattern's own assignment rule
 * made checkable: a row with one number stops at two lines and has none, and a row with more
 * numbers than its hero gets exactly that many minus the hero.
 *
 * `tablesBelow` is how many `<table>` elements the view still renders on a phone — the other
 * patterns' tables, which stay. Asserting the count rather than the absence of one table is
 * what catches a card list rendered *next to* the table it was meant to replace.
 */
const CARDED = [
  {
    view: "Portfolio › Transactions",
    tablesBelow: 0,
    lists: [{
      what: "the trade ledger",
      rows: () => readFixture("transactions.json").length,
      tableIndex: 0, cols: 8, fields: 2,
    }],
  },
  {
    view: "Portfolio › Dividends",
    // The crosstab above it is pattern A and stays a table at every width.
    tablesBelow: 1,
    lists: [{
      what: "the payment ledger",
      rows: () => readFixture("dividend-details.json").rows.length,
      tableIndex: 1, cols: 8, fields: 3,
    }],
  },
  {
    view: "Portfolio › SecurityDetail",
    // The options wheel log is pattern A — three tables, two patterns, deliberately.
    tablesBelow: 1,
    lists: [{
      what: "the transaction history",
      rows: () => readFixture("holding-pltr.json").transactions.length,
      tableIndex: 0, cols: 8, fields: 3,
    }],
    unrendered: [
      "SecurityDetail's dividend history (6 cols) — PLTR is the row the suite drills into " +
      "because it has 73 option trades, and it has no dividends at all, so that card list " +
      "is never mounted",
    ],
  },
  {
    view: "Spending › Overview",
    tablesBelow: 0,
    lists: [{
      what: "top line items",
      rows: () => Math.min(14, readFixture("spending-summary.json").by_subcategory.length),
      tableIndex: 0, cols: 4, fields: 0,
    }],
  },
  {
    view: "Spending › Transactions",
    tablesBelow: 0,
    lists: [{
      what: "the spend ledger",
      rows: () => readFixture("spending-transactions.json").length,
      tableIndex: 0, cols: 6, fields: 0,
    }],
  },
];

for (const { view, lists, tablesBelow, unrendered } of CARDED) {
  test.describe(view, () => {
    test("is one card per row below the tier and the table it always was above it",
      async ({ page, baseURL }, testInfo) => {
        const vp = viewportOf(testInfo.project.name);
        await openView(page, baseURL, view);

        for (const gap of unrendered ?? []) {
          testInfo.annotations.push({ type: "not-covered-by-fixtures", description: gap });
        }

        // Soft throughout, like the pinned spec: one page load, every gate reported. A card
        // count that is wrong and a hero that lost its alignment are two findings.
        if (vp.width >= PHONE_TIER_BELOW) {
          expect.soft(await page.locator(".main .cards").count(),
            "card-per-row reached the tablet tier — it is phone-only by decision").toBe(0);
          for (const spec of lists) {
            const cols = await page.locator(".main table").nth(spec.tableIndex)
              .locator("thead th").count();
            expect.soft(cols, `${spec.what}: a column went missing above the tier`).toBe(spec.cols);
          }
          return;
        }

        expect.soft(await page.locator(".main .cards").count(), "card lists in this view")
          .toBe(lists.length);
        expect.soft(await page.locator(".main table").count(),
          "a table this pattern replaces is still rendering beside its cards").toBe(tablesBelow);

        for (const [i, spec] of lists.entries()) {
          const list = page.locator(".main .cards").nth(i);
          expect.soft(await list.locator("> .rowcard").count(),
            `${spec.what}: one card per row`).toBe(spec.rows());
          // The key/value block is the assignment rule made visible: a row carrying one
          // number stops at two lines, and one carrying more gets the rest under a rule.
          const kv = await list.locator("> .rowcard").first().locator(".rc-kv > div").count();
          expect.soft(kv, `${spec.what}: the key/value block`).toBe(spec.fields);
        }
      });

    test("nothing in a card is clipped or has to be scrolled sideways to read",
      async ({ page, baseURL }, testInfo) => {
        const vp = viewportOf(testInfo.project.name);
        test.skip(vp.width >= PHONE_TIER_BELOW, "above the tier there are no cards");
        await openView(page, baseURL, view);

        // The criterion cards were chosen for, and the one they cannot afford to lose:
        // nothing hidden. EVERY card is measured rather than a sample — the longest string
        // in the fixtures is a 65-character merchant name and nothing outside the
        // measurement knows which row it is on — so this is geometry only, in one round
        // trip. `scrollWidth`/`clientWidth` on a page nobody is mutating costs one forced
        // layout and then plain property reads; a `getComputedStyle` in the same loop would
        // be one style resolution per element, and at 1001 cards that starves the whole
        // worker pool for minutes and takes unrelated specs down with it. The truncation
        // half is a stylesheet fact and is asserted as one, once, below.
        const bad = await page.locator(".main .cards").evaluateAll((lists) => {
          const found = [];
          for (const list of lists) {
            for (const el of list.querySelectorAll(".rowcard, .rowcard *")) {
              if (el.scrollWidth > el.clientWidth + 1) {
                found.push(`${el.className || el.tagName} overflows by ` +
                  `${el.scrollWidth - el.clientWidth}px: ${el.textContent.trim().slice(0, 40)}`);
              }
            }
          }
          return found.slice(0, 10);
        });
        expect(bad, "a card hides part of its row").toEqual([]);
      });

    test("the hero amount is right-aligned and tabular", async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.width >= PHONE_TIER_BELOW, "above the tier there are no cards");
      await openView(page, baseURL, view);

      // The one alignment the pattern promises to keep. The rest of a card's fields line up
      // within the card and not across cards, which is the price of the pattern and is only
      // acceptable because it is never assigned where comparing across rows is the job — so
      // the hero is the whole of what is asserted here, deliberately.
      const hero = await page.locator(".main .rowcard .rc-hero").first().evaluate((el) => {
        const s = getComputedStyle(el);
        return { align: s.textAlign, numerals: s.fontVariantNumeric };
      });
      expect.soft(hero.align, "the hero amount is not right-aligned").toBe("right");
      expect.soft(hero.numerals, "the hero amount lost its tabular numerals")
        .toContain("tabular-nums");
    });

    test("a card is not interactive", async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.width >= PHONE_TIER_BELOW, "above the tier there are no cards");
      await openView(page, baseURL, view);

      // "Nothing hidden and no interaction at all" is half the reason this pattern beat the
      // priority-summary variant, which charged a tap to see the fields a card just prints.
      // A card that grew a control would be that variant arriving by the back door, and the
      // 44px tap floor would then apply to it — so this is cheaper to gate than to discover.
      //
      // One selector over the whole list rather than a walk per card, and the cursor read on
      // one card rather than all of them: `cursor` comes from the sheet, so the first card
      // answers for every card, and a thousand style resolutions here is what makes a suite
      // this size expensive to work against.
      const interactive = await page.locator(".main .cards").evaluateAll((lists) => {
        const found = new Set();
        for (const list of lists) {
          for (const el of list.querySelectorAll(
            ".rowcard a, .rowcard button, .rowcard input, .rowcard select, " +
            ".rowcard textarea, .rowcard [role=button]")) {
            found.add(el.tagName.toLowerCase());
          }
          const first = list.querySelector(".rowcard");
          if (first && getComputedStyle(first).cursor === "pointer") found.add("cursor: pointer");
        }
        return [...found];
      });
      expect(interactive, "a card grew a control — the pattern is read-only by decision")
        .toEqual([]);
    });
  });
}

test("the count the missing header gave up is in the card title", async ({ page, baseURL }) => {
  // There is no `<thead>` under this pattern, so the two things a header carried besides its
  // labels have to land somewhere: how many rows there are, and — in a grouped table — what
  // they add up to. The count goes in the title above the list, at every width rather than
  // only on a phone, because it is the same number either way and a title that changes shape
  // at 640 is a second thing to keep in step.
  const titles = [
    { view: "Portfolio › Transactions", rows: () => readFixture("transactions.json").length },
    // `rows.length`, not the fixture's `total`: the two are equal only because the flagged
    // filter is off, and the count the title owes the missing header is the one on screen.
    { view: "Portfolio › Dividends", rows: () => readFixture("dividend-details.json").rows.length },
    {
      view: "Portfolio › SecurityDetail",
      rows: () => readFixture("holding-pltr.json").transactions.length,
    },
    {
      view: "Spending › Overview",
      rows: () => Math.min(14, readFixture("spending-summary.json").by_subcategory.length),
    },
    {
      view: "Spending › Transactions",
      rows: () => readFixture("spending-transactions.json").length,
    },
  ];
  for (const t of titles) {
    await openView(page, baseURL, t.view);
    const headings = await page.locator(".main .card h3").allInnerTexts();
    expect.soft(headings.join(" | "), `${t.view}: no card title states the row count`)
      .toContain(String(t.rows()));
  }
});

test("no rule under this pattern truncates or refuses to wrap", async ({ page, baseURL }) => {
  await openView(page, baseURL, "Spending › Transactions");
  // The other half of "nothing is clipped", and it is a fact about the sheet rather than a
  // measurement — which is precisely why the per-card gate above cannot hold it. An
  // `ellipsis` is invisible to a `scrollWidth` check: the element it truncates fits its box
  // perfectly, which is the whole point of it. Two ways in, and both would read as house
  // style to whoever adds them: the prototype this pattern came from ellipsised its name
  // column, and the table rule these cards replace is `white-space: nowrap`.
  for (const sel of [".cards", ".rowcard", ".rc-head", ".rc-nm", ".rc-hero", ".rc-sub",
                     ".rc-kv", ".rc-kv > div", ".rc-kv .k", ".rc-kv .v"]) {
    for (const r of await declarationsFor(page, sel)) {
      expect(r.decls["text-overflow"], `\`${sel}\` truncates — a card must not hide a field`)
        .toBeUndefined();
      expect(r.decls["white-space"], `\`${sel}\` refuses to wrap`).not.toBe("nowrap");
    }
  }
});

test.describe("the tier is the hook, not a media query", () => {
  test("no rule under this pattern is wrapped in one", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Spending › Transactions");
    // Pattern A had to write its tier in CSS, because it restyles markup that renders at
    // every width — and `pinned.spec.js` gates *which* tier it wrote, because 639.98 and
    // 1023.98 are one character apart to read and a whole tier apart in effect. This pattern
    // has no such choice to get wrong: the card list does not exist above 640 at all. What it
    // can get wrong is writing 640 twice, so this asserts the CSS never says it.
    for (const sel of [".cards", ".rowcard", ".rc-head", ".rc-hero", ".rc-sub", ".rc-kv"]) {
      const rules = await declarationsFor(page, sel);
      expect(rules.length, `no rule ships for \`${sel}\``).toBeGreaterThan(0);
      for (const r of rules) {
        expect(r.media, `\`${sel}\` is scoped to a tier the hook already owns`).toBeNull();
      }
    }
  });

  test("a rotated phone gets its table back without a reload",
    async ({ page, baseURL }, testInfo) => {
      // The gate that separates a live `matchMedia` from a read at mount, which is what
      // `Holdings.jsx` does with the same query for its footnote — and the difference is
      // deliberate there: that one seeds state the user then owns. This one *is* the layout,
      // and 844x390 is a real phone that has left the tier by turning sideways.
      //
      // Run once rather than ten times: it sets its own two viewports, so the project's is
      // the starting point and nothing else.
      test.skip(testInfo.project.name !== "design-width", "this test drives its own viewport");

      await openView(page, baseURL, "Spending › Transactions");
      await expect(page.locator(".main .cards")).toHaveCount(1);
      await expect(page.locator(".main table")).toHaveCount(0);

      await page.setViewportSize({ width: 844, height: 390 });
      await expect(page.locator(".main .cards")).toHaveCount(0);
      await expect(page.locator(".main table")).toHaveCount(1);

      await page.setViewportSize({ width: 390, height: 844 });
      await expect(page.locator(".main .cards")).toHaveCount(1);
      await expect(page.locator(".main table")).toHaveCount(0);
    });
});

test("the excluded row's treatment survives the pattern", async ({ page, baseURL }, testInfo) => {
  await openView(page, baseURL, "Spending › Transactions");
  // ASSERTED AS A DECLARATION, because the fixtures hold no row it applies to: every
  // captured spending transaction is counted spend, and the endpoint only returns the
  // excluded ones behind `include_excluded=true`, which was never captured. So the table
  // above the tier cannot demonstrate its dimming either — the two renderings are equally
  // unexercised, and the check that matters is that they agree on the number.
  testInfo.annotations.push({
    type: "not-covered-by-fixtures",
    description: "no excluded spending row exists in the committed fixtures, so the dimmed " +
      "treatment is asserted as a declaration on both sides rather than observed",
  });
  const rules = await declarationsFor(page, ".rowcard.dim");
  expect(rules, "no dimmed treatment for an excluded row").toHaveLength(1);
  // The same 0.55 the table row carries inline in `spending/Transactions.jsx`. It is the
  // same fact about the row in both renderings, so a card that dimmed differently would be
  // the pattern quietly restating a decision it only inherited.
  expect(rules[0].decls.opacity, "the card dims by a different amount than the row").toBe("0.55");
});
