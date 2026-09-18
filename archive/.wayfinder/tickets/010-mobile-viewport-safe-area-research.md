---
id: 10
title: Mobile viewport units, safe areas & input zoom — research
type: research
status: closed
assignee: nywleswoey
blocked_by: []
parent: map-mobile-responsive
---

## Question

What are the current, correct answers for the four mobile-browser viewport behaviours this app is
about to collide with? Capture findings as `research/mobile-viewport-safe-area.md`.

1. **Viewport height.** `styles.css:8` sets `.app { height: 100vh }`. On iOS Safari and Chrome
   Android, what does `100vh` actually resolve to with the URL bar shown vs hidden, and what is
   the current recommended replacement — `100dvh`, `100svh`/`100lvh`, or
   `-webkit-fill-available`? Browser support as of now, and the failure mode of each.

2. **Safe-area insets.** What `viewport-fit=cover` + `env(safe-area-inset-*)` requires in
   `web/index.html`'s meta viewport tag, and what breaks if the meta tag is not changed. Which
   insets matter for a bottom-anchored element (home-bar) vs a top-anchored one (notch/Dynamic
   Island), and how insets interact with `position: fixed`.

3. **Input auto-zoom on iOS.** Body font is `14px` (`styles.css:7`) and `input, select` inherit it
   (`:47-48`). iOS Safari zooms the viewport on focus when a form control's font-size is below a
   threshold — confirm the exact threshold, whether it still applies on current iOS, and the
   accepted fixes (16px controls vs `maximum-scale=1` and why the latter is discouraged).

4. **Virtual keyboard.** When the on-screen keyboard opens, how does it affect viewport height,
   `position: fixed` elements, and dynamic viewport units? Note the `interactiveWidget` viewport
   meta value and the VirtualKeyboard API if relevant.

**Why it's blocking.** [The phone navigation shell](012-phone-navigation-shell.md),
[Touch targets & type scale](015-touch-targets-type-scale.md) and
[Sign-in on a phone](016-sign-in-on-phone.md) each hinge on these facts. Prefer primary sources
(MDN, WHATWG/CSSWG specs, WebKit and Chrome release notes) over blog posts.

## Resolution

Full findings: [mobile-viewport-safe-area.md](../research/mobile-viewport-safe-area.md) (519 lines,
sources cited inline). Captured on throwaway branch `research/mobile-viewport-safe-area`, commit
`516866e`.

**1. Viewport height → `100svh`, not `dvh`.** `100vh` is spec-defined to equal `100lvh` — the height
*as if the toolbar were retracted*. The decisive local fact: this shell **owns its own scroll**
(`.main { overflow:auto }` styles.css:14, plus the `.fillpane`/`.grow`/`.scroll` machinery :15-18),
so the document never scrolls, so **the toolbar never retracts**. The overflowing strip is therefore
permanently unreachable — not cosmetic: a bottom-anchored nav placed there would be invisible and
untappable. In a non-scrolling shell `svh` ≡ `dvh`, so `svh` wins on stability (cannot reflow
mid-interaction). Write as a fallback pair: `height: 100vh; height: 100svh;`.

**2. Safe areas → add `viewport-fit=cover`.** Without it every `env(safe-area-inset-*)` resolves to
`0` and any safe-area CSS is dead code. Also, on Chrome 135+ Android, omitting it inherits the
dynamic "chin" that resizes the viewport during scroll — a moving target under an `svh` shell. The
insets that actually matter here are **`bottom`** (home/gesture bar) and **`left`/`right` in
landscape** (notch) — *not* `top`. Pad with `max(<padding>, env(...))`; never offset.

**3. Input zoom → 16px controls on phone, and `maximum-scale=1` is not an option.** The threshold is
not a boolean — WebKit computes `scale = clampTo(16 / fontSize, min, max)`
(`WKWebViewIOS.mm:1756-7`), so today's 14px controls (styles.css:47-48 `font: inherit` ← :7) zoom the
viewport to **114%** on every focus and leave it there. `maximum-scale=1` / `user-scalable=no` do
provably suppress it (iOS's "always allow zoom" a11y override deliberately does *not* re-enable it),
but violate WCAG 1.4.4. Bump **controls only** — a 16px `body` would reflow the dense numeric tables.

**4. Virtual keyboard → do nothing; solve it structurally.** `interactive-widget` is unimplemented in
WebKit (bug 259770, `NEW`, last touched 2026-07-28) and the VirtualKeyboard API likewise (bug 230225,
`NEW`) — neither helps an iPhone-first app. Instead make the phone nav a **flex child of the `svh`
shell rather than `position: fixed`**: that removes the entire bug class with zero JS, since
`position: fixed` bottom chrome is the one construction that genuinely breaks under an iOS keyboard.
(Also noted: the app has almost no keyboard surface — `auth.jsx` has no text input at all, only the
Google-rendered button.)

**Net diff this implies**, all inside the spec's scope:

```
index.html:5      viewport meta   + viewport-fit=cover
styles.css:8      .app            height: 100vh  →  height: 100vh; height: 100svh;
styles.css:47-48  input, select   + font-size: 16px  (inside the <640px media query)
auth.jsx:50,125   minHeight       "100vh"  →  "100svh"
```

**Constraint handed downstream.** [The phone navigation shell](012-phone-navigation-shell.md) is no
longer free to choose `position: fixed` for bottom-anchored chrome — finding 4 rules it out on
grounds that have nothing to do with taste.

### Corrected in the build

**The `height: 100vh; height: 100svh;` fallback pair was not built.** Finding 1 prescribes it for
`styles.css:8`; the foundations slice ships `height: 100svh` alone, on the acceptance criterion "no
`100vh` remains in the shell or on sign-in" — and `inventory.spec.js` now asserts that as a source
grep, so the pair cannot come back without amending the gate. The grounds are
[016](016-sign-in-on-phone.md)'s own, applied one file wider than it applied them: `svh` is Safari
15.4 / Chrome 108 / Firefox 101, universally available since 2022. The residual risk that finding 1
was guarding — a browser with no `svh` collapsing `.app`'s height — is real and accepted rather than
denied; it is the one place the shell is less defended than the ticket asked for.

**The phone gutter guards all four sides, `top` included** (`max(14px, env(safe-area-inset-top))`),
where finding 2 says the insets that matter "are **`bottom`** and **`left`/`right` in landscape** —
*not* `top`". Both are right at their own moment: with no app bar yet, `.main` *is* the top of the
viewport. The finding becomes true again the moment the shell lands, and that is written down as a
trap in [`RESPONSIVE.md`](../../RESPONSIVE.md) rather than left for a reader to rediscover.
