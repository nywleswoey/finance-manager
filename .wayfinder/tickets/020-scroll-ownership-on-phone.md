---
id: 20
title: Scroll ownership on a phone
type: grilling
status: open
assignee:
blocked_by: [13]
parent: map-mobile-responsive
---

## Question

On a phone, does a section still own its own vertical scroll — or does the whole pane scroll as one?

`styles.css:15-18` defines a three-class machinery that lets a view fill the main pane so an inner
section can scroll independently:

```css
.fillpane            { flex:1 1 auto; min-height:0; display:flex; flex-direction:column; }
.fillpane > .grow    { flex:1 1 auto; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
.fillpane > .grow > .scroll { flex:1 1 auto; min-height:0; overflow:auto; }
```

It pairs with `th { position: sticky; top: 0 }` (:37) so a long table keeps its header visible while
its own box scrolls inside a `100vh` shell that never scrolls.

[The phone navigation shell](012-phone-navigation-shell.md) settled the frame this sits in: the shell
stays `100svh`, `.main` stays `flex:1; overflow:auto`, and the only chrome above it is a 48px app bar.
So the machinery is not *structurally* broken by the shell change. The open question is whether it is
still the right behaviour at 390px, where the scrollable box is a few hundred px tall:

1. **Does an inner scroll box survive at phone height at all**, or does a ~400px viewport into a
   table make the sticky header a bigger win than the scroll trap it creates? Nested scroll on touch
   has no visible scrollbar to signal that the inner box, not the page, is what moved.
2. **Which is it — per view, or one rule for all?** Find which views actually use `.fillpane`
   (grep `fillpane` under `web/src/modules/`) before deciding; the answer may be "only Transactions
   needs it".
3. **What happens to the sticky `th`** if the machinery is dropped on phone — does the header stick
   to the top of `.main` instead, and is that acceptable under the app bar?
4. **Does the answer change per orientation?** Landscape on a phone is ~390px tall total; an inner
   scroll box there is a slit.

Blocked by [Wide numeric tables on a phone](013-wide-tables-on-phone.md) — if that ticket replaces
tables with cards or a horizontally-scrolling wrapper, the sticky-header premise this machinery
exists to serve may not survive, and this question answers itself.

**Widened by [The tablet tier](018-tablet-tier.md)**, in two ways the title no longer covers:

- Pattern A now applies up to **1024px**, not just below 640, and it scopes *horizontal* scroll to the
  table — taking it away from `.main`, which owns it today at every width (measured: `Holdings.jsx:142`
  is 1272px against 1024px of content even at a 1280px viewport). So "who owns the scroll" is now a
  question with a horizontal axis and a two-tier answer, not a phone-only vertical one.
- Item 4 is **half-answered**: 018 put 012's shell rules behind `(max-height: 500px)` as well as
  `(max-width: 639.98px)`, so a rotated phone gets the phone shell and its 48px app bar. What that
  leaves open is only whether the *inner scroll box* survives at ~340px of remaining height.
