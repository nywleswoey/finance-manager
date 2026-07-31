---
id: 12
title: The phone navigation shell
type: prototype
status: closed
assignee: nywleswoey
blocked_by: [10]
parent: map-mobile-responsive
---

## Question

What replaces the sidebar-plus-tab-strip chrome on a phone?

Today `App.jsx:76-127` renders two levels of navigation simultaneously, both desktop-shaped:

- **Sections** — a permanently-visible 200px left rail (`.side`, styles.css:9): Portfolio,
  Net Worth, Spending, a dimmed Settings, plus the signed-in email and Sign-out button
  (`.side-user`, :64-67). At 390px wide that rail eats **half the screen**.
- **Tabs** — a horizontal strip inside the section (`.tabs`, :19-22): **6 tabs** for Portfolio
  (Overview / Holdings / Performance / Dividends / Options / Transactions) and **5** for Spending.
  The Portfolio strip also carries a right-aligned "↻ Refresh prices" button and its status message
  (`.tabs-right`, :22). This strip will overflow long before 390px.

Decide, by building a throwaway prototype to react to (`/prototype`, in the manner of
`web/prototypes/classify-prototype.html`):

1. **The section switcher** — off-canvas drawer behind a hamburger, a bottom tab bar, a top
   dropdown, or something else. Weigh thumb reach and the vertical budget it costs against the fact
   that there are only three real sections.
2. **The tab strip** — horizontally scrollable strip, wrap to two rows, collapse into a `<select>`,
   or fold into whatever the section switcher becomes. 6 items is the worst case.
3. **Where "Refresh prices" and its status message go**, given `.tabs-right` has no room.
4. **Where the signed-in email and Sign-out go** once the rail is gone.
5. **The shell's height model** — whether `.app { height:100vh }` (styles.css:8) survives at all,
   and what it becomes. Use the findings from
   [Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md);
   this is where **safe-area insets** get resolved, since anything bottom-anchored sits on the
   iPhone home-bar.

Link the prototype from the resolution. The answer must name the chosen pattern for each of the
five, with the reasoning, so a build session can implement without re-deciding.

## Resolution

**Prototype** (primary source): [`web/prototypes/mobile-shell-prototype.html`](../../web/prototypes/mobile-shell-prototype.html)
— 3 structurally-different shells (A bottom section bar + scrolling tab strip · B hamburger drawer +
native tab select · C one unified destination sheet), switchable via `?variant=` or ←/→, in a 390×844
frame on desktop and full-bleed below 760px. Carries a **HOME BAR** toggle that fakes
`env(safe-area-inset-bottom)` (desktop always reports `0`) and a live-measured `chrome Npx` readout.

**Verdict: Variant B — hamburger drawer + native tab select.**

The deciding trade was the vertical budget. Variant A keeps both nav levels permanently visible and
**measured 147px of chrome, 181px with the home bar — 21% of an 844px screen**, roughly four table
rows or a whole tile row. B and C both measured **48px**. On a dense numeric dashboard that is read,
not flipped through, permanently advertising a rare act does not earn that. B and C tie on cost, so
the smaller diff won: B *reuses the existing `.side` rail verbatim* as drawer content, where C
invents a flattened destination list and a sheet component for the same 48px.

The five, decided:

1. **Section switcher — off-canvas drawer behind a `☰` at the left of the app bar.** Slide-in from
   the left over a scrim; scrim tap closes. Contents are today's `.side` markup unchanged: brand,
   the three `navitem`s, dimmed Settings, `.side-user` footer. There are only three real sections and
   users land in one and stay — a bottom tab bar is priced for frequent switching that does not
   happen here. One `useState` in `App.jsx` (`drawerOpen`) is the whole state cost.
2. **Tab strip — a native `<select>`, filling the app bar between `☰` and `↻`.** 6 items is the worst
   case; a horizontal scroll-strip (tried in variant A) pushes items off-screen with no affordance
   that they exist, while the native picker shows every option in one full-height sheet on one tap,
   costs no custom code, and inherits platform a11y. **It must carry `font-size: 16px`** — per
   [ticket 010](010-mobile-viewport-safe-area-research.md), the inherited 14px makes iOS zoom the
   viewport to `16/14` = 114% on focus and leave it there. Net Worth has no tabs: the select is
   replaced by the section name as plain text.
3. **"Refresh prices" — an icon-only `↻` button at the right end of the app bar**; the text label
   drops on phone, and it renders `…` + disabled while busy. **Its status message becomes a
   transient full-width toast strip immediately below the app bar**, auto-dismissing — a *flex child*
   of the shell, so it pushes content down rather than overlaying it, and cannot collide with the
   home bar. `.tabs-right` ceases to exist under 640px.
4. **Signed-in email + Sign out — the drawer footer, exactly as `.side-user` today**: `margin-top:auto`,
   `border-top`, ellipsised email, ghost button. The rail isn't deleted on phone, it's hidden behind
   the hamburger, so this needs no new home at all. Button grows to the touch-target floor
   ([ticket 015](015-touch-targets-type-scale.md) owns the number).
5. **Height model — the `100svh` column shell.** `.app` keeps `height: 100vh; height: 100svh` (the
   fallback pair from ticket 010) and flips to `flex-direction: column` under 640px. The app bar and
   the toast are ordinary flex children; `.main` stays `flex: 1; overflow: auto` and remains the
   scroll owner. **Nothing is `position: fixed`** — the drawer and scrim are `position: absolute`
   inside the shell, which is what makes the whole shell immune to the iOS keyboard without JS.
   `viewport-fit=cover` goes on the viewport meta. Safe areas: drawer pads
   `padding-bottom: max(16px, env(safe-area-inset-bottom))` and
   `padding-left: max(0px, env(safe-area-inset-left))`; the content pane pads
   `padding-left/right: max(14px, env(safe-area-inset-left/right))` for landscape, which matters on a
   table-heavy dashboard people rotate. **Choosing B makes `safe-area-inset-bottom` almost a
   non-issue** — B has no bottom-anchored chrome at all. That is a real side benefit of the choice.

**Accepted, not fixed: the section is not named anywhere on screen while the drawer is closed.**
Portfolio and Spending both own a tab called "Overview", so `☰ [Overview ▾] ↻` is ambiguous between
them. Both cheap fixes were rejected (a section label in the bar, which competes for width with the
select; and a `Portfolio · Overview` prefix inside the select). You arrive at a view by tapping it —
knowing where you are is not a problem you have on the way out of the drawer you just used.

**Not decided here** (deliberately): the tab-strip decision covers *navigation* chrome only. Whether
`.main`'s nested `.fillpane`/`.grow`/`.scroll` machinery should still let a section own its own
vertical scroll on a phone is now a stateable question — split out as
[Scroll ownership on a phone](020-scroll-ownership-on-phone.md).
