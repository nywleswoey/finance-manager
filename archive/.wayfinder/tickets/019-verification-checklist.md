---
id: 19
title: Verification checklist & target viewports
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [12, 13, 14, 15, 16, 17, 18, 21]
parent: map-mobile-responsive
---

## Question

What is the checklist that says the work is done — and what are the exact viewports it is run at?

The map locks verification as **manual, in a real browser, no automated tests** (the repo has 17
pytest files and zero JS test infrastructure; automated viewport/visual-regression testing is Out of
scope). So the checklist *is* the definition of done, and it is the last artifact of the spec.

This is the final ticket: it assembles the decisions from every other ticket into something a build
session can self-check against.

Decide:

1. **The viewport list.** Which concrete sizes get checked — a small phone (~360×640), a modern
   phone (~390×844), a large phone (~430×932), a tablet (~768×1024), desktop — and whether real
   devices are required or Chrome device emulation suffices.
2. **The universal criteria** applied to every one of the 13 views + sign-in: no horizontal page
   scroll, no clipped or overlapping content, no text below the type floor from
   [Touch targets & type scale](015-touch-targets-type-scale.md), no unreachable control, nav
   reachable from every screen.
3. **The per-view criteria** — what specifically to look at in each view, drawn from whatever
   [Wide numeric tables on a phone](013-wide-tables-on-phone.md),
   [Charts on a phone](014-charts-on-phone.md) and
   [The "doesn't break" floor](017-editors-dont-break-floor.md) decided. Includes the two editors'
   floor criteria as their own reduced list.
4. **Where the checklist lives** — a doc in the repo (alongside `DIVIDENDS.md`, `BACKEND.md`), a
   section of the handed-off spec, or a `.wayfinder/` artifact.
5. **Regression posture.** With no automated tests, what stops the next UI change from silently
   undoing this? Decide whether the answer is "nothing, accepted", a note in `CLAUDE.md`, or a
   re-run trigger — and if the honest answer is that it needs automation, say so and note it as a
   follow-on effort rather than pulling it in scope.

Resolving this closes the map: the spec is then ready to hand to a build session or `/prd-to-issues`.

## Resolution

**The checklist is [`RESPONSIVE.md`](../../RESPONSIVE.md) at the repo root.** It is the definition of
done, and the one artifact of this map with a job *after* the build session.

**Assembling it found what it was built to find: four tables have no pattern assignment in any ticket.**
013 inventoried 13 and 017 found 5 more in the editors; `grep -rn "<table" web/src/modules` returns
**22**. Two of the four are 9 columns wide and sit in fully-responsive views — including
`Performance.jsx:18`, an entire Portfolio tab no ticket has examined. Graduated as
[The four tables no ticket ever assigned](022-unassigned-tables.md); listed under **Open calls** in the
checklist meanwhile. **So this ticket does not close the map** — one decision remains.

### The four, decided

1. **Nine viewports, not five.** Three additions each earn their place from a decision that exists
   nowhere else: the **639/640 pair** (every phone rule is `max-width: 639.98px`, so checking one side
   proves half a rule, and 640 is the tablet tier at its worst — 384px of content behind the 200px rail);
   **844×390**, the only viewport that exercises 018's `(max-height: 500px)` shell guard; and
   **1100×900**, the 1024–1120 band where the wrapped tab strip and single-column `.grid2` are
   *deliberate*. A 360/390/430/768/1280 sweep never sees a tier boundary or the one range where the spec
   knowingly ships a compromise — which is exactly the range a reviewer would otherwise file as a bug.
   **Emulation suffices except for four items** that need a real iPhone: iOS focus-zoom (emulation
   doesn't reproduce Safari's zoom), `env(safe-area-inset-*)` (desktop Chrome reports **0** — 012's
   prototype had to fake it, which is direct evidence the sweep can't check it), Recurring's nested-scroll
   feel, and 44px comfort.
2. **Three classes, not one list: Gates / Observations / Open calls.** The spec produced three genuinely
   different kinds of checkable thing and 016 had already drawn the line itself — "Observations, not
   gates — neither can change the diff above" — while 013 left two assignments to "sanity-check rather
   than trust", where failing *changes a decision* rather than reporting a bug. Folding an unfailable
   item into a pass/fail list is how checklists stop being trusted. **The editors get 017's four criteria
   quoted positively**, not exemptions from the universal list — an exemption list drifts the moment the
   universal list changes, and 017 was explicit that reading comfort, row density and tap ergonomics
   beyond 24px are below the floor *by choice*.
3. **`RESPONSIVE.md` at the repo root, checklist only** — matching the `DIVIDENDS.md` / `BACKEND.md`
   house style. Rejected `.wayfinder/`: it buries a living document among closed tickets. **Rejected
   consolidating the spec into it**, tempting as that is for handoff: the map's governing rule is that a
   decision lives in exactly one place, and several resolutions layer corrections on earlier ones (018
   corrected 013's inventory, 020 corrected 012's safe-area placement, 021 corrected all three
   prototypes). Those corrections are coherent read in order and would read as contradictions flattened
   into one file. Accepted cost: a build session reads the map as an index and zooms on demand.
4. **Regression: a short `web/CLAUDE.md` pointing at the checklist, with a proportionate trigger.**
   Directory-scoped so it loads only when an agent is working in `web/` — where a note in the root
   `CLAUDE.md` would sit inside a workflow document with nothing to do with the frontend and be read
   every session regardless. The trigger must be cheap enough to actually run or it is "nothing,
   accepted" with extra words: **any change under `web/src` re-runs the universal gates at 390×844 for
   the touched views only**; the full sweep is reserved for `styles.css` or the shell. **`web/CLAUDE.md`
   is created by the build session, not now** — pointing at a definition of done for unbuilt work would
   mislead any agent that read it today.

### Two universal criteria the ticket proposed are already dead

Item 2 listed five. Two of them cannot be checked as written:

- **"No horizontal page scroll."** 017 proved this unbuildable *as a criterion*: `.main { overflow: auto }`
  absorbs every overflow before it reaches the page, so **it can never fail**. Replaced by 017's
  criterion 1 verbatim — `.main` must never scroll horizontally; sideways scroll is confined to a
  container that is visibly a table.
- **"No text below the type floor from 015."** 015 decided "**11px holds, no floor**". The floor this
  cites does not exist. Replaced by what 015 *did* decide and is checkable: every `input`/`select`/
  `textarea` renders at 16px on phone, and nothing else changes size.

The other three stand, and the checklist adds two the ticket didn't list: nothing is `position: fixed`,
and safe areas clear the notch **including the app bar** — 021's find.

### Recorded honestly, inside the checklist

A manual checklist decays, nothing in it can fail a build, and the real fix is the automated
viewport/visual-regression effort the map already parked as its own map. That sentence is in
`RESPONSIVE.md` itself, so nobody mistakes "the checklist exists" for "this is protected".
