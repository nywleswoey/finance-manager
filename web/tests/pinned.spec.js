/**
 * Pattern A: the pinned identity column, and the scroll ownership that comes with it.
 *
 * Seven tables across six views exist so you can compare a number DOWN the column. Below
 * 1024px they are read through a window: the identity column is pinned, the rest scrolls
 * horizontally inside a wrapper, and the header stays put while the rows go by. This file
 * is the gate on all three halves plus the traps that make them fragile.
 *
 * WHY THE TIER IS 1024 AND NOT 640. The pin is worth *more* as the window narrows. At 640,
 * behind the 200px rail, the desktop table shows two identity columns and not one number,
 * and because `.main` owns the scroll there, reaching a number takes the identity away with
 * it — strictly worse than the phone. So every gate here runs at seven of the ten viewports,
 * and the other three assert the inverse: that nothing changed above the tier.
 *
 * WHAT IS ASSERTED AS A DECLARATION RATHER THAN AS GEOMETRY, and why — the same reasoning
 * `foundations.spec.js` opens with. `overscroll-behavior` being *unset* has no geometry: the
 * observable difference between `auto` and `contain` is whether a flick that reaches the end
 * of the table carries on to the page, and a synthetic scroll does not chain. So it is
 * asserted twice over as a fact about the stylesheet — no rule declares it, and it computes
 * to `auto` on every wrapper — because it is the one property here whose *absence* is the
 * decision, and the reflex is to reach for `contain`.
 *
 * WHAT THIS CANNOT CHECK. Whether two nested scroll regions on Recurring feel confusing —
 * that is an open call on a real device, not an assertion. And nothing here says the pinned
 * column is a useful *identity*; a pin that reads Put / Put / Call passes every gate below
 * and is worthless. That is what the merged contract cell exists for, and it is a reading
 * job rather than a measurement.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW, PIN_TIER_BELOW, PIN_TIER_EDGE, VIEWPORTS } from "./viewports.js";
import { openView } from "./support/app.js";
import { declarationsFor } from "./support/css.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/**
 * Every table assigned the pattern, with the two things a pin can silently get wrong.
 *
 * `pin` is the first header's text, which is the assertion that the *right* column got
 * pinned — Performance's is `{by}`, lowercase and changing with its `<select>`, so this
 * doubles as the check that the pinned header is the grouping key rather than a label.
 *
 * `cols` is the header count, and it is here because of the criterion no other gate covers:
 * **no table drops a column.** The pattern scrolls to them. A build that "fixed" the phone by
 * hiding four columns behind a media query would pass every geometric gate in this file.
 * Dividends is `null` because its column count is one per year and grows with time — which
 * is exactly why that table got horizontal scroll rather than anything that expires.
 *
 * `unrendered` is the seam showing through, and it is written down rather than left as a
 * shorter list. Recurring's tracked monitor is behind a non-empty tracked list and the owner
 * tracks nothing, so the committed fixture is `[]` and that table does not render at all —
 * the same shape of blind spot that let four tables through an entire planning effort. The
 * fixtures are derived from the live database and are not hand-edited, so the honest move is
 * to name the gap: it is reported as an annotation on every run rather than closed by
 * inventing a row.
 */
const PINNED = [
  { view: "Portfolio › Holdings", tables: [{ pin: "Security", cols: 13 }] },
  { view: "Portfolio › Performance", tables: [{ pin: "market", cols: 9 }] },
  { view: "Portfolio › Dividends", tables: [{ pin: "Bucket", cols: null }] },
  { view: "Portfolio › Options", tables: [{ pin: "Underlying", cols: 8 }] },
  { view: "Portfolio › SecurityDetail", tables: [{ pin: "Contract", cols: 6 }] },
  {
    view: "Spending › Recurring",
    tables: [{ pin: "Merchant", cols: 7 }],
    unrendered: [
      "Recurring.jsx's tracked monitor (11 cols, pin `Name`) — `/api/spending/recurring` " +
      "is `[]` in the committed fixtures, so the table is never mounted",
    ],
  },
];

/** The measurements one wrapper can be asked for, taken in a single round trip. */
const wrapperFacts = (page, index) =>
  page.locator(".pinned").nth(index).evaluate((wrap) => {
    const style = getComputedStyle(wrap);
    const table = wrap.querySelector("table");
    const tableStyle = getComputedStyle(table);
    const headers = [...table.querySelectorAll("thead th")];
    const corner = headers[0];
    // `:not(.grouprow)` in the stylesheet, and here for the same reason: Holdings' group
    // banner is a `colSpan` cell as wide as seven columns and is deliberately not pinned.
    const body = table.querySelector("tbody tr:not(.grouprow) > *");
    const banner = table.querySelector("tbody tr.grouprow > *");
    return {
      overflowX: style.overflowX,
      overscroll: style.overscrollBehavior,
      height: wrap.getBoundingClientRect().height,
      scrollsX: wrap.scrollWidth > wrap.clientWidth,
      scrollsY: wrap.scrollHeight > wrap.clientHeight,
      borderCollapse: tableStyle.borderCollapse,
      borderSpacing: tableStyle.borderSpacing,
      headerCount: headers.length,
      pinText: corner.textContent.trim(),
      corner: {
        position: getComputedStyle(corner).position,
        left: getComputedStyle(corner).left,
        top: getComputedStyle(corner).top,
        borderBottomWidth: getComputedStyle(corner).borderBottomWidth,
      },
      body: body && {
        position: getComputedStyle(body).position,
        left: getComputedStyle(body).left,
        borderBottomWidth: getComputedStyle(body).borderBottomWidth,
      },
      bannerPosition: banner && getComputedStyle(banner).position,
    };
  });

for (const { view, tables, unrendered } of PINNED) {
  test.describe(view, () => {
    test("pins its identity column and scrolls the rest, with the header and its borders intact",
      async ({ page, baseURL }, testInfo) => {
        const vp = viewportOf(testInfo.project.name);
        await openView(page, baseURL, view);

        for (const gap of unrendered ?? []) {
          testInfo.annotations.push({ type: "not-covered-by-fixtures", description: gap });
        }

        // Soft throughout: one page load, every gate reported. A pin that is missing and a
        // header that lost its border are two findings, and hearing about them one run at a
        // time is what makes a suite this size expensive to work against.
        expect.soft(await page.locator(".pinned").count(), "pattern-A wrappers in this view")
          .toBe(tables.length);

        for (const [i, spec] of tables.entries()) {
          const f = await wrapperFacts(page, i);

          expect.soft(f.pinText, `the pinned header of table ${i + 1}`).toBe(spec.pin);
          if (spec.cols !== null) {
            expect.soft(f.headerCount, "a column was dropped — the pattern scrolls to them")
              .toBe(spec.cols);
          } else {
            // One column per year, so the count is the fixture's rather than a constant.
            expect.soft(f.headerCount, "the crosstab lost its year columns")
              .toBeGreaterThanOrEqual(3);
          }

          if (vp.width >= PIN_TIER_BELOW) {
            // The other half of the claim: above the tier this is the table it always was.
            expect.soft(f.borderCollapse, "the desktop table changed its border model")
              .toBe("collapse");
            expect.soft(f.body?.position, "the pin reached desktop").toBe("static");
            continue;
          }

          expect.soft(f.overflowX, `wrapper ${i + 1} does not own the sideways scroll`)
            .toBe("auto");
          // THE TRAP. Under `collapse` the borders belong to the table's border grid and a
          // cell that has left the flow leaves them behind, so the pin and the sticky header
          // both render rule-less. The border widths below are the half that would actually
          // be visible; the border model is the half that explains it.
          expect.soft(f.borderCollapse, "sticky cells lose their borders under `collapse`")
            .toBe("separate");
          expect.soft(f.borderSpacing, "`separate` without zero spacing is a visible change")
            .toBe("0px");
          expect.soft(f.corner.borderBottomWidth, "the sticky header lost its rule").toBe("1px");
          expect.soft(f.body.borderBottomWidth, "the pinned column lost its rules").toBe("1px");

          expect.soft(f.corner.position, "the header corner is not stuck").toBe("sticky");
          expect.soft(f.corner.left, "the header corner is not pinned left").toBe("0px");
          expect.soft(f.corner.top, "the header corner is not stuck to the top").toBe("0px");
          expect.soft(f.body.position, "the identity column is not pinned").toBe("sticky");
          expect.soft(f.body.left).toBe("0px");
          if (f.bannerPosition !== null) {
            // Holdings only, and deliberate: pinning a seven-column `colSpan` banner would
            // park a subtotal over the numbers the sideways scroll exists to reach.
            expect.soft(f.bannerPosition, "the group banner got pinned").toBe("static");
          }

          // The decision that has no geometry — see the header.
          expect.soft(f.overscroll, "`overscroll-behavior` was set; default chaining is the decision")
            .toBe("auto");
        }
      });

    test("the identity stays put while the numbers scroll under it", async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.width >= PIN_TIER_BELOW, "above the tier there is no pin to hold still");
      await openView(page, baseURL, view);

      for (let i = 0; i < tables.length; i++) {
        // A table narrow enough to fit has nothing to demonstrate: the pin is still there,
        // it simply never leaves. Reported rather than silently skipped, because "it fits"
        // and "the wrapper stopped scrolling" look identical from here.
        const moved = await page.locator(".pinned").nth(i).evaluate((wrap) => {
          const row = wrap.querySelector("tbody tr:not(.grouprow)");
          const pin = row.children[0];
          const far = row.children[row.children.length - 1];
          if (wrap.scrollWidth <= wrap.clientWidth) return null;
          const before = { pin: pin.getBoundingClientRect().x, far: far.getBoundingClientRect().x };
          wrap.scrollLeft = wrap.scrollWidth - wrap.clientWidth;
          const after = { pin: pin.getBoundingClientRect().x, far: far.getBoundingClientRect().x };
          return { pinDrift: Math.abs(after.pin - before.pin), farDrift: before.far - after.far };
        });
        if (moved === null) {
          testInfo.annotations.push({
            type: "fits-outright",
            description: `${vp.name} · ${view} · table ${i + 1} needs no scroll`,
          });
          continue;
        }
        expect.soft(moved.pinDrift, `table ${i + 1}: the identity column scrolled away`)
          .toBeLessThanOrEqual(1);
        expect.soft(moved.farDrift, `table ${i + 1}: nothing scrolled`).toBeGreaterThan(0);
      }
    });

    test("the header stays put while the rows go by", async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.width >= PIN_TIER_BELOW, "above the tier the wrapper is not a scroll box");
      await openView(page, baseURL, view);

      for (let i = 0; i < tables.length; i++) {
        const stuck = await page.locator(".pinned").nth(i).evaluate((wrap) => {
          const th = wrap.querySelector("thead th");
          if (wrap.scrollHeight <= wrap.clientHeight) return null;
          const before = th.getBoundingClientRect().y;
          wrap.scrollTop = wrap.scrollHeight - wrap.clientHeight;
          return { drift: Math.abs(th.getBoundingClientRect().y - before) };
        });
        if (stuck === null) {
          // Performance is the permanent case: its row count is bounded by the grouping
          // dimension at eight, so it never scrolls and the tier's cap is a permanent no-op
          // on it. That is why the cap is a `max-height` and not an exemption list.
          testInfo.annotations.push({
            type: "no-vertical-scroll",
            description: `${vp.name} · ${view} · table ${i + 1} fits its box`,
          });
          continue;
        }
        expect.soft(stuck.drift, `table ${i + 1}: the sticky header scrolled away with the rows`)
          .toBeLessThanOrEqual(1);
      }
    });
  });
}

test.describe("the height that makes the sticky header work", () => {
  test("caps every pattern-A wrapper at 60svh on a phone, and leaves short tables alone",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.width >= PHONE_TIER_BELOW, "the cap is phone-only, by decision");

      const cap = vp.height * 0.6;

      // Every wrapper first, because the criterion is about all of them and the pair below
      // only proves the two ends of it.
      for (const { view, tables } of PINNED) {
        await openView(page, baseURL, view);
        const heights = await page.locator(".pinned")
          .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
        expect(heights, `${view}: pattern-A wrappers`).toHaveLength(tables.length);
        for (const [i, h] of heights.entries()) {
          expect.soft(h, `${view} table ${i + 1} is taller than the cap`).toBeLessThanOrEqual(cap + 1);
        }
      }

      // Holdings is the long one and Performance the short one, and the pair IS the claim:
      // one self-limiting rule rather than an exemption list. A `max-height` does nothing to
      // a table that fits, so the same declaration reaches both and neither is named.
      await openView(page, baseURL, "Portfolio › Holdings");
      const long = await page.locator(".pinned").first().evaluate((el) => el.getBoundingClientRect().height);
      expect(long, "the long table is not capped — its sticky header is dead").toBeLessThanOrEqual(cap + 1);
      expect(long, "the cap collapsed the table").toBeGreaterThan(cap - 2);

      await openView(page, baseURL, "Portfolio › Performance");
      const short = await page.locator(".pinned").first().evaluate((el) => el.getBoundingClientRect().height);
      expect(short, "the short table is being held at the cap rather than fitting")
        .toBeLessThan(cap - 1);
      testInfo.annotations.push({
        type: "pinned-heights",
        description: `${vp.name} · cap ${Math.round(cap)}px · Holdings ${Math.round(long)}px · Performance ${Math.round(short)}px`,
      });
    });

  test("writes the cap in the phone block and nowhere else", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Portfolio › Holdings");
    const rules = await declarationsFor(page, ".pinned");
    const capped = rules.filter((r) => r.decls["max-height"] !== undefined);
    expect(capped, "`.pinned` declares a height in more than one place").toHaveLength(1);
    // Rejected unconditional: turning a long list into a 60vh box on a 1280px desktop is a
    // visible change to a view nobody complained about.
    expect(capped[0].media, "the cap escaped the phone block").toContain("639.98px");
    // `svh`, like the shell — a box sized in `vh` resizes mid-flick when a toolbar retracts,
    // and this one is being flicked by definition.
    expect(capped[0].decls["max-height"]).toBe("60svh");

    const pattern = rules.filter((r) => r.decls["overflow-x"] !== undefined);
    expect(pattern, "the pattern itself is declared in more than one place").toHaveLength(1);
    expect(pattern[0].media, "the pattern is not written against the pin tier")
      .toContain(PIN_TIER_EDGE);
  });
});

test("no rule anywhere declares `overscroll-behavior`", async ({ page, baseURL }) => {
  // The reflex on a nested scroll box is `contain`, and here it is actively wrong: default
  // chaining is what you want — flick the table, hit its end, the page keeps going. `contain`
  // traps the gesture inside a 60svh box with nothing to say why. This is a source gate
  // rather than a behavioural one because a synthetic scroll does not chain, so the
  // difference between `auto` and `contain` cannot be observed from here at all.
  await openView(page, baseURL, "Portfolio › Holdings");
  const offenders = await page.evaluate(() => {
    const found = [];
    const walk = (rules) => {
      for (const rule of rules) {
        if (rule.style) {
          for (const prop of rule.style) {
            if (prop.startsWith("overscroll-behavior")) found.push(`${rule.selectorText} { ${prop} }`);
          }
        }
        if (rule.cssRules) walk(rule.cssRules);
      }
    };
    for (const sheet of document.styleSheets) {
      try { walk(sheet.cssRules); } catch { /* a cross-origin sheet, if one ever appears */ }
    }
    return found;
  });
  expect(offenders, "chaining is the decision — see the comment above `.pinned`").toEqual([]);
});

test.describe("a tappable row says so without a hover", () => {
  test("carries a persistent chevron in the pinned cell, below the tier only",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      await openView(page, baseURL, "Portfolio › Holdings");

      const cell = page.locator(".pinned tbody tr.rowlink > *").first();
      const seen = await cell.evaluate((el) => ({
        chevron: getComputedStyle(el, "::after").content,
        lane: getComputedStyle(el).paddingRight,
      }));

      if (vp.width >= PIN_TIER_BELOW) {
        // Above the tier there is no pinned cell to carry it, and hover is alive. A chevron
        // written unconditionally would also widen the identity column at desktop, which is
        // the layout change "desktop is unchanged" actually forbids.
        expect(seen.chevron, "the chevron reached desktop").toBe("none");
        return;
      }
      expect(seen.chevron, "no chevron — tappability is invisible without a hover")
        .toContain("›");
      // Absolutely positioned against the sticky cell, with the padding reserving its lane,
      // so a long security name cannot collide with it.
      expect(parseFloat(seen.lane), "the chevron has no lane to sit in").toBeGreaterThanOrEqual(24);
      testInfo.annotations.push({ type: "chevron", description: `${vp.name} · lane ${seen.lane}` });
    });

  test("takes its feedback from `:active` rather than `:hover`, at every width",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Portfolio › Holdings");
      // The rule is read rather than exercised, and not for want of trying: with a mouse,
      // `:hover` is true whenever `:active` is, and they resolve to the same colour here on
      // purpose — so a mouse-down that turns the row that colour proves nothing about which
      // of the two did it. Reading the sheet is what distinguishes them.
      //
      // Unconditional on purpose: a mouse-down flash in the colour the row already takes on
      // hover costs desktop nothing, where a second rule inside the tablet tier would cost
      // that tier the claim that it holds exactly one.
      //
      // It ships merged with `tr:hover td` — same declaration block, so the build folds the
      // two into one rule. `declarationsFor` matches a member of the selector list for that
      // reason; see its comment.
      const rules = await declarationsFor(page, "tr.rowlink:active > td");
      expect(rules, "no `:active` feedback — hover does not exist on touch").toHaveLength(1);
      expect(rules[0].media, "the tap feedback was scoped to a tier").toBeNull();
      // `background-color`, not `background`: the CSSOM expands the shorthand into its nine
      // longhands, so the property as authored is not a key here at all.
      expect(rules[0].decls["background-color"], "the row flashes nothing on tap")
        .toBe("rgb(26, 33, 42)");
    });
});

test.describe("Holdings' footnote", () => {
  test("is a disclosure on a phone and the paragraph it always was above the tier",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      await openView(page, baseURL, "Portfolio › Holdings");

      const note = page.locator("details.tablenote");
      await expect(note, "the footnote is not a disclosure element").toHaveCount(1);
      const summary = note.locator("summary");

      if (vp.width < PHONE_TIER_BELOW) {
        // Measured at the 44px pitch, collapsing it takes the table from 11 rows to 13 in
        // portrait and from 2 to 4 in landscape — the largest single row win on that screen.
        await expect(summary, "no way to open the footnote on the one screen it is shut on")
          .toBeVisible();
        expect(await note.evaluate((el) => el.open), "the footnote is open, spending the rows it saves")
          .toBe(false);
        const box = await summary.boundingBox();
        expect(box.height, "the disclosure is below the tap floor").toBeGreaterThanOrEqual(44);
      } else {
        // Open with its summary hidden: what renders is the paragraph, unchanged.
        await expect(summary, "a summary appeared above the tier").toBeHidden();
        expect(await note.evaluate((el) => el.open), "the desktop footnote is collapsed").toBe(true);
      }
      testInfo.annotations.push({ type: "footnote", description: `${vp.name}` });
    });
});

test("numbers stay right-aligned and tabular in every pinned table", async ({ page, baseURL }) => {
  // Most of why the pattern won: you are reading the real table through a window rather than
  // a translation of it, so the two properties that make a column of money comparable at a
  // glance are untouched. They are asserted at every viewport including desktop, because the
  // claim is that the pattern costs them nothing anywhere.
  for (const { view, tables } of PINNED) {
    await openView(page, baseURL, view);
    for (let i = 0; i < tables.length; i++) {
      const numeric = await page.locator(".pinned").nth(i).evaluate((wrap) => {
        // The first body cell with no `.l` — the app marks left-aligned columns and leaves
        // the numeric ones to the sheet's default.
        const cell = [...wrap.querySelectorAll("tbody tr:not(.grouprow) > *")]
          .find((td) => !td.classList.contains("l"));
        if (!cell) return null;
        const s = getComputedStyle(cell);
        return { align: s.textAlign, numerals: s.fontVariantNumeric };
      });
      expect(numeric, `${view} table ${i + 1} has no numeric column`).not.toBeNull();
      expect.soft(numeric.align, `${view} table ${i + 1}`).toBe("right");
      expect.soft(numeric.numerals, `${view} table ${i + 1}`).toContain("tabular-nums");
    }
  }
});
