/**
 * Driving the app: fixture interception, and reaching each of the thirteen views.
 *
 * The app has no router — `App.jsx` holds section and tab in React state — so a view is
 * reached by clicking, not by navigating to a URL. That is a property of the app under
 * test, not a shortcut: the same clicks are what a person does, which is what makes the
 * gates measure a real render rather than a mounted component.
 */
import { expect } from "@playwright/test";
import { fixtureFor } from "../fixtures/index.js";

/**
 * Serve every API call from committed fixtures and cut the page off from the network.
 *
 * Returns a record of what the page tried to reach that the fixtures did not cover, so a
 * test can assert the seam actually held. Nothing here falls through to a real server: an
 * uncovered `/api/` path is answered with a 404 and recorded, and any cross-origin request
 * — Google's identity script above all — is aborted and recorded.
 */
export async function mockApi(page, baseURL) {
  const seam = { unmatched: [], external: [] };
  const origin = new URL(baseURL).origin;

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.origin !== origin) {
      // The auth gate is satisfied by the mocked session endpoint, so the login screen
      // never renders and Google Identity Services is never requested. Aborting rather
      // than allowing is what turns that into a checkable fact.
      seam.external.push(request.url());
      return route.abort();
    }

    if (url.pathname.startsWith("/ingest/")) {
      // PostHog's same-origin reverse proxy. Analytics is not initialised in a build with
      // no key, but swallow it rather than let a stray beacon reach the preview server.
      return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    }

    if (!url.pathname.startsWith("/api/")) {
      return route.continue();          // the app's own HTML, JS and CSS
    }

    const hit = fixtureFor(url.pathname + url.search);
    if (!hit) {
      seam.unmatched.push(url.pathname + url.search);
      return route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "no fixture captured for this path" }),
      });
    }
    return route.fulfill({
      status: hit.status,
      contentType: "application/json",
      body: JSON.stringify(hit.body),
    });
  });

  return seam;
}

/**
 * Wait until the pane has finished painting.
 *
 * `.loading` doubles as the app's error state ("API not reachable"), so waiting for the
 * class to disappear would hang on a view that failed. Wait for the *word* instead, then
 * for the view's own anchor, so a silently empty pane cannot pass as ready.
 */
async function settle(page, anchor) {
  await expect(page.locator(".main .loading").filter({ hasText: /Loading/ })).toHaveCount(0, {
    timeout: 20_000,
  });
  await expect(anchor(page).first()).toBeVisible({ timeout: 20_000 });
}

const section = (page, name) => page.locator(".navitem", { hasText: new RegExp(`^${name}$`) });
const tab = (page, name) => page.locator(".tab", { hasText: new RegExp(`^${name}$`) });

async function openTab(page, sectionName, tabName, anchor) {
  await section(page, sectionName).click();
  await tab(page, tabName).click();
  await settle(page, anchor);
}

/**
 * The thirteen views, in the order the manual checklist walks them.
 *
 * SecurityDetail is reached the only way it can be — by tapping a Holdings row — because
 * there is no router. PLTR is the row on purpose: 73 option trades is the longest options
 * history in the fixtures, so the view renders at its tallest rather than its emptiest.
 */
export const VIEWS = [
  {
    name: "Portfolio › Overview",
    open: (page) => openTab(page, "Portfolio", "Overview", (p) => p.locator(".tiles")),
  },
  {
    name: "Portfolio › Holdings",
    open: (page) => openTab(page, "Portfolio", "Holdings", (p) => p.getByText(/^Holdings \(\d+\)$/)),
  },
  {
    name: "Portfolio › Performance",
    open: (page) => openTab(page, "Portfolio", "Performance", (p) => p.getByText("Performance roll-up")),
  },
  {
    name: "Portfolio › Dividends",
    open: (page) => openTab(page, "Portfolio", "Dividends", (p) => p.getByText("Annual Dividend Income")),
  },
  {
    name: "Portfolio › Options",
    open: (page) => openTab(page, "Portfolio", "Options", (p) => p.getByText("Realized P/L by Year")),
  },
  {
    name: "Portfolio › Transactions",
    open: (page) => openTab(page, "Portfolio", "Transactions", (p) => p.locator(".card h3")),
  },
  {
    name: "Portfolio › SecurityDetail",
    open: async (page) => {
      await openTab(page, "Portfolio", "Holdings", (p) => p.getByText(/^Holdings \(\d+\)$/));
      await page
        .locator("tbody tr")
        .filter({ has: page.locator("span.pill", { hasText: /^PLTR$/ }) })
        .first()
        .click();
      await settle(page, (p) => p.getByText("← Holdings"));
    },
  },
  {
    name: "Net Worth",
    open: async (page) => {
      await section(page, "Net Worth").click();
      await settle(page, (p) => p.getByTestId("networth-summary"));
    },
  },
  {
    name: "Spending › Overview",
    open: (page) => openTab(page, "Spending", "Overview", (p) => p.getByText("Top Line Items")),
  },
  {
    name: "Spending › By Category",
    open: (page) => openTab(page, "Spending", "By Category", (p) => p.getByText("Expenses by Category")),
  },
  {
    name: "Spending › Classify",
    open: (page) => openTab(page, "Spending", "Classify", (p) => p.getByText(/^Unclassified$/)),
  },
  {
    name: "Spending › Recurring",
    open: (page) => openTab(page, "Spending", "Recurring", (p) => p.locator(".card h3")),
  },
  {
    name: "Spending › Transactions",
    open: (page) => openTab(page, "Spending", "Transactions", (p) => p.locator(".card h3")),
  },
];

/** Load the app with the seam installed and the shell rendered. */
export async function loadApp(page, baseURL) {
  const seam = await mockApi(page, baseURL);
  await page.goto("/");
  await expect(page.locator(".app")).toBeVisible({ timeout: 20_000 });
  return seam;
}

/** Every element in the document whose computed `position` is `fixed`, described. */
export function fixedPositionedElements(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll("*")]
      .filter((el) => getComputedStyle(el).position === "fixed")
      .map((el) => {
        const id = el.id ? `#${el.id}` : "";
        const cls = typeof el.className === "string" && el.className
          ? `.${el.className.trim().split(/\s+/).join(".")}`
          : "";
        return `${el.tagName.toLowerCase()}${id}${cls}`;
      })
  );
}

/**
 * How far the main pane overflows its own box horizontally, in CSS pixels.
 *
 * The gate is about `.main`, not the page: `.main { overflow: auto }` absorbs horizontal
 * overflow before it ever reaches the document, so "no horizontal page scroll" is a
 * criterion that can never fail and therefore never means anything.
 */
export function mainPaneOverflow(page) {
  return page.evaluate(() => {
    const main = document.querySelector(".main");
    if (!main) return null;
    return main.scrollWidth - main.clientWidth;
  });
}
