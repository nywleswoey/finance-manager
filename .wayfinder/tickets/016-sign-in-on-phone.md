---
id: 16
title: Sign-in on a phone
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [10]
parent: map-mobile-responsive
---

## Question

What has to change on the first screen a phone ever sees?

`auth.jsx:49-60` renders `LoginScreen` with all-inline styles, and it is **already close**:
`minHeight: 100vh; display: grid; placeItems: center` centres a 📊 emoji, an `<h1>`, "Sign in to
continue", and a `<div ref={btn}>` that **Google Identity Services renders its own button into**.
`auth.jsx:125` renders the same `minHeight: 100vh` shell while auth is resolving. So this is a
small ticket — but it gates everything, so it gets decided rather than assumed.

Decide:

1. **`minHeight: 100vh`** (`auth.jsx:50` and `:125`) — apply the replacement chosen in
   [Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md), or
   argue that `min-height` (unlike the shell's `height: 100vh`) is already safe here.
2. **The Google button.** GSI renders the button itself and takes `width` / `size` / `shape` config
   we do not currently pass. Decide whether it needs a phone-specific width (full-bleed vs its
   default), and whether **One Tap** behaves differently on mobile in a way that matters.
3. **Inline styles vs the stylesheet.** This screen is styled entirely inline with its own colour
   literals (`#0f1115`, `#e6e6e6`, `#8a8f98`) that **don't match** the `--bg`/`--txt`/`--mut`
   custom properties in `styles.css:1-4`. Decide whether making it responsive is the moment to move
   it into the stylesheet, or whether that is a separate cleanup this map shouldn't drag in.
4. **The error paragraph** at `auth.jsx:57` has a hard `maxWidth: 280` — confirm or change.
5. **Safe area.** Whether a centred, non-scrolling screen needs inset handling at all.

## Resolution

**The screen is already responsive. It is only mis-sized vertically.** Nothing overflows at any phone
width, so there is no reflow work here and no phone media query. The entire diff is **two characters on
two lines** — `100vh` → `100svh` at `auth.jsx:50` and `auth.jsx:125`, exactly as
[Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md) prescribed.
Everything else the ticket asked about is confirmed unchanged, and the reasons are recorded below so a
build session doesn't "improve" any of it.

### The diff

| File:line | Change |
|---|---|
| `auth.jsx:50` | `minHeight: "100vh"` → `minHeight: "100svh"` |
| `auth.jsx:125` | `minHeight: "100vh"` → `minHeight: "100svh"` |

### Confirmed unchanged

| Thing | Decision | Why |
|---|---|---|
| Layout / reflow | **nothing** | inner div is shrink-to-fit and centred; widest child is the GSI button at ~200px. Nothing approaches 320px. |
| GSI `renderButton` config | **nothing** — no `width`, `theme/size/text/shape` as-is | see *The 44px carve-out*. |
| Inline styles → stylesheet | **stays inline** | see *Why the cleanup is ruled out*. |
| The four colour literals | **stay wrong** | same, and see the map's Out of scope. |
| `maxWidth: 280` (`:57`) | **unchanged** | all four error strings are fixed and bounded; longest ≈240px unwrapped at 13px, so the cap is **essentially never binding**. When it is, 280px inside a 320px iPhone SE still leaves 20px gutters. |
| `env(safe-area-inset-*)` | **none, anywhere on this screen** | see *Safe area*. |
| Phone media query | **none** | this screen contributes nothing to 015's `@media (max-width: 639.98px)` block. |

### Why `min-height` still needs the fix

`min-height: 100vh` does **not** create the unreachable strip that `height: 100vh` creates in the shell —
it creates a **scrollable** one. `100vh` ≡ `100lvh`, so the box is ~844px inside a ~780px visible area: the
page gains ~64px of pointless scroll and the "centred" content sits ~32px **below** optical centre. With
`100svh` the box is exactly the visible height, the page doesn't scroll, the toolbar can't retract, and the
content centres where it looks centred.

### The 44px carve-out

[Touch targets & type scale on a phone](015-touch-targets-type-scale.md) set a 44px square floor for
everything tappable in a fully-responsive view, and sign-in is fully in scope. **The GSI button is exempt,
explicitly** — Google's reference documents no height for `large`/`medium`/`small` and exposes only `width`
(max 400px). The floor is unsatisfiable by our own mechanism.

It is also unnecessary here. 015 justified 44px on a specific shape — *adjacent* bare `✕` glyphs in a table
cell, "the exact case the number exists for." This screen has **one** tappable target with ~390px of empty
space around it; mis-tap risk is nil, and whatever `large` measures it clears **WCAG 2.5.8's 24px** minimum
regardless (44px was 015's own standard, not a conformance requirement). The two rejected alternatives:
passing `width` caps at 400px — not full-bleed on a 390px screen anyway — and a *responsive* width would
mean renting 014's `matchMedia` hook to size one button; `transform: scale()` blurs the vendor logo and
violates Google's brand chrome.

**This decision is robust to a fact nobody has measured**: whether `large` renders at 40px or 44px. We
can't change it either way, so the number only affects whether the carve-out is *needed*, never what we do.

### Why the cleanup is ruled out

The structural argument for moving this screen into `styles.css` is that **inline styles cannot hold a
media query**, and 015 chose "literal values in one `@media (max-width: 639.98px)` block" as the mechanism.
That argument is **void** — this screen needs no phone-specific rule, so the mechanism never has to reach
it.

Two facts kill the remaining argument, the colour drift:

1. **`styles.css` is imported globally at `main.jsx:7`, before `AuthGate` renders.** `var(--bg)` and friends
   are *already* in scope inside `auth.jsx`. Fixing the drift never required moving the file — the ticket
   bundled two separable questions, and they get different answers.
2. **`auth.jsx` is not an outlier.** Inline hex literals that bypass the tokens are the **house style**:
   ~30 instances across 9 files — `charts.jsx:7`, `Recurring.jsx:6-10`, `Classify.jsx:25-28,350`, every
   Recharts `contentStyle`, `NetWorth.jsx:98-105`. `Classify.jsx:415` even shows the halfway form,
   `var(--panel, #161b22)`. Retokenising auth's four literals fixes 4 of ~30 and makes `auth.jsx` the one
   file following a convention nothing else does.

### Safe area

**Nothing on this screen is edge-anchored** — content is ≤280px, centred, in a ≥320px viewport. Portrait
insets are irrelevant. In landscape the notch eats ~50px of an 844px width while the content sits ~280px
wide dead centre and never reaches it. Zero `env()` padding.

`viewport-fit=cover`, which 010 adds globally at `index.html:5`, is a **passive win** here rather than a new
obligation: the layout viewport extends under the home bar, so the dark background paints into it instead of
leaving a light strip. Nothing to compensate for.

### Two things the build session must be told, not left to find

1. **The `svh` fallback cannot be expressed inline.** React style objects have unique keys, so the two-line
   `height: 100vh; height: 100svh;` pair that 010 prescribes for `styles.css:8` has **no inline equivalent**.
   `minHeight: "100svh"` is all-or-nothing: a browser without `svh` drops the invalid value, `min-height`
   falls back to `auto`, and the box collapses to content height. This is the one capability a stylesheet has
   that inline genuinely lacks — surfaced and **accepted**, on two counts. `svh` is Safari 15.4+ /
   Chrome 108+ / Firefox 101+, universally available since 2022; and the degradation is near-invisible,
   because the uncovered area falls back to body's `--bg` `#0f1419` against the div's `#0f1115` — a
   four-unit difference in one channel. **The colour drift this ticket declined to fix is what makes the
   failure mode benign.**
2. **One Tap is not in use and this ticket does not introduce it.** `prompt()` appears nowhere in `web/src`
   — `auth.jsx:37,41` call only `initialize` + `renderButton`, and `auto_select` is left default-false. Any
   mobile One Tap behaviour is therefore out of the question's reach.

### Handed to [Verification checklist & target viewports](019-verification-checklist.md)

Observations, not gates — neither can change the diff above:

- **Measure the rendered GSI button height** at `size: "large"`, and record it. If it is ≥44px the carve-out
  is moot; if it is 40px the carve-out is load-bearing and should stay written down.
- **Confirm no seam under `viewport-fit=cover`** — that `#0f1115` paints under the home bar and no `--bg`
  strip appears at the bottom in either orientation.
