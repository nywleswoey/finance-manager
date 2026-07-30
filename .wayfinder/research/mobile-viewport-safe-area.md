# Mobile viewport units, safe areas & input zoom

## Question

What are the current (2026-07-30), correct answers for the four mobile-browser viewport behaviours
`web/` is about to collide with?

1. **Viewport height** — what `100vh` actually resolves to on iOS Safari and Chrome Android with the
   URL bar shown vs hidden, and what replaces it (`dvh` / `svh` / `lvh` / `-webkit-fill-available`).
2. **Safe-area insets** — what `viewport-fit=cover` + `env(safe-area-inset-*)` needs in the meta
   viewport tag, what breaks without it, which insets matter top vs bottom, and how insets interact
   with `position: fixed`.
3. **Input auto-zoom on iOS** — the exact threshold, whether it still applies, and the accepted fixes.
4. **Virtual keyboard** — effect on viewport height, `position: fixed`, and dynamic viewport units;
   the `interactive-widget` meta key and the VirtualKeyboard API.

---

## Recommendation

**The four decisions, up front.**

1. **Use `100svh`, not `100dvh`.** Change `styles.css:8` from `.app { display: flex; height: 100vh; }`
   to a two-line fallback pair — `height: 100vh; height: 100svh;`. This app's shell **owns its own
   scroll** (`.main { overflow: auto }`, styles.css:14; the `.fillpane`/`.grow`/`.scroll` machinery,
   styles.css:15-18), so the document itself never scrolls, so the browser's retractable toolbar
   **never retracts**. `100vh` is spec-defined to equal `100lvh` — the height *as if the toolbar were
   hidden* — which in this app is a height that is permanently taller than the visible area and can
   never be scrolled to. That is not a cosmetic bug: the bottom strip of the shell is unreachable, so
   a bottom-anchored phone nav (ticket 012) placed there would be invisible and untappable. `svh` and
   `dvh` resolve to the same number in a non-scrolling shell; pick `svh` because it is *stable* and
   cannot reflow mid-interaction. Do the same at `auth.jsx:50` and `auth.jsx:125` (`minHeight: "100vh"`).
2. **Add `viewport-fit=cover`.** Change `index.html:5` to
   `<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />`.
   Without it every `env(safe-area-inset-*)` resolves to `0` and the safe-area CSS is dead code — and
   on Chrome 135+ Android you inherit the dynamic "chin" bar, which resizes the viewport as the user
   scrolls, i.e. a moving target underneath an `svh`-sized shell. With it, you take on the obligation
   to pad manually: `padding-bottom: max(<your padding>, env(safe-area-inset-bottom))` on any
   bottom-anchored chrome, and `padding-left/right: max(..., env(safe-area-inset-left/right))` for
   landscape (which matters here — this is a table-heavy dashboard people will rotate).
3. **Set form controls to 16px on phone. Do not use `maximum-scale=1`.** `styles.css:47-48` has
   `input, select { … font: inherit }`, inheriting the `14px` body font from `styles.css:7`. iOS
   computes its focus zoom as literally `16 / fontSize` (WebKit source, quoted in §3), so 14px inputs
   zoom the viewport to **114%** on every focus and leave it there. Add
   `input, select, textarea { font-size: 16px }` inside the phone media query. Bump the controls only,
   not `body` — a 16px body would reflow the dense numeric tables.
4. **Do nothing about the virtual keyboard.** `interactive-widget` is **not implemented in Safari**
   (WebKit bug 259770, still `NEW` as of 2026-07-28) and the VirtualKeyboard API is **not implemented
   in Safari or Firefox** (WebKit bug 230225, still `NEW`). Neither helps an iPhone-first app. Instead,
   make the phone nav a **flex child of the `svh`-sized shell**, not `position: fixed`. A flex child of
   a fixed-height shell is untouched by the keyboard on both platforms and needs zero JavaScript; a
   `position: fixed` bottom bar is the one construction that genuinely breaks under an iOS keyboard.

**Net diff implied by this research** (three files, all in the mobile-responsive spec's scope):

```
index.html:5      viewport meta   + viewport-fit=cover
styles.css:8      .app            height: 100vh  →  height: 100vh; height: 100svh;
styles.css:47-48  input, select   + font-size: 16px  (inside the <640px media query)
auth.jsx:50,125   minHeight       "100vh"  →  "100svh"
```

---

## 1. Viewport height: what `100vh` actually is, and what to use instead

### What the spec says `vh` is

CSS Values and Units Level 4 defines three viewport sizes, and pins the unprefixed units to the
largest one:

> "The **small** viewport-percentage units (`sv*`) are defined with respect to the small viewport
> size: the viewport sized assuming any UA interfaces that are dynamically expanded and retracted to
> be **expanded**."
>
> "The **large** viewport-percentage units (`lv*`) **and default viewport-percentage units (`v*`)**
> are defined with respect to the large viewport size: the viewport sized assuming any UA interfaces
> that are dynamically expanded and retracted to be **retracted**."
>
> "The **dynamic** viewport-percentage units (`dv*`) are defined with respect to the dynamic viewport
> size: the viewport sized with dynamic consideration of any UA interfaces that are dynamically
> expanded and retracted."
>
> — [CSS Values 4 §6.1.2, viewport-relative lengths](https://www.w3.org/TR/css-values-4/#viewport-relative-lengths)

The spec is explicit that mapping `v*` to `lv*` is not an accident: "the mapping to the large
viewport-percentage units is presumed to be required for Web compatibility". MDN states the same as
observed fact: *"Currently, all default viewport units (`vh`, `vw`, etc.) are equivalent to their
large viewport counterparts (`lvh`, `lvw`, etc.)."*
([MDN, `<length>`](https://developer.mozilla.org/en-US/docs/Web/CSS/length))

### What that means per engine

**Chrome on Android.** Chrome documents this behaviour directly:

> "`vh` units will be sized to the viewport height as if the URL bar is always hidden" — and
> separately, "the ICB will not resize when the URL bar is hidden. Instead, it will remain the same
> height, as if the URL bar were always showing."
>
> — [Chrome for Developers, *URL bar resizing*](https://developer.chrome.com/blog/url-bar-resizing)

So on Chrome Android, `100vh` is *bigger* than the visible area whenever the URL bar is shown, and
percentage heights (`height: 100%`, which resolve against the ICB) are *smaller* than visible when the
URL bar is hidden. The same doc notes a third behaviour that matters for §2 and §4: *"a
`position: fixed` element whose containing block is the ICB will resize in response to the URL bar
showing or hiding."*

**iOS Safari.** Same shape, and Chrome explicitly says the 56+ change was made to align with it. WebKit
shipped the new units first, in Safari 15.4, framing the problem as: *"Web developers often ask for a
tool that would work similar to existing viewport units, but work better on mobile devices where the
dimensions of the browser's viewport change as a user scrolls the page."*
([WebKit, *New WebKit Features in Safari 15.4*](https://webkit.org/blog/12445/new-webkit-features-in-safari-15-4/))

### The specific failure in this app

The load-bearing detail is that **`web/`'s shell never scrolls the document**. `.app { height: 100vh }`
(styles.css:8) is a flex row; `.main` is `overflow: auto` (styles.css:14); the `.fillpane`/`.grow`/
`.scroll` chain (styles.css:15-18) exists precisely so an inner pane owns the vertical scroll. Toolbar
retraction on both engines is driven by **main-frame scroll**, and there is none. Therefore:

- The toolbar is permanently **expanded** ⇒ the visible area is permanently the **small** viewport.
- `100vh` = `100lvh` = the **large** viewport ⇒ the shell is taller than the screen by roughly the
  toolbar height, permanently.
- Because the document cannot scroll, that overflowing strip is **unreachable**. Anything anchored to
  the bottom of `.app` is invisible forever.

This makes the choice easy rather than a trade-off: in a non-scrolling shell, `svh` and `dvh` resolve
to the *same* number, so you get `dvh`'s correctness for free while keeping `svh`'s stability.

### The four candidates, and how each fails

| Candidate | Verdict | Failure mode |
|---|---|---|
| `100vh` (status quo, styles.css:8) | **Wrong** | Spec-mapped to `lvh`. Shell is toolbar-height taller than the screen, and the overflow is unscrollable because the document doesn't scroll. Kills a bottom nav. |
| `100lvh` | **Wrong** | Identical to `100vh`. Explicitly the same value per the spec. |
| `100dvh` | **Acceptable, not chosen** | Correct value, but MDN warns dynamic units are *"NOT stable — sizes change even when viewport itself unchanged"* and *"can cause content to resize while user is scrolling, degrading UI and causing performance hits"* ([MDN `<length>`](https://developer.mozilla.org/en-US/docs/Web/CSS/length)). Harmless in today's non-scrolling shell, but it silently becomes a reflow-on-scroll hazard the moment any view lets the document scroll — a live risk given the map's open "nested-scroll machinery" question. |
| **`100svh`** | **Recommended** | Stable, and never taller than the visible area. Only downside: if the toolbar ever *did* retract you'd get dead space at the bottom. In this shell it can't. |
| `-webkit-fill-available` | **Reject** | Non-standard. MDN: *"The `stretch` value provides a standard replacement, but `-webkit-fill-available` is supported as an alias by browsers for backwards-compatibility reasons"* ([MDN, WebKit extensions](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Webkit_extensions)). The historical Blink/WebKit behavioural divergence is exactly why it produced the folklore it did. The standard `stretch` keyword only reached Safari in the **27 beta** ([WebKit, *Safari 27 beta*](https://webkit.org/blog/17967/news-from-wwdc26-webkit-in-safari-27-beta/)) — far too new to depend on, and it solves a different problem (fill the *parent*, not the *viewport*). |

### Browser support — verified, not recalled

Small/large/dynamic viewport units: **Chrome/Edge 108, Safari & iOS Safari 15.4, Firefox 101, Samsung
Internet 21, Opera 94**; **92.52% global usage**
([caniuse: viewport-unit-variants](https://caniuse.com/viewport-unit-variants)). caniuse's mobile
columns list only the current shipping version (it renders "Chrome for Android 150"), which reflects
today's release, not the introduction point — the Blink introduction point is 108, shared with desktop
Chrome. WebKit shipped them first, in [Safari 15.4](https://webkit.org/blog/12445/new-webkit-features-in-safari-15-4/).

Because 15.4 (March 2022) predates every iOS version realistically in the field, the `height: 100vh;`
fallback line is belt-and-braces rather than a live requirement — but it costs one line and makes the
intent legible.

---

## 2. Safe-area insets

### What the meta tag needs

`web/index.html:5` is currently:

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
```

It must become:

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
```

`viewport-fit` takes `auto` (default), `contain`, `cover`
([MDN, meta name=viewport](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/meta/name/viewport)).
The spec defines the values in terms of the viewport rectangle itself:

> `contain`: "The initial layout viewport and the visual viewport are set to the largest rectangle
> which is inscribed in the display of the device."
> `cover`: "The initial layout viewport and the visual viewport are set to the circumscribed rectangle
> of the physical screen of the device."
>
> — [CSS Round Display 1, `viewport-fit`](https://drafts.csswg.org/css-round-display-1/#viewport-fit-descriptor)

### What breaks if the meta tag is not changed

**Nothing renders under the notch — but the safe-area CSS becomes dead code.** Under the default
`viewport-fit=auto`, the UA has already inset the viewport inside the safe area, so
`env(safe-area-inset-*)`, which is defined as an inset *"from the edge of the viewport"*
([CSS Environment Variables 1](https://drafts.csswg.org/css-env-1/)), is **`0`**. Every
`calc(1em + env(safe-area-inset-bottom))` silently becomes `calc(1em + 0px)`. WebKit spells out the
default: *"By default, Safari automatically insets content within the display's safe area to avoid the
notch and rounded corners. The page's `background-color` fills the inset area"*
([WebKit, *Designing Websites for iPhone X*](https://webkit.org/blog/7929/designing-websites-for-iphone-x/)).

So the cost of *not* changing it is two-fold:

- **iOS:** you permanently forfeit the notch/home-bar bands to letterboxed `background-color`. On a
  dark dashboard this looks acceptable, but you lose real vertical pixels on a device where you have
  none to spare.
- **Chrome 135+ Android — the bigger one:** without `viewport-fit=cover` you get Chrome's new dynamic
  bottom bar, "the chin". Chrome's guide: *"this chin moves out of the way as you start scrolling and
  **affects the size of the viewport**"*, whereas with `viewport-fit=cover` *"the viewport extend[s] up
  to the bottom edge by default without the chin ever being visible"*
  ([Chrome for Developers, *Edge-to-edge migration guide*](https://developer.chrome.com/docs/css-ui/edge-to-edge)).
  A viewport that resizes underneath an `svh`-sized shell is exactly the instability §1 chose `svh` to
  avoid — so `cover` is not merely "nice for the notch", it's what makes the §1 recommendation hold on
  Android.

The obligation `cover` creates: once the viewport spans the physical screen, **you** must keep content
out of the unsafe bands. Skip that and a bottom nav lands under the home indicator.

### Which insets actually matter, top vs bottom

**Bottom-anchored (the phone nav shell, ticket 012) — `safe-area-inset-bottom`. This is the one that
bites.**

- iOS: the home indicator band (~34px) on any Face-ID-era iPhone.
- Android: the gesture navigation bar. Chrome documents `safe-area-inset-bottom` as *"dynamically
  updat[ing] as the chin moves"*, with `safe-area-max-inset-bottom` being the static maximum, *"typically
  ~36px"* ([Chrome, edge-to-edge](https://developer.chrome.com/docs/css-ui/edge-to-edge)). Chrome
  explicitly recommends laying out against the **max** inset to avoid *"layout thrashing"* from the
  dynamic value changing during scroll. `safe-area-max-inset-*` is the spec's answer to this: the insets
  are *"static values"* tied to their dynamic counterparts ([css-env-1](https://drafts.csswg.org/css-env-1/)),
  which MDN describes as the values *"when all UI features are retracted"*
  ([MDN, `env()`](https://developer.mozilla.org/en-US/docs/Web/CSS/env)).

**Top-anchored (notch / Dynamic Island) — mostly a non-issue in this app.** In portrait iOS Safari the
browser's own top chrome occupies the notch band above the page, so `safe-area-inset-top` is typically
`0`; it becomes non-zero in standalone/PWA display mode, which the map rules **out of scope**. Chrome's
guide likewise says *"Top and side insets typically remain zero on Android."* The app's sticky table
headers (`th { position: sticky; top: 0 }`, styles.css:37) are sticky *inside* `.scroll`, not against
the viewport, so they are not exposed to the top inset at all.

**Landscape left/right — the sleeper.** When an iPhone rotates, the notch/Dynamic Island rotates to a
side edge and `safe-area-inset-left`/`-right` become non-zero. This app is a **table-heavy dashboard**
with `th, td { white-space: nowrap }` (styles.css:36) — landscape is a realistic reading posture, and a
full-bleed horizontally-scrolling table would run its first or last column under the island. WebKit's
own worked example is exactly this case:

```css
padding-left: max(12px, env(safe-area-inset-left));
```

— [WebKit, *Designing Websites for iPhone X*](https://webkit.org/blog/7929/designing-websites-for-iphone-x/).
Use `max()`, not raw `env()`, so the desktop/portrait case keeps its designed padding when the inset
is `0`.

### How insets interact with `position: fixed`

Two independent facts, both of which cut against a `position: fixed` bottom bar:

1. **`position: fixed` is positioned against the layout viewport (ICB), and under `viewport-fit=cover`
   the ICB spans the physical screen.** So `position: fixed; bottom: 0` puts your element's bottom edge
   at the *physical* bottom — underneath the home indicator. The fix is to **pad, not offset**:
   `padding-bottom: max(8px, env(safe-area-inset-bottom))` keeps the element's background bleeding to
   the true edge while lifting its content clear. Offsetting with `bottom: env(...)` instead leaves an
   ugly uncoloured strip below it.
2. **Fixed elements are already unstable relative to the URL bar.** Chrome: *"a `position: fixed`
   element whose containing block is the ICB will resize in response to the URL bar showing or hiding"*
   ([URL bar resizing](https://developer.chrome.com/blog/url-bar-resizing)) — i.e. fixed elements track
   the *visual* viewport for URL-bar purposes but the *layout* viewport for keyboard purposes (§4).
   That split is the root of essentially every mobile fixed-footer bug.

**Recommendation:** avoid `position: fixed` for the shell chrome entirely. Make `.app` a
`flex-direction: column` container at phone width with the nav as an ordinary flex child of the
`100svh` shell. That construction is immune to both facts above, needs no `env()` on the *positioning*
(only `padding-bottom` for the home bar), and — per §4 — is the only bottom-bar pattern that survives
an iOS keyboard without JavaScript.

`env()` support is not a constraint: **94.77% global**, Safari 11.1+/iOS 11.3+, Chrome 69+, Firefox 65+,
Edge 79+ ([caniuse: css-env-function](https://caniuse.com/css-env-function)); MDN records it as
Baseline **widely available since January 2020** ([MDN, `env()`](https://developer.mozilla.org/en-US/docs/Web/CSS/env)).
`safe-area-max-inset-*` is newer and Chrome-led — treat it as progressive enhancement with an
`env(safe-area-max-inset-bottom, 36px)` fallback, not a dependency.

---

## 3. Input auto-zoom on iOS

### The threshold is exactly 16px — and it is a *ratio*, not a boolean

This is confirmable in WebKit source rather than inferred. In
`Source/WebKit/UIProcess/API/ios/WKWebViewIOS.mm`, `-[WKWebView _zoomToFocusRect:…]`, lines **1756-1757**:

```objc
const double webViewStandardFontSize = 16;
scale = clampTo<double>(webViewStandardFontSize / fontSize, minimumScale, maximumScale);
```

— [WebKit/WebKit, `WKWebViewIOS.mm`](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/API/ios/WKWebViewIOS.mm)
(fetched from `raw.githubusercontent.com`, `main`, 2026-07-30)

So the zoom is not "zoom if under 16px" — the target page scale is literally **`16 / fontSize`, clamped
to `[minimumScale, maximumScale]`**:

- `font-size: 16px` ⇒ ratio `1.0` ⇒ clamps to `minimumScale` (`1.0` under `width=device-width`) ⇒ **no zoom**.
- `font-size: 14px` ⇒ ratio `1.143` ⇒ **the viewport zooms to 114%** on focus. That is the current app.
- `font-size: 11px` (`.pill`, styles.css:41; `th`, styles.css:37) ⇒ ratio `1.45` ⇒ 145% if it were a control.

`fontSize` here is `_focusedElementInformation.nodeFontSize`, threaded through from
`-[WKContentView _zoomToRevealFocusedElement]`
([`WKContentViewInteraction.mm`](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/ios/WKContentViewInteraction.mm), ~L2977-2984) —
i.e. the focused element's **computed** font-size, not the declared body value.

### Does it still apply on current iOS?

Yes — this is `main`-branch WebKit as of today, unguarded by any feature flag or version check. The
only gates are in the call site:

```objc
[self _zoomToFocusRect:_focusedElementInformation.interactionRect
    …
    maximumScale:_focusedElementInformation.maximumScaleFactorIgnoringAlwaysScalable
    allowScaling:_focusedElementInformation.allowsUserScalingIgnoringAlwaysScalable
                 && PAL::currentUserInterfaceIdiomIsSmallScreen()
    …];
```

That tells you three things:

- **iPhone only.** `currentUserInterfaceIdiomIsSmallScreen()` excludes iPad.
- **`user-scalable=no` disables it outright.** `allowsUserScalingIgnoringAlwaysScalable()` returns
  `m_configuration.allowsUserScaling` ([`ViewportConfiguration.cpp`](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/page/ViewportConfiguration.cpp) L405-407),
  which is set from `m_viewportArguments.userZoom != 0.` (L555) — i.e. straight from the meta tag.
- **`maximum-scale=1` clamps it away.** `clampTo(16/14, min, 1.0)` = `1.0`.
- **The accessibility override does not save you.** iOS's "always allow zooming" setting is
  `m_forceAlwaysUserScalable`, and `allowsUserScaling()` = `m_forceAlwaysUserScalable || allowsUserScalingIgnoringAlwaysScalable()`
  (L400-402) — but the focus-zoom path deliberately calls the ***IgnoringAlwaysScalable*** variants.
  So the accessibility setting restores pinch-zoom for the user while leaving the author's
  `user-scalable=no` in force for auto-zoom. Suppressing the zoom this way genuinely does take zoom
  away from the user.

### The two fixes, and why only one is acceptable

**Recommended: 16px form controls.** `styles.css:47-48` is currently:

```css
input, select { background: var(--panel2); border: 1px solid var(--line); color: var(--txt);
  padding: 6px 9px; border-radius: 6px; font: inherit; }
```

`font: inherit` pulls the `14px` from `body { font: 14px/1.5 … }` (styles.css:7). Add, inside the phone
media query (which must come *after* this rule — `font: inherit` is a shorthand that resets `font-size`,
so a later `font-size` at equal specificity wins on source order):

```css
@media (max-width: 640px) {
  input, select, textarea { font-size: 16px; }
}
```

Bump the **controls only**, not `body`. A 16px body would reflow every `th`/`td` in the eight table views
and blow up the very column-width problem the map is trying to solve. Note this also covers
`.nw-row input, .nw-row select` (styles.css:58) in `NetWorth.jsx` — which the map keeps
"desktop-optimised" but requires to *render without breaking*; a 114% zoom on every field focus is
breaking.

**Rejected: `maximum-scale=1` / `user-scalable=no`.** It works (proved by the source above) and it is a
one-line change, which is exactly why it's tempting. Reject it because MDN carries an explicit
accessibility warning on both keys: *"Setting `user-scalable=no` or restricting `maximum-scale` prevents
users with low vision from zooming and reading content"*, citing **WCAG 2.0 SC 1.4.4** and requiring
*"Minimum 2× scaling … Best practice: Allow 5× zoom"*
([MDN, meta name=viewport](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/meta/name/viewport)).
For a personal-finance dashboard rendering 11px table headers and 24px tile values, pinch-zoom is not a
theoretical affordance — it is how the numbers get read.

**Also rejected: the `font-size: 16px` + `transform: scale(0.875)` trick** to keep the visual size at 14px.
It is fragile (it depends on which font-size WebKit reports as `nodeFontSize`, an implementation detail
that is not contracted anywhere), it breaks caret and selection geometry, and the design work it protects
— 14px controls — is something ticket 015 (*Touch targets & type scale*) wants to abandon on phone anyway.
16px controls are the *goal*, not a workaround.

---

## 4. Virtual keyboard

### What the keyboard actually does

**Neither engine shrinks the layout viewport by default**, so *no* viewport unit — `vh`, `svh`, `lvh`, or
`dvh` — changes when the keyboard opens.

The spec anticipates this explicitly:

> "UAs may have some dynamically-shown interfaces that intentionally overlay content and do not cause
> any shifts in layout—and therefore **have no effect on any of the viewport-percentage lengths**.
> (Typically on-screen keyboards will fit into this category.)"
>
> — [CSS Values 4 §6.1.2](https://www.w3.org/TR/css-values-4/#viewport-relative-lengths)

MDN states the mechanism: *"User-interface features like the on-screen keyboard (OSK) can shrink the
**visual** viewport without affecting the **layout** viewport."*
([MDN, Visual Viewport API](https://developer.mozilla.org/en-US/docs/Web/API/Visual_Viewport_API))

Chrome aligned to this in **Chrome 108 on Android**, which previously resized both viewports:

> "Previously, showing the on-screen keyboard resized both the Layout Viewport and Visual Viewport. Now
> it resizes only the Visual Viewport … matching iOS Safari behavior."
>
> — [Chrome for Developers, *Prepare for viewport resize behavior changes*](https://developer.chrome.com/blog/viewport-resize-behavior)

**Consequence for `position: fixed`:** a fixed element is laid out against the **layout** viewport, which
did not shrink — so the keyboard simply covers it. Chrome's own table for the default `resizes-visual`
says: *"`position: fixed` elements maintain position … OSK can obscure fixed elements."* On iOS this is
worse than "obscured": WebKit has an open, actively-reported defect where `visualViewport.offsetTop`
fails to reset after the keyboard is dismissed, leaving fixed headers/footers permanently misaligned on
subsequent scrolls ([WebKit bug 265578](https://bugs.webkit.org/show_bug.cgi?id=265578); reproduced
repeatedly on the [Apple Developer Forums](https://developer.apple.com/forums/thread/800125)).

iOS *does* auto-scroll the focused control into the remaining space — that is the same
`_zoomToFocusRect:` routine from §3, which reserves
`const double minimumHeightToShowContentAboveKeyboard = 106;`
([`WKWebViewIOS.mm` L1712](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/API/ios/WKWebViewIOS.mm)).
So the *input* stays visible for free. It is only the surrounding fixed chrome that misbehaves.

### `interactive-widget` — real, but useless here

Chrome 108 introduced the `interactive-widget` meta viewport key with three values
([MDN](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/meta/name/viewport),
[Chrome](https://developer.chrome.com/blog/viewport-resize-behavior)):

| Value | Effect |
|---|---|
| `resizes-visual` (**default**) | Only the visual viewport shrinks. Viewport units and `position: fixed` unchanged; keyboard can obscure fixed elements. |
| `resizes-content` | Both viewports resize. *"Viewport-relative units shrink with keyboard"*; fixed elements shift. (Pre-108 Chrome Android behaviour.) |
| `overlays-content` | Neither viewport resizes; keyboard draws on top. |

**Support, verified today:**

- **Chrome/Edge 108+ on Android** — shipped. Chrome's doc is explicit that *"this extension only works
  in Chrome 108+ on Android, excluding iOS/iPadOS versions (which use WebKit)."*
- **Firefox 131** — [Bugzilla 1831649](https://bugzilla.mozilla.org/show_bug.cgi?id=1831649):
  **RESOLVED FIXED**, landed on the Firefox 131 branch.
- **Safari / WebKit — NOT IMPLEMENTED.** [WebKit bug 259770](https://bugs.webkit.org/show_bug.cgi?id=259770)
  ("Implement the interactive-widget property in the viewport meta tag") is still **status `NEW`, no
  resolution, no assignee**, last modified **2026-07-28** — two days ago. Filed August 2023; comments
  through June 2026 are still asking whether anyone is working on it.

**Verdict: do not add `interactive-widget`.** It would change behaviour on Android only, introducing a
platform divergence in the one place you least want one, and it would do nothing for the iPhone that the
map names as the real target.

### VirtualKeyboard API — also not available

`navigator.virtualKeyboard.overlaysContent`, the `geometrychange` event, and the `env(keyboard-inset-*)`
variables are genuinely the "right" primitives — but:

- **Chromium/Edge 94+** only ([Chrome for Developers, *Full control with the VirtualKeyboard API*](https://developer.chrome.com/docs/web-platform/virtual-keyboard)).
- **Safari: not implemented.** [WebKit bug 230225](https://bugs.webkit.org/show_bug.cgi?id=230225) is
  **status `NEW`**, open since September 2021, last activity **2026-04-15**.
- **Firefox: no support.** MDN classes the whole API as *limited availability, not Baseline, "does not
  work in some of the most widely-used browsers"*
  ([MDN, VirtualKeyboard API](https://developer.mozilla.org/en-US/docs/Web/API/VirtualKeyboard_API)).

`env(keyboard-inset-height)` returns `0px` in Safari and Firefox, so any layout built on it degrades to
"keyboard covers content" on exactly the target device.

### What to do instead

1. **Build the phone nav as a flex child, not `position: fixed`.** With `.app { height: 100svh;
   flex-direction: column }` at phone width and the nav as a normal flex item, the keyboard cannot
   displace it — the shell's height is a viewport unit the keyboard doesn't touch, and the nav has no
   viewport-relative positioning to be wrong about. This costs nothing and removes the entire class of
   bug in §4. It is the decisive reason to prefer a flex-child nav over a fixed one in ticket 012.
2. **Note how little keyboard surface this app actually has.** The map keeps `NetWorth.jsx` (the only
   real form) and `Classify.jsx` desktop-optimised. The sign-in screen (`auth.jsx`) has **no text
   input at all** — it renders a Google Identity Services button (`auth.jsx:41-43`), so the keyboard
   never opens there, and any Google account-picker keyboard is inside Google's own popup, not your
   viewport. Keyboard-vs-layout is therefore a near-empty problem in this codebase; don't over-engineer it.
3. **Only if a fixed bottom bar becomes unavoidable:** the sole cross-browser mechanism is the
   `VisualViewport` API — listen for `resize`/`scroll` and re-`transform` the bar, per MDN's
   "simulate `position: device-fixed`" recipe
   ([MDN, Visual Viewport API](https://developer.mozilla.org/en-US/docs/Web/API/Visual_Viewport_API)).
   That is JavaScript layout code in a repo with zero frontend tests. Treat it as a last resort.

---

## Sources

All fetched live 2026-07-30 unless noted.

**Specifications**
- [CSS Values and Units Level 4 §6.1.2 — viewport-relative lengths](https://www.w3.org/TR/css-values-4/#viewport-relative-lengths) — normative definitions of small/large/dynamic viewport, `v*` ≡ `lv*` mapping, and the on-screen-keyboard note.
- [CSS Environment Variables Level 1](https://drafts.csswg.org/css-env-1/) — `safe-area-inset-*` (dynamic) and `safe-area-max-inset-*` (static) definitions.
- [CSS Round Display Level 1 — `viewport-fit`](https://drafts.csswg.org/css-round-display-1/#viewport-fit-descriptor) — `auto`/`contain`/`cover` semantics. Editor's Draft, updated 2025-12-26.

**MDN**
- [`<length>`](https://developer.mozilla.org/en-US/docs/Web/CSS/length) — `sv*`/`lv*`/`dv*` guidance; the dynamic-unit instability/performance warning.
- [`env()`](https://developer.mozilla.org/en-US/docs/Web/CSS/env) — safe-area and keyboard-inset variables; Baseline widely available since January 2020.
- [`<meta name="viewport">`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/meta/name/viewport) — full content-value table; `viewport-fit`, `interactive-widget`; WCAG accessibility warning on `maximum-scale`/`user-scalable`.
- [Visual Viewport API](https://developer.mozilla.org/en-US/docs/Web/API/Visual_Viewport_API) — layout vs visual viewport; OSK shrinks visual only; `position: device-fixed` simulation recipe.
- [VirtualKeyboard API](https://developer.mozilla.org/en-US/docs/Web/API/VirtualKeyboard_API) — limited availability, not Baseline.
- [WebKit vendor-prefixed CSS extensions](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Webkit_extensions) — `-webkit-fill-available` is a back-compat alias for `stretch`.

**WebKit**
- [Designing Websites for iPhone X](https://webkit.org/blog/7929/designing-websites-for-iphone-x/) — `viewport-fit=cover`, `env()` safe areas, default auto-inset behaviour, the `max(12px, env(...))` idiom.
- [New WebKit Features in Safari 15.4](https://webkit.org/blog/12445/new-webkit-features-in-safari-15-4/) — `svh`/`lvh`/`dvh` shipped, and the mobile problem they solve.
- [News from WWDC26: WebKit in Safari 27 beta](https://webkit.org/blog/17967/news-from-wwdc26-webkit-in-safari-27-beta/) — `stretch` keyword; guidance to migrate off `-webkit-fill-available`.
- [Bug 259770 — Implement the `interactive-widget` property in the viewport meta tag](https://bugs.webkit.org/show_bug.cgi?id=259770) — **status `NEW`, unresolved, last modified 2026-07-28.**
- [Bug 230225 — Implement the VirtualKeyboard API](https://bugs.webkit.org/show_bug.cgi?id=230225) — **status `NEW`, unresolved, last activity 2026-04-15.**
- [Bug 265578 — Visual viewport height updated late when Safari UI is expanded](https://bugs.webkit.org/show_bug.cgi?id=265578) and [Apple Developer Forums thread 800125](https://developer.apple.com/forums/thread/800125) — fixed-element misalignment after keyboard dismissal.

**WebKit source** (repo `WebKit/WebKit`, branch `main`, fetched 2026-07-30)
- [`Source/WebKit/UIProcess/API/ios/WKWebViewIOS.mm`](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/API/ios/WKWebViewIOS.mm) — L1712 `minimumHeightToShowContentAboveKeyboard = 106`; L1756-1757 `webViewStandardFontSize = 16` and `clampTo(16 / fontSize, minimumScale, maximumScale)`.
- [`Source/WebKit/UIProcess/ios/WKContentViewInteraction.mm`](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/ios/WKContentViewInteraction.mm) — L~2977-2984, `_zoomToRevealFocusedElement` call site and its `allowScaling` / `maximumScale` gating.
- [`Source/WebCore/page/ViewportConfiguration.cpp`](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/page/ViewportConfiguration.cpp) — L355-365 `minimumScale()`, L400-407 `allowsUserScaling()` vs `allowsUserScalingIgnoringAlwaysScalable()`, L555 `allowsUserScaling` ← `userZoom`.

**Chrome for Developers / Chromium**
- [URL bar resizing](https://developer.chrome.com/blog/url-bar-resizing) — `vh` sized as if the URL bar is hidden; ICB sized as if shown; `position: fixed` resizes with the URL bar.
- [Prepare for viewport resize behavior changes coming to Chrome on Android](https://developer.chrome.com/blog/viewport-resize-behavior) — Chrome 108 OSK change; the `interactive-widget` value table; Android-only availability.
- [Chrome on Android edge-to-edge migration guide](https://developer.chrome.com/docs/css-ui/edge-to-edge) — Chrome 135 edge-to-edge, the "chin", `viewport-fit=cover` opt-in, `safe-area-max-inset-bottom` ≈ 36px, layout-thrashing guidance.
- [Full control with the VirtualKeyboard API](https://developer.chrome.com/docs/web-platform/virtual-keyboard) — Chromium 94+.

**Other**
- [Bugzilla 1831649 — Implement the `interactive-widget` meta viewport key](https://bugzilla.mozilla.org/show_bug.cgi?id=1831649) — **RESOLVED FIXED, Firefox 131.**
- [caniuse: viewport-unit-variants](https://caniuse.com/viewport-unit-variants) — 92.52% global; Chrome/Edge 108, Safari & iOS Safari 15.4, Firefox 101, Samsung Internet 21.
- [caniuse: css-env-function](https://caniuse.com/css-env-function) — 94.77% global; Safari 11.1 / iOS Safari 11.3, Chrome 69, Firefox 65, Edge 79.

**Repository primary sources**
- `web/index.html:5` — viewport meta tag, currently missing `viewport-fit=cover`.
- `web/src/styles.css:7` (`body { font: 14px/1.5 … }`), `:8` (`.app { height: 100vh }`), `:14` (`.main { overflow: auto }`), `:15-18` (`.fillpane`/`.grow`/`.scroll` nested-scroll machinery — the reason the document never scrolls), `:36-37` (`white-space: nowrap`, sticky `th`), `:47-48` (`input, select { … font: inherit }`), `:58` (`.nw-row input`).
- `web/src/auth.jsx:41-43` (Google Identity Services button — no text input on the sign-in screen), `:50` and `:125` (`minHeight: "100vh"`).
