---
id: 21
title: The phone content gutter
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [12]
parent: map-mobile-responsive
---

## Question

What is `.main`'s padding on a phone — and is it one number or two?

`.main { padding: 22px 28px }` (styles.css:14) is a desktop assumption the map's Notes never listed
alongside the others. **The map has been using 14px for three tickets without ever deciding it.**
[The phone navigation shell](012-phone-navigation-shell.md)'s prototype styled its content pane
`padding: 14px 14px 20px` with `padding-left/right: max(14px, env(safe-area-inset-left/right))`
(`web/prototypes/mobile-shell-prototype.html:44-46`), and
[Wide numeric tables on a phone](013-wide-tables-on-phone.md) and
[Charts on a phone](014-charts-on-phone.md) both measured inside that shell. So 14px is load-bearing
for every width in the spec, but exists only as a number inside a prototype.

This is worth deciding rather than inheriting, because the gutter is the **cheapest horizontal
width in the app** — every px returned to content is returned to all 13 views at once, and several
decisions are sitting close to their limits on it:

- [The "doesn't break" floor for Classify & Net Worth](017-editors-dont-break-floor.md) computes
  `.nw-row`'s label column at **124px** and its currency `<select>` at **~70px exactly** — both move
  1:1 with the gutter.
- 013's measured **15 rows / 1302px** table width and 014's full-width bar tracks were all taken at 14px.

Decide:

1. **The number.** Ratify 14px, or pick another. Note it is charged twice — `.main`'s padding *plus*
   `.card`'s own `padding: 16px` (styles.css:33), so a card's content sits 30px in from each edge
   today. Decide whether `.card` shrinks on phone too, or whether the gutter carries the change alone.
2. **Vertical vs horizontal.** The prototype used `14px 14px 20px` — a larger bottom pad. Confirm or
   flatten.
3. **Safe-area interaction.** [Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md)
   requires `padding-left/right: max(<pad>, env(safe-area-inset-left/right))` for landscape, which the
   prototype already does. Confirm that this lands on `.main` and not somewhere else, given 012 put
   **nothing** in `position: fixed`.
4. **Does it apply at the tablet tier?** Or does `.main` keep `22px 28px` above 640px —
   [The tablet tier](018-tablet-tier.md) owns the threshold question but this is the value it would
   switch between.
5. **Whether full-bleed is ever wanted.** A table under 013's pattern A scrolls horizontally inside its
   container; a gutter around it means the scroll never reaches the screen edge. Decide whether
   scrolled tables break out of the gutter or stay inside it.

Answer should be a short table of literal values a build session can apply, plus the one-line
rationale for each — the same shape as
[Touch targets & type scale](015-touch-targets-type-scale.md).

## Resolution

**14px ratified — but the ticket's reason for asking was wrong, and the real finding is elsewhere.**
The gutter is **not load-bearing anywhere between 8px and 16px**. Nothing in the spec has a threshold
in that range; the first one is at 20px. What the investigation did turn up is a **live defect in 012**:
the app bar has no `env()` guard, so `☰` sits under the notch in landscape.

Measured at a true 390px frame. Harness: `scratchpad/gutter2.html` (throwaway, not committed).

| gutter | content | card inner | `.nw-row` label | Holdings cols | full-bleed cols |
|---|---|---|---|---|---|
| 8 | 374 | 340 | 168 (136 in card) | 3 | 3 |
| 12 | 366 | 332 | 160 (128) | 3 | 3 |
| **14** | 362 | 328 | 156 (**124**) | 3 | 3 |
| 16 | 358 | 324 | 152 (120) | 3 | 3 |
| 20 | 350 | 316 | 144 (112) | **2** | 3 |

### The values

```css
.main {                                    /* ≥640px — unchanged from today */
  padding: 22px 28px;
  padding-left:   max(28px, env(safe-area-inset-left));
  padding-right:  max(28px, env(safe-area-inset-right));
  padding-bottom: max(22px, env(safe-area-inset-bottom));
}
@media (max-width: 639.98px) {
  .main {
    padding: 14px;
    padding-left:   max(14px, env(safe-area-inset-left));
    padding-right:  max(14px, env(safe-area-inset-right));
    padding-bottom: max(20px, env(safe-area-inset-bottom));
  }
}
.appbar {                                  /* phone shell, incl. 018's height guard */
  padding: 0 12px;
  padding-left:  max(12px, env(safe-area-inset-left));
  padding-right: max(12px, env(safe-area-inset-right));
}
```

Longhands **must follow** the shorthand — the shorthand resets all four sides.

| value | why |
|---|---|
| **gutter 14px** | Already written into a closed decision: [018](018-tablet-tier.md) hoisted `max(14px, env(...))` to unconditional as a defect fix. Ratifying costs nothing; 12px means amending 018 to buy 4px that measurement says changes nothing. |
| **`.card` 16px, unchanged** | Card content does sit 30px from the screen edge (15% of a 390px phone), but dropping the card to 12px buys **10px** and nothing has a threshold there. 017 already measured `.nw-row`'s label at 124px, accepted it, and ruled `.nw-row` "changes not at all". |
| **bottom `max(20px, env(...bottom))`** | Under `100svh` the pane's bottom edge *is* the screen's, so the last row of a scrolled list sits under the home indicator. Resolves to **34px** on an iPhone, to the 20px literal elsewhere. Gives the bottom the same `max(<literal>, env())` shape as left/right — one idiom on all four sides. |
| **no full-bleed** | Buys **zero** columns at every gutter we'd use. A plain `margin-inline: -14px` also *breaks* in landscape (padding becomes the 44px inset, margin stays −14, table lands at an arbitrary 30px); correctness needs `calc(-1 * max(14px, env(...)))` per side. And under [020](020-scroll-ownership-on-phone.md) it would put the pinned identity column **8px** from the screen edge instead of 22px. |
| **app bar `max(12px, env(...))`** | New — see below. |
| **value follows width, guard is unconditional** | `.main` keeps `22px 28px` at ≥640px inside the same `max(..., env(...))`, which resolves to the 44px inset on a landscape tablet. Consistent with 018's split: the shell follows *height*, horizontal decisions follow *width*, and the gutter is horizontal. |

### The defect this ticket actually found

**012 specifies `env()` guards for the drawer and the content pane, but not for the app bar** — its
prototype styles the bar `padding: 0 12px` (`mobile-shell-prototype.html:48`). In landscape the inset
is ~44px, which puts `☰` **under the notch**. This is live rather than hypothetical, because
[018](018-tablet-tier.md) made landscape a *supported* orientation by putting the shell behind
`(max-height: 500px)`. The app bar is the one piece of chrome that must be hittable.

Rejected putting the guard once on `.app` and letting children inherit: it insets the bar's
**background** as well as its contents, leaving an unpainted strip beside the panel colour under the
notch — [010](010-mobile-viewport-safe-area-research.md) wanted `viewport-fit=cover` precisely so the
dark background paints edge to edge, and [016](016-sign-in-on-phone.md) already banked on that as
"a passive win".

### Corrections

- **The three prototypes never agreed on the gutter**, so the ticket's premise — that 013 and 014 both
  measured inside 012's shell at 14px — is wrong: 012's shell used `14px 14px 20px`
  (`mobile-shell-prototype.html:44`), **013's tables prototype used a flat `12px`**
  (`mobile-tables-prototype.html:52`), and 014's charts used `14px 14px 40px`
  (`mobile-charts-prototype.html:77`). Harmless, exactly because of the headline: nothing in 8–16px
  moves. 014's 40px bottom existed to clear its own floating variant-switcher, not for the app.
- **"Several decisions are sitting close to their limits on it" is false.** Holdings shows the same 3
  columns from 8px to 16px, and **`.nw-row`'s currency `<select>` is gutter-immune** — it holds at
  exactly 70px throughout, because `1fr 120px 70px` makes it a fixed track and only the `1fr` label
  absorbs the change. The ticket's "~70px exactly" worry doesn't move with the gutter at all.
- **017's 124px reproduces exactly, and explains itself**: 156px at the 14px gutter, minus the card's
  own 16px × 2. That confirms item 1's suspicion that the gutter is charged twice — the label column is
  the one place in the app where it visibly is.
