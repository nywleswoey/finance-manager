/**
 * Driving the app: fixture interception, and reaching each of the thirteen views.
 *
 * The app has no router — `App.jsx` holds section and tab in React state — so a view is
 * reached by clicking, not by navigating to a URL. That is a property of the app under
 * test, not a shortcut: the same clicks are what a person does, which is what makes the
 * gates measure a real render rather than a mounted component.
 *
 * WHERE THE SHELL IS THE PHONE'S, THE CLICKS ARE DIFFERENT ONES, because the navigation is.
 * The rail is behind a hamburger and the tab strip is a native `<select>`, so `openView`
 * branches on the viewport rather than on a flag: every caller keeps asking for
 * "Spending › Recurring" and gets there the way a person on that viewport would. This is the
 * whole reason the phone shell is the ticket that unblocks the rest — until it lands, no
 * phone behaviour past the first screen can be reached at all.
 *
 * THAT BRANCH IS NOT "BELOW 640px" ANY MORE. The tablet tier put the shell on a height guard
 * as well, so 844×390 gets the drawer and the picker with a 844px width — see `onPhoneShell`
 * in `viewports.js`. Every gate that reaches a view at that viewport goes through this file,
 * so the guard is exercised thirteen views deep rather than only where it is asserted.
 */
import { expect } from "@playwright/test";
import { fixtureFor } from "../fixtures/index.js";
import { onPhoneShell } from "../viewports.js";

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

/**
 * True when the viewport gets the phone navigation shell, where navigation is the drawer.
 *
 * WIDTH *OR* HEIGHT, since the tablet tier landed. A rotated phone is 844px wide and so
 * leaves the phone tier by width, but its 390px of height is what the drawer was chosen
 * against in the first place — so the shell follows `(max-height: 500px)` too, and this
 * helper has to ask the same question the stylesheet does or every gate at 844×390 would go
 * looking for a tab strip that is `display: none`. It is the navigation alone: the pin, the
 * cards, the charts and the gutter are all still width-only.
 */
export const onPhone = (page) => onPhoneShell(page.viewportSize());

/** The drawer's parts, named once so a rename breaks in one place rather than eleven. */
export const menuButton = (page) => page.getByTestId("menu");
export const drawer = (page) => page.locator(".side");
export const scrim = (page) => page.getByTestId("scrim");
export const tabSelect = (page) => page.getByTestId("tabsel");

const section = (page, name) => page.locator(".navitem", { hasText: new RegExp(`^${name}$`) });
const tab = (page, name) => page.locator(".tab", { hasText: new RegExp(`^${name}$`) });

/**
 * Switch section — through the drawer on a phone, straight off the rail above it.
 *
 * The drawer closes itself when a section is chosen, and this waits for that: leaving it
 * open would leave the scrim over the pane every later gate measures through.
 */
async function openSection(page, name) {
  if (!onPhone(page)) return section(page, name).click();
  await menuButton(page).click();
  await section(page, name).click();
  await expect(scrim(page)).toBeHidden();
}

/** Switch tab — the native picker on a phone, the strip above it. */
async function openTabControl(page, name) {
  if (!onPhone(page)) return tab(page, name).click();
  await tabSelect(page).selectOption(name);
}

async function openTab(page, sectionName, tabName, anchor) {
  await openSection(page, sectionName);
  await openTabControl(page, tabName);
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
      await openSection(page, "Net Worth");
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

/**
 * Install the seam, load the app, and open one named view — the two lines every spec that
 * measures a rendered view starts with, written once.
 *
 * Returns the seam, so a caller that wants to report "the view never settled because these
 * paths had no fixture" still can; `baseline.spec.js` is the one that does.
 */
export async function openView(page, baseURL, viewName) {
  const seam = await loadApp(page, baseURL);
  const view = VIEWS.find((v) => v.name === viewName);
  if (!view) throw new Error(`no view named "${viewName}" — check VIEWS`);
  await view.open(page);
  return seam;
}

/**
 * Load the app signed *out*, so the login screen renders instead of the shell.
 *
 * The session endpoint is the app's one auth chokepoint — `AuthGate` turns on it alone —
 * so answering it 401 is the whole of it. The override is registered after `mockApi`'s
 * catch-all on purpose: Playwright matches routes in reverse registration order, so the
 * later, narrower route wins.
 *
 * What renders is not quite what a signed-out person sees: Google Identity Services is
 * cross-origin, so the seam aborts it and the screen shows its own load-failure line where
 * production shows a button. That is the point of the seam rather than a gap in it — every
 * gate this screen carries is about the *box*, which is the same either way, and the GSI
 * button is explicitly carved out of the tap floor because Google exposes no height for it.
 */
export async function loadSignIn(page, baseURL) {
  const seam = await mockApi(page, baseURL);
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "no session" }),
    })
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible({ timeout: 20_000 });
  return seam;
}

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
