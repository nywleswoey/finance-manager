/**
 * The two editors' floor.
 *
 * `Classify` and `NetWorth` are desktop-optimised BY DECISION. They are checked against
 * four criteria instead of the universal list — reading comfort, row density and tap
 * ergonomics beyond 24px are below this floor deliberately, and asserting them here would
 * be asserting a decision the spec explicitly did not take.
 *
 * The four:
 *
 *   1. Sideways scrolling is confined to a container that visibly IS a table.
 *   2. Nothing overlaps and nothing is clipped.
 *   3. Every control is reachable, readable and tappable at 24px square.
 *   4. No control silently does nothing — and a `title=` tooltip DOES NOT EXIST ON TOUCH,
 *      so any explanation one carries has to be visible text.
 *
 * Criterion 3's geometry already lives in `unconditional.spec.js`, which measures it at all
 * ten viewports because it is a floor rather than a phone rule; what this file adds is the
 * same measurement with the rule modal OPEN, which is the one surface that file cannot see
 * without opening something.
 *
 * WHAT IS SCOPED TO WHICH WIDTH, and why each boundary is the one it is:
 *
 *   - Containment (1) is gated BELOW 1024, the same edge `.pinned` uses and the same edge
 *     `HSCROLL_GATE_APPLIES_BELOW` exempts. Above it the editors are unchanged by decision,
 *     and "unchanged" includes the sticky `<th>` that an `overflow-x: auto` wrapper would
 *     silently kill — see `RESPONSIVE.md`'s trap on that mechanism.
 *   - The reorder button and the nested-scroll neutralisation are BELOW 640, the phone tier.
 *     Hiding the button is what makes the reorder modal unreachable on a phone by design,
 *     which is the whole reason this file has no gates on that modal at phone widths.
 *
 * WHAT THIS FILE CANNOT REACH. `MatchTable` renders only after a rule is parsed, which is a
 * POST the committed fixtures do not carry — they are GET captures from the live database
 * and are not hand-written. So its containment is annotated on every run rather than closed
 * with an invented response.
 */
import { expect, test } from "@playwright/test";
import { HSCROLL_GATE_APPLIES_BELOW, PHONE_TIER_BELOW, VIEWPORTS } from "./viewports.js";
import { openView } from "./support/app.js";
import { declarationsFor } from "./support/css.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

const EDITORS = ["Net Worth", "Spending › Classify"];

/**
 * Every `<table>` under `.main`, with the nearest ancestor that absorbs its sideways
 * scroll — and whether that ancestor is a box holding the table and nothing else.
 *
 * "Visibly is a table" is not a claim about appearance that a test can make. What it
 * reduces to structurally is: the scrolling box wraps the table alone, so what slides under
 * your finger is the grid of numbers rather than the card, the heading and the save button
 * with it. A sheet or a card with `overflow: auto` on it satisfies "the pane does not
 * scroll" and fails this.
 */
function tableContainment(page) {
  return page.evaluate(() => {
    const main = document.querySelector(".main");
    const name = (el) => {
      const cls = typeof el.className === "string" && el.className
        ? "." + el.className.trim().split(/\s+/).join(".") : "";
      return el.tagName.toLowerCase() + cls;
    };
    return [...main.querySelectorAll("table")].map((t) => {
      let box = null;
      for (let el = t.parentElement; el && el !== main; el = el.parentElement) {
        const ox = getComputedStyle(el).overflowX;
        if (ox === "auto" || ox === "scroll") { box = el; break; }
      }
      const headers = [...t.querySelectorAll("thead th")]
        .map((th) => th.textContent.trim()).filter(Boolean);
      return {
        table: headers.slice(0, 2).join("/") || "(unheaded)",
        container: box ? name(box) : null,
        // The box holds the table and nothing else.
        wrapsTableAlone: box ? box.children.length === 1 && box.firstElementChild === t : null,
        // ...and does not itself push its parent wide, which is how an "absorbing" wrapper
        // that absorbs nothing passes the first two checks and still overflows the pane.
        fitsItsParent: box
          ? box.getBoundingClientRect().width <= box.parentElement.clientWidth + 1
          : null,
      };
    });
  });
}

/**
 * Every element under `.main` carrying a `title=`, described.
 *
 * Asserted as *empty* rather than as a list of the five that existed when this landed, which
 * is the difference between a gate and a note: a sixth tooltip cannot arrive quietly. Scoped
 * to `.main` because the drawer's signed-in email carries one and is not either editor's —
 * both modals render inside `.fillpane`, so scoping does not lose them.
 */
function titledUnderMain(page) {
  return page.$$eval(".main [title]", (els) =>
    els.map((el) => `${el.tagName.toLowerCase()}[title="${el.getAttribute("title")}"]`));
}

test.describe("sideways scroll is confined to a container that is the table alone", () => {
  // The pin tier's edge, not the phone tier's: above 1024 the editors are unchanged by
  // decision, and the horizontal gate is exempt there for the same reason.
  test.skip(({ viewport }) => viewport.width >= HSCROLL_GATE_APPLIES_BELOW,
    "at and above 1024 the editors are unchanged, wrappers included");

  for (const viewName of EDITORS) {
    test(viewName, async ({ page, baseURL }) => {
      await openView(page, baseURL, viewName);
      const tables = await tableContainment(page);
      expect(tables.length, `${viewName} rendered no table`).toBeGreaterThan(0);

      for (const t of tables) {
        expect.soft(t.container,
          `"${t.table}" has no scrolling container — its overflow reaches .main`).not.toBeNull();
        expect.soft(t.wrapsTableAlone,
          `"${t.table}" scrolls inside ${t.container}, which holds more than the table`).toBe(true);
        expect.soft(t.fitsItsParent,
          `${t.container} is wider than its own parent — it absorbs nothing`).toBe(true);
      }
    });
  }
});

test.describe("the reorder button, and the modal it is the only way to", () => {
  const reorder = (page) => page.getByRole("button", { name: /Reorder/ });

  test("Spending › Classify", async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    await openView(page, baseURL, "Spending › Classify");

    if (vp.width < PHONE_TIER_BELOW) {
      // Drag-to-reorder has no touch equivalent and the rules list carries no drag at all,
      // so the whole feature is behind this one button. Hiding it is the phone fix, and the
      // modal being unreachable below the tier is the consequence rather than a gap.
      await expect(reorder(page),
        "the reorder button is reachable on a phone, where its modal cannot be used").toBeHidden();
    } else {
      await expect(reorder(page)).toBeVisible();
      // Reachable AND usable: 67 rules in the fixtures, so it is not the disabled state.
      await expect(reorder(page)).toBeEnabled();
    }
  });
});

test.describe("the editor's nested scroll", () => {
  // The `.fillpane` / `.grow` / `.scroll` machinery has exactly one user in the whole app,
  // and it is this view. Below the tier it is neutralised so the screen scrolls as one
  // page — which deletes the app's deepest nesting rather than merely tolerating it.
  test("Spending › Classify", async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    await openView(page, baseURL, "Spending › Classify");

    const geometry = await page.evaluate(() => {
      const of = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const s = getComputedStyle(el);
        return {
          display: s.display, overflowX: s.overflowX, overflowY: s.overflowY,
          scrolls: el.scrollHeight > el.clientHeight + 1,
        };
      };
      return { main: of(".main"), pane: of(".fillpane"), grow: of(".fillpane>.grow"), scroll: of(".fillpane>.grow>.scroll") };
    });

    expect(geometry.pane, "Classify no longer renders a .fillpane").not.toBeNull();
    expect(geometry.scroll, "Classify no longer renders a .scroll").not.toBeNull();

    if (vp.width < PHONE_TIER_BELOW) {
      expect.soft(geometry.pane.display, "the pane is still a flex column").toBe("block");
      expect.soft(geometry.grow.display).toBe("block");
      expect.soft(geometry.grow.overflowX, "`overflow: hidden` on a block that no longer gets a height clips it")
        .toBe("visible");
      // The whole claim, in one number: the inner box does not scroll vertically, because
      // with no flex parent to cap it, it sizes to its own content.
      expect.soft(geometry.scroll.scrolls,
        "the unclassified list still owns a vertical scroll of its own").toBe(false);
      expect.soft(geometry.main.scrolls, "nothing scrolls — the page is not the scroller").toBe(true);
      // ...and it is still the table's horizontal container. `overflow-x: auto` is what
      // survives the neutralisation; it is also what forces `overflow-y` to `auto`, which
      // is exactly why sizing to content is the whole fix rather than half of one.
      expect.soft(geometry.scroll.overflowX).toBe("auto");
    } else {
      // Desktop unchanged: the funnel owns the vertical scroll and the pane does not.
      expect.soft(geometry.pane.display).toBe("flex");
      expect.soft(geometry.grow.overflowX).toBe("hidden");
      expect.soft(geometry.scroll.scrolls, "the funnel stopped owning its scroll above the tier").toBe(true);
      // ...EXCEPT ON A ROTATED PHONE, and that is a pre-existing property of the machinery
      // rather than anything this slice did. 844x390 is 390px tall, and Classify's tiles
      // plus its 232px-capped rules card already exceed that before the funnel is given a
      // pixel — so there is nothing left for `.fillpane` to fill and `.main` scrolls after
      // all. The tier is written in width, the failure is in height, and 844x390 is the one
      // viewport where those disagree. Recorded rather than asserted away: below 640 the
      // neutralisation makes this the *intended* behaviour, so a gate here would be
      // claiming the opposite thing 200px to the left.
      if (vp.height >= 500) {
        expect.soft(geometry.main.scrolls, "the main pane scrolls — the fillpane stopped filling it").toBe(false);
      } else {
        testInfo.annotations.push({
          type: "rotated-phone",
          description: `.main scrolls: ${geometry.main.scrolls} — the fixed content above the funnel exceeds a 390px-tall pane`,
        });
      }
    }
  });
});

test("the net-worth row grid is unchanged at every width", async ({ page, baseURL }) => {
  // Written as an assertion because the instinct is to shrink it. At the phone gutter the
  // label column is 124px, not the ~200px it looks like, and the column you would reach for
  // is the one that can least afford it under the 16px input rule. Stacking turns 17 rows
  // into ~34 lines and destroys the right-aligned column that makes the form scannable.
  await openView(page, baseURL, "Net Worth");

  const rules = await declarationsFor(page, ".nw-row");
  expect(rules, "`.nw-row` is written more than once — a tier rule arrived").toHaveLength(1);
  expect(rules[0].media, "`.nw-row` grew a media query").toBeNull();

  const tracks = await page.$eval(".nw-row", (el) =>
    getComputedStyle(el).gridTemplateColumns.split(/\s+/).filter(Boolean));
  expect(tracks, "the row is no longer three columns").toHaveLength(3);
  expect(tracks[1], "the value column moved").toBe("120px");
  expect(tracks[2], "the currency column moved").toBe("70px");
});

test.describe("the rule modal", () => {
  test("is usable at this width, and every control in it clears 24px",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      await openView(page, baseURL, "Spending › Classify");
      await page.getByRole("button", { name: "+ Propose a rule" }).click();

      const sheet = page.getByTestId("rule-sheet");
      await expect(sheet).toBeVisible();

      const box = await sheet.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return { top: r.top, bottom: r.bottom, maxHeight: s.maxHeight,
                 hOverflow: el.scrollWidth - el.clientWidth };
      });
      // `svh`, not `vh`. Emulation cannot tell the two apart — there is no retractable
      // toolbar here — so what this can say is that the cap is still 84% of the screen and
      // has not been dropped or rewritten as a pixel constant. `inventory.spec.js` holds
      // the half that can see the unit, by forbidding `vh` under `web/src` outright.
      expect(Math.round(parseFloat(box.maxHeight)), "the sheet's cap is not 84% of the viewport")
        .toBe(Math.round(vp.height * 0.84));
      expect(box.top, "the sheet starts above the top of the screen").toBeGreaterThanOrEqual(0);
      expect(Math.ceil(box.bottom), "the sheet runs off the bottom of the screen")
        .toBeLessThanOrEqual(vp.height);
      // Criterion 1 again, inside the modal: the sheet is not a horizontal scroller. If a
      // control is too wide for 390px the fix is for it to wrap, not for the buttons to
      // slide off the edge with it.
      expect(box.hOverflow, "the sheet scrolls sideways — its controls do not fit").toBeLessThanOrEqual(1);

      const controls = await sheet.evaluate((el) =>
        [...el.querySelectorAll("button, input, select, textarea")].map((c) => {
          const r = c.getBoundingClientRect();
          return { w: r.width, h: r.height, text: (c.textContent ?? "").trim().slice(0, 24) };
        }));
      expect(controls.length).toBeGreaterThan(0);
      for (const c of controls) {
        expect.soft(Math.min(c.w, c.h), `"${c.text}" is ${Math.round(c.w)}x${Math.round(c.h)}`)
          .toBeGreaterThanOrEqual(24);
      }

      // THE GAP THIS FILE CANNOT CLOSE, and it is two surfaces rather than one. Everything
      // below `Parse & preview` renders only after a parsed rule, which is a POST the
      // GET-captured fixtures do not carry: `MatchTable`, and the category row whose
      // `max-width: 100%` and `flex-wrap: wrap` are the reason the sheet fits at 390 at all.
      // So the measurement above is taken on the modal's first state only. Annotated on
      // every run rather than closed with a hand-written response — `tests/fixtures/` says
      // why those files are not hand-edited.
      testInfo.annotations.push({
        type: "unreached",
        description: "MatchTable and the CatSelect row — both need POST /compile-preview, which the GET-captured fixtures do not carry",
      });
    });
});

test.describe("no control in an editor is explained by a tooltip alone", () => {
  // Criterion 4. `title=` does not exist on touch: there is no hover, and a long-press is
  // the platform's own text-selection gesture. Anything a tooltip was carrying is either
  // visible text now or was never load-bearing.
  for (const viewName of EDITORS) {
    test(viewName, async ({ page, baseURL }) => {
      await openView(page, baseURL, viewName);
      const titled = await titledUnderMain(page);
      expect(titled, "a hover-only explanation — make it visible text").toEqual([]);
    });
  }

  test("Spending › Classify — with the rule modal open", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Spending › Classify");
    await page.getByRole("button", { name: "+ Propose a rule" }).click();
    await expect(page.locator("textarea")).toBeVisible();
    const titled = await titledUnderMain(page);
    expect(titled, "a hover-only explanation in the modal").toEqual([]);
  });

  test("Spending › Classify — with the reorder modal open", async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    test.skip(vp.width < PHONE_TIER_BELOW, "the reorder modal is unreachable below the tier by design");
    await openView(page, baseURL, "Spending › Classify");
    await page.getByRole("button", { name: /Reorder/ }).click();
    await expect(page.getByRole("button", { name: "Save order" })).toBeVisible();
    const titled = await titledUnderMain(page);
    expect(titled, "a hover-only explanation in the reorder modal").toEqual([]);
  });
});

test("the breakdown says in text which rows it will let you edit", async ({ page, baseURL }) => {
  // The one tooltip in either editor that was carrying something a reader could not get
  // anywhere else: `title="pulled from statements"` on the `auto` pill, which is the whole
  // explanation of why some rows have an input and the rest do not. As visible text it is
  // also the answer to criterion 4's other half — a row whose value you cannot change is
  // not a control that silently does nothing, once something says so.
  await openView(page, baseURL, "Net Worth");
  const note = page.getByTestId("breakdown-legend");
  await expect(note).toBeVisible();
  await expect(note).toContainText(/manual/i);
  await expect(note).toContainText(/statements/i);
});
