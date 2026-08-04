---
id: 20
title: Scroll ownership on a phone
type: grilling
status: closed
assignee: nywleswoey
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

## Resolution

**Nobody was going to choose the scroll owner — 013's wrapper chooses it.** Adding `overflow-x: auto`
to a flex item of `.main` flips its `min-height: auto` to `0`, so it stops sizing to content, shrinks
to the pane, and **becomes the vertical scroll owner while `.main` stops scrolling**. That is a side
effect of pattern A, not a decision anyone made, and it is what this ticket had to ratify or reverse.

Measured in Chrome at 390×844 and 844×390 against the real `styles.css` inside 012's shell. Harness:
`scratchpad/scroll-owner.html`, `holdings-phone.html`, `card-nested.html` (throwaway, not committed).

The trade is binary — the two halves cannot both be had:

| wrapper | height | vertical owner | sticky `th` |
|---|---|---|---|
| default (`flex: 0 1 auto`) | shrinks to pane | **the wrapper** | **works** |
| `flex: none` | keeps content height | `.main` | **dead** |

### The five, decided

1. **The wrapper owns the vertical scroll — ratified, not reversed.** 013 chose pattern A over
   card-per-row on a **15 rows vs 3** measurement and banked on "sticky headers survive under A";
   both describe the shrinking wrapper, and re-measuring it here reproduces **exactly 15 rows**. So
   013's prototype already assumed this answer and `flex: none` would quietly retract a documented
   property of an accepted pattern. On a 13-column table scrolled sideways the header is what tells you
   *which number* you are looking at — the pin tells you which row, not which column. **This ticket's
   item 1 largely dissolves:** because the wrapper shrinks to fit, `.main` stops scrolling, so on
   Holdings there is exactly **one** scrollable region on screen, not two competing ones.
2. **Card-nested pattern-A tables get `max-height: 60svh`, phone-only.** The behaviour in (1) is free
   only for a **direct flex child of `.main`** — and only `Holdings.jsx:142` is one. The other three
   pattern-A tables live inside `.card`, an ordinary block, where the wrapper sizes to content
   (measured 1348px), never scrolls, and **the sticky header is dead**. A `max-height` restores it
   (measured 506px box, header stuck). Chosen as **one self-limiting rule rather than an exemption
   list**: `max-height` is a no-op when content is shorter, so it does nothing on Dividends and engages
   on Recurring when long. Rejected unconditional — turning a long Recurring list into a 60vh scroll box
   on a 1280px desktop is a visible design change to a view nobody complained about. Rejected hoisting
   the tables out of their cards — the card supplies the panel and heading; that is markup surgery to
   reach where one declaration reaches.
3. **No affordance added, and `overscroll-behavior` deliberately left unset.** Recorded as a decision
   rather than an omission, because the reflex on a nested scroll box is to reach for `contain` and here
   it is actively wrong: default chaining is what you want — flick the table, hit its end, the page
   keeps going. `contain` would trap the gesture inside a 60svh box. The cue needs no gradient either:
   `max-height` almost always clips the last row mid-height, and a half-row is the most reliable
   "more below" signal there is — which is why the value is a `max-height` and not a row count.
   **`-webkit-overflow-scrolling: touch` is obsolete** (default since iOS 13) — recorded so nobody adds it.
4. **`.fillpane`/`.grow`/`.scroll` neutralised under 640px** — `.main` scrolls as one page on Classify.
   The machinery encodes a desktop working posture (rules pinned above while you classify row after row);
   on a phone at 015's 44px pitch that posture buys ~7 funnel rows under ~5 rule rows across **three**
   competing scroll regions. 017 already settled that the editors only have to *not break*, and a single
   page scroll is precisely that — it deletes the deepest nesting in the app.
5. **Landscape accepted as a columns-for-rows trade; Holdings' footnote becomes a `<details>` on phone.**
   Rotating this dashboard is a deliberate act to see more **columns**, and it delivers — 844px wide shows
   8+ of Holdings' 13 columns against 2–3 in portrait. Rejected dropping the inner box in landscape only:
   it would give the phone two scroll models depending on which way it is held, and a header that appears
   and disappears on rotate is worse than a short table. The footnote was the real lever — measured at
   44px pitch:

   | | footnote full | collapsed |
   |---|---|---|
   | portrait 390×844 | 529px box → **11 rows** | 625px → **13 rows** |
   | landscape 844×390 | 161px box → **2 rows** | 221px → **4 rows** |

   **Correction (#50): every cell above is computed at a pitch neither orientation has.** 44px is a
   *floor*, not a pitch, and Holdings' pinned cell is two lines, so portrait's real data row is
   **60.5px**; landscape's is **52.5px**, because this block is `max-width`-scoped and 844 is not the
   phone tier, so a rotated phone kept the old 7px padding. Shipped (#49, at 390×844 and 844×390):
   **portrait 10**, against the 13 this table forecast for the collapsed state. **Landscape 4 — with
   the disclosure OPEN**, i.e. the *footnote-full* column, which forecast 2. `Holdings.jsx` reads its
   query by width, once, at mount, so landscape gets the `<details>` markup but not the phone's
   collapse; landscape therefore came out **better** than this table predicted for the state it is
   actually in, not "unchanged". **The finding is untouched** — the footnote is still the lever, and
   which cell you land in still turns on whether it is open. What is dead is the arithmetic, not the
   design. Nobody has measured collapsed landscape post-#47 and this correction does not claim to.

   Rejected moving the footnote *inside* the wrapper: a block child of an `overflow-x: auto` container
   sizes to the container, not the table, so the paragraph would sit at the far left and slide out of
   view as you scrolled right to read columns. `<details>` is real UI, which 018 forbade for the cheap
   tablet tier — that rule was scoped to that tier, and phone is where this map does its design work.

### Findings the ticket did not anticipate

- **The machinery has exactly one user in the whole app** — `Classify.jsx:104`, an *editor*, the very
  thing 017 ruled desktop-optimised. Item 2's "the answer may be only Transactions needs it" was close
  in spirit and wrong in fact: no read-only view uses it at all.
- **`Dividends.jsx:30` has a dead sticky header on desktop today.** It already carries
  `overflow-x: auto`, making it a scroll container that never scrolls. **Harmless, and provably so:**
  `CONTEXT.md:18` fixes funding buckets as a closed set of three — `cash`, `CPF`, `SRS` — so the crosstab
  is 3 rows plus a Total and can never scroll vertically. It grows in *columns* (years), which is exactly
  why 013 gave it h-scroll. Recorded, not fixed.
- **One inline-style trap, same family as 015's `Transactions.jsx:35`.** Classify's rules-list cap is
  inline at `Classify.jsx:126` (`maxHeight: 232, overflowY: "auto"`), which CSS cannot reach — so
  decision 4 neutralises the `.fillpane` machinery but **not** that box. **Accepted:** it stays a bounded
  232px scroller on phone, which behaves fine; removing it would need the app's second `matchMedia`
  consumer for an editor the map has already deprioritised.

### Handed to verification

Whether two nested scroll regions on **Recurring** actually feel confusing — it is the one view where
`.main` scrolls *and* two table boxes scroll inside it (three cards: the add form, Tracked, Detected).
The geometry is measurable; the feel is not. Real-device check at
[Verification checklist & target viewports](019-verification-checklist.md).
