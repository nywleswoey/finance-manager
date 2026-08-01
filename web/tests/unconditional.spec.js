/**
 * The gates that hold at EVERY width, asserted at every width their subject exists at.
 *
 * `baseline.spec.js` is the "desktop is unchanged" ratchet and runs thirteen views past a
 * handful of universal gates. This file is its opposite number: a small set of specific
 * claims, each checked only on the views that carry it, and each of them unconditional by
 * decision — no media query, no `matchMedia`, one code path. That is why they can be
 * asserted here rather than waiting for the phone tier: they are true today, at 360 and at
 * 1440 alike, or the slice is not finished.
 *
 * ONE GATE IS NOW SCOPED, AND THE DISTINCTION MATTERS. The phone shell replaced the
 * labelled refresh control with an icon in the app bar, so below 640 there is no labelled
 * button to measure — `.tabs-right` is `display: none`. The claim did not become
 * conditional; its *subject* stopped rendering, which is a different thing from a rule
 * being overridden in a media block, and it is why that one test skips rather than being
 * softened. `shell.spec.js` carries the icon's own gates. Nothing else here is scoped.
 *
 * Every gate below moved OUT of `RESPONSIVE.md` when it moved in here. The checklist
 * shrinks as behaviour lands; it does not keep a copy.
 *
 * WHAT IS DELIBERATELY NOT HERE. The 1024-1120 band gets visibly worse under these fixes
 * and that is the fix working: `.refresh-btn` was crushing itself to 78x77 with its label
 * on three lines, which made the tab strip *appear* to fit. Stopping the crush reveals an
 * overflow that was always there. The horizontal-overflow ratchet in `baseline.spec.js`
 * does not gate at or above 1024, so the band is not asserted either way — see
 * `HSCROLL_GATE_APPLIES_BELOW`.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW, VIEWPORTS } from "./viewports.js";
import { openView } from "./support/app.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/** Every element matching `sel`, as `{ w, h }` border boxes, measured in the page. */
function boxes(page, sel) {
  return page.$$eval(sel, (els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect();
      return { w: r.width, h: r.height, text: (el.textContent ?? "").trim().slice(0, 30) };
    })
  );
}

test.describe("the refresh control keeps its natural size and its label on one line", () => {
  // Scoped to 640 and up when the phone shell landed, because below it this control no
  // longer exists to measure: the labelled button and the whole `.tabs-right` group it sits
  // in are `display: none`, and Refresh is an icon in the app bar instead. The claim itself
  // did not weaken — a labelled button that fits on one line is still unconditional
  // *wherever the label renders*. `shell.spec.js` owns the icon's own gates below 640.
  test.skip(({ viewport }) => viewport.width < PHONE_TIER_BELOW,
    "below 640 the labelled control is replaced by the app bar's icon");

  test("Portfolio › Overview", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Portfolio › Overview");
    const btn = page.locator(".refresh-btn");

    // One line, stated two ways, because either alone is weak. `white-space: nowrap` says
    // the label cannot wrap; the height says it did not — the crush this replaces was
    // 78x77, three lines of a two-word label, which is exactly what a height check catches
    // and a single computed-style check would not if the rule were later overridden.
    expect(await btn.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
    const box = await btn.boundingBox();
    expect(box.height, "the label wrapped — this is the 78x77 crush").toBeLessThan(45);

    // Natural size: it renders at least as wide as its own content wants to be. A shrunk
    // flex item is narrower than its scrollWidth; `flex: none` is what stops that.
    const { offset, scroll } = await btn.evaluate((el) => ({ offset: el.offsetWidth, scroll: el.scrollWidth }));
    expect(offset, "the button was shrunk below its content").toBeGreaterThanOrEqual(scroll);
  });
});

test.describe("card grids collapse rather than crush, and never produce a third column", () => {
  // Every view with a `.grid2`. All five call sites have exactly two children, which is
  // what makes "never three" a property of the CSS rather than of the data.
  for (const viewName of [
    "Portfolio › Overview",
    "Portfolio › Options",
    "Net Worth",
    "Spending › Overview",
    "Spending › By Category",
  ]) {
    test(viewName, async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      await openView(page, baseURL, viewName);

      const grids = await page.$$eval(".grid2", (els) =>
        els.map((el) => ({
          tracks: getComputedStyle(el).gridTemplateColumns.split(/\s+/).filter(Boolean).length,
          children: el.children.length,
          width: el.getBoundingClientRect().width,
        }))
      );
      expect(grids.length, `${viewName} has no .grid2`).toBeGreaterThan(0);

      for (const g of grids) {
        expect(g.children, "a .grid2 with three children makes 'never three columns' a data fact")
          .toBe(2);
        expect(g.tracks, "three columns — auto-fit was given room for a track it must not have")
          .toBeLessThanOrEqual(2);
        // Two tracks need 420 + 18 + 420 of grid box. Below that it must be one, which is
        // the collapse; above it, two, which is desktop unchanged.
        expect(g.tracks, `${g.tracks} tracks in a ${Math.round(g.width)}px grid at ${vp.name}`)
          .toBe(g.width >= 858 ? 2 : 1);
      }
    });
  }
});

test.describe("the tab strip wraps rather than crushing its neighbour", () => {
  test("Portfolio", async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    await openView(page, baseURL, "Portfolio › Overview");
    const tabs = page.locator(".tabs").first();

    // Still asserted below 640, where the strip is `display: none`, because the wrap rule
    // itself is still unconditional — the phone tier hides the strip, it does not restyle
    // it — and a computed value survives `display: none`. If someone later moves
    // `flex-wrap` into a media block, this notices at four viewports.
    expect(await tabs.evaluate((el) => getComputedStyle(el).flexWrap)).toBe("wrap");

    // The no-op half of the claim, and the reason this file needed a tenth viewport: at
    // 1280 AND 1440 the strip fits on one line, so wrapping changes nothing there. One
    // desktop width cannot tell "it fits" from "it fits at exactly 1280".
    if (vp.width >= 1280) {
      const rows = await tabs.evaluate((el) =>
        new Set([...el.children].map((c) => Math.round(c.getBoundingClientRect().top))).size
      );
      expect(rows, `the strip wrapped at ${vp.width}px — desktop is not unchanged`).toBe(1);
    }
  });
});

test.describe("every editor control is at least 24px square", () => {
  // The two editors' own floor: 24px is WCAG 2.5.8, and `.nw-del` failed it on the desktop
  // these views are optimised for. Comfort beyond 24px is deliberately below the floor
  // here — that is the 44px target the fully-responsive views get, not this one.
  test("Net Worth", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Net Worth");
    const controls = await boxes(page, ".main button, .main input, .main select");
    expect(controls.length).toBeGreaterThan(0);
    for (const c of controls) {
      expect.soft(Math.min(c.w, c.h), `"${c.text}" is ${Math.round(c.w)}x${Math.round(c.h)}`)
        .toBeGreaterThanOrEqual(24);
    }
  });

  test("Spending › Classify", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Spending › Classify");
    // `.link-btn` included: seven of Classify's controls are one, at ~21px tall before this
    // slice. The 44px comfort target for the *fully responsive* views — Recurring's three
    // `.link-btn`s among them — is phone-only and lands with the phone tier, not here.
    const controls = await boxes(page, ".main button, .main input, .main select");
    expect(controls.length).toBeGreaterThan(0);
    for (const c of controls) {
      expect.soft(Math.min(c.w, c.h), `"${c.text}" is ${Math.round(c.w)}x${Math.round(c.h)}`)
        .toBeGreaterThanOrEqual(24);
    }
  });
});

test("the rule text area matches the app's dark styling", async ({ page, baseURL }) => {
  // The `textarea` exists only inside `RuleModal`, so this is the one gate in the file that
  // has to open something. It rendered UA-default — a white box on a dark modal — because
  // `styles.css`'s form rule named `input, select` and not `textarea`.
  await openView(page, baseURL, "Spending › Classify");
  await page.getByRole("button", { name: "+ Propose a rule" }).click();
  const box = page.locator("textarea");
  await expect(box).toBeVisible();

  const style = await box.evaluate((el) => {
    const s = getComputedStyle(el);
    return { bg: s.backgroundColor, colour: s.color, family: s.fontFamily };
  });
  // `--panel2` and `--txt`. Named as values rather than as "not white" so a future palette
  // change reads as a deliberate edit here rather than as a test that quietly stops meaning
  // anything.
  expect(style.bg, "the textarea is still UA-default — a white box on a dark modal")
    .toBe("rgb(28, 35, 44)");
  expect(style.colour).toBe("rgb(215, 221, 228)");
  expect(style.family, "`font: inherit` — the UA's monospace default is the other half of the tell")
    .not.toMatch(/monospace/);
});

test.describe("list rows are a full-width track with the fill behind the text", () => {
  for (const viewName of ["Portfolio › Overview", "Spending › Overview", "Spending › By Category"]) {
    test(viewName, async ({ page, baseURL }) => {
      await openView(page, baseURL, viewName);

      const rows = await page.$$eval(".barrow", (els) =>
        els.map((el) => {
          const row = el.getBoundingClientRect();
          const fill = el.querySelector(".barfill");
          const name = el.querySelector(".nm");
          return {
            rowWidth: row.width,
            fillWidth: fill ? fill.getBoundingClientRect().width : null,
            fillPosition: fill ? getComputedStyle(fill).position : null,
            nameWidth: name ? name.getBoundingClientRect().width : null,
            nameFlex: name ? getComputedStyle(name).flexGrow : null,
          };
        })
      );
      expect(rows.length, `${viewName} rendered no .barrow rows`).toBeGreaterThan(0);

      for (const r of rows) {
        // Behind the text, not beside it.
        expect(r.fillPosition, "the fill is laid out in flow — it is beside the text, not behind it")
          .toBe("absolute");
        // Full-width track: the fill is a percentage of the row, so it can reach the row's
        // own width. The 220px constant it replaces could not, and stopped being
        // proportional the moment the card was wider than 220.
        expect(r.fillWidth).toBeLessThanOrEqual(r.rowWidth + 1);
        // No 130px name column: the name takes what is left rather than reserving.
        expect(r.nameFlex, "the name is not a growing flex child — the fixed column is back")
          .not.toBe("0");
        expect(r.nameWidth, "the name is pinned at the old 130px column width")
          .not.toBe(130);
      }
    });
  }
});

test.describe("the options tables lead with a merged identity cell", () => {
  for (const [viewName, leadingHeader] of [
    ["Portfolio › Options", "Underlying"],   // the ledger pins Underlying; Contract follows it
    ["Portfolio › SecurityDetail", "Contract"],
  ]) {
    test(viewName, async ({ page, baseURL }) => {
      await openView(page, baseURL, viewName);

      // The options table is the one with a `Contract` header. Find it by that, not by
      // index — `SecurityDetail` has three tables and `Options` has three.
      const table = page.locator("table").filter({ has: page.locator("th", { hasText: /^Contract$/ }) });
      await expect(table, `${viewName} has no table with a Contract column`).toHaveCount(1);

      // `textContent`, not `innerText`: `th` is `text-transform: uppercase`, so the rendered
      // text would compare the stylesheet rather than the markup.
      const headers = await table.locator("thead th")
        .evaluateAll((els) => els.map((el) => el.textContent.trim()));
      expect(headers[0]).toBe(leadingHeader);
      expect(headers).toContain("Contract");

      // Type, Strike and Qty are gone as columns — the whole point, since pinning `Type`
      // gives you a landmark reading Put / Put / Call.
      for (const gone of ["Type", "Strike", "Qty"]) {
        expect(headers, `${gone} is still its own column`).not.toContain(gone);
      }

      // And the cell that replaced them carries all four facts, on two lines.
      const cell = table.locator("tbody td.contract").first();
      await expect(cell).toBeVisible();
      const lines = await cell.evaluate((el) => [...el.children].length);
      expect(lines, "the Contract cell is not two lines").toBe(2);
      await expect(cell.locator(".contract-terms")).toContainText("×");
    });
  }
});
