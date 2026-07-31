---
id: 17
title: The "doesn't break" floor for Classify & Net Worth
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [13]
parent: map-mobile-responsive
---

## Question

The map locks these two editors as **desktop tasks that must still render without breaking** on a
phone. What exactly does "doesn't break" mean, concretely enough to build and verify?

**`spending/Classify.jsx` (417 lines)** — the rules dashboard from the spend-classification map
(see [The /classify screen UX](007-classify-screen-ux.md)). It carries: a priority-ordered rule
list with **HTML5 drag-to-reorder** (does nothing on touch — no error, just an inert control), an
unclassified-spend pool with inline manual-classify, a "Propose a rule" → NL → parse & preview →
confirm **modal**, and provenance pills.

**`networth/NetWorth.jsx` (292 lines)** — the snapshot form. `.nw-formhead` is a flex row of
labelled inputs (styles.css:52-53) and every line item is
`.nw-row { grid-template-columns: 1fr 120px 70px }` (:56) — label, right-aligned value input,
delete. At 390px the fixed 120px + 70px leave ~200px for a label, and the whole form is dozens of
rows deep. It also renders a **`LineChart`** at `:96` — the app's only time-series — whose phone
treatment belongs to [Charts on a phone](014-charts-on-phone.md), not to this floor.

Decide:

1. **The floor itself.** Candidate criteria: no horizontal *page* scroll, no overlapping or clipped
   controls, every control reachable and readable, no dead-end state. Ratify or amend that list —
   it becomes the acceptance criteria for these two views.
2. **The inert drag handle.** A control that silently does nothing on touch is worse than one that
   is visibly unavailable. Decide: hide the handle on phone, show it disabled with an explanation,
   or leave it inert. (Building touch drag is **out of scope** — map's Out of scope.)
3. **The Classify modal.** Modals are the most common phone-layout failure. Decide whether it gets
   real phone treatment (full-screen sheet) or is covered by the floor — noting the NL-input flow
   involves a text field and therefore the virtual keyboard.
4. **`.nw-row`'s fixed 120px/70px columns.** The cheapest change that satisfies the floor — collapse
   to a stacked two-line row, shrink the fixed columns, or let the form scroll horizontally in its
   own container.
5. **Is "don't break" enough for the unclassified pool?** It is a *table*, so it may inherit the
   pattern from [Wide numeric tables on a phone](013-wide-tables-on-phone.md) for free. Decide
   whether it rides along with the read-only tables or stays behind the floor.

## Resolution

**The floor is four criteria, and both editors are within a handful of lines of clearing them.** The
surprise is how little is broken: Classify's tables are *already* contained, `.nw-row` needs no change at
all, and the single largest item — the inert drag surface — turns out to be **one button**, not a control
per row. Total: **two CSS rules on phone, one unconditional CSS fix, two `vh`→`svh` literals, two markup
wrappers, and one `float` to unpick.**

### The floor

1. **Sideways scrolling is confined to a container that is visibly a table. `.main` must never scroll
   horizontally.** The ticket's "no horizontal *page* scroll" is unbuildable as written — `.main
   { overflow: auto }` (styles.css:14) absorbs every overflow before it reaches the page, so the criterion
   can never fail. What matters is *which box* scrolls: a table in its own scroll container is fine;
   `.main` scrolling sideways is not, because it drags the tiles, card borders and headings with it.
2. **No overlapping or clipped controls.**
3. **Every control reachable, readable, and tappable** — tappable meaning 015's unconditional 24px square
   floor for the editors.
4. **No control that silently does nothing, and no state you can't get out of.** Note `title=` tooltips
   **do not exist on touch**, so any explanation must be visible text.

Explicitly *below* the floor: reading comfort, row density, tap ergonomics beyond 24px, and anything
resembling an information-design change. That is the line between the floor and the treatment the
read-only views get.

### The diff

**Unconditional — every width**

| Where | Change | Why |
|---|---|---|
| `styles.css:47` | add `textarea` to the `input, select` rule | `textarea` appears **once** in `web/src` and is styled **nowhere** — it renders UA-default, i.e. a **white box on a dark modal**, at every width. Same shape as `.nw-del` in 015: a live defect, visually free, removes a conditional. |
| `Classify.jsx:412` `overlay` | `padding: "6vh 16px"` → `6svh` | 010, applied. |
| `Classify.jsx:416` `sheet` | `maxHeight: "84vh"` → `"84svh"` | 010, applied. |
| `NetWorth.jsx:223` Breakdown | wrap the `<table>` in `overflow-x: auto` | criterion 1. |
| `NetWorth.jsx:267` History | wrap the `<table>` in `overflow-x: auto` | criterion 1. |
| `Classify.jsx:116` | replace the inline `float: right` | criterion 2 — see *The float*. |

**`@media (max-width: 639.98px)`**

| Where | Change |
|---|---|
| `Classify.jsx:119` ⇅ Reorder | **hidden** |
| `.nw-formhead` (styles.css:52) | `flex-wrap: wrap` |

### 1. The drag surface is one button

**The ticket's premise is wrong.** The rules table (`:127-148`) has **no drag at all**. Drag lives in a
separate `ReorderModal` (`:205`), reachable only by pressing **⇅ Reorder** (`:119`). There is no per-row
handle to hide.

**⇅ Reorder is hidden under 640px.** Leaving it inert opens a modal whose only interaction is HTML5 drag
and whose only exit is Cancel — the dead-end criterion 4 forbids. Disabling it costs two additions rather
than one: `.link-btn` (styles.css:42) has **no `:disabled` rule**, and its explicit `color: var(--mut)`
overrides the UA's disabled greying, so a disabled ⇅ Reorder looks *identical* to an enabled one — and the
explanation can't live in `title=`, which touch doesn't render. Priority stays **visible** (the rules table
keeps its Priority column); it simply isn't reorderable on a phone, which is what the map already decided
when it ruled touch drag-reorder out as "a sit-down desktop task".

> **`.link-btn` has no `:disabled` style — a live defect on desktop too.** `disabled={rules.length < 2}`
> (`:119`) and `disabled={(pick[r.id] ?? "") === ""}` (`:179`) are both **invisible today**. Not fixed here
> (it is not a floor violation once ⇅ Reorder is hidden), but recorded.

**Consequence: `ReorderModal` becomes unreachable on a phone**, so its layout needs no floor treatment at
all. Only `RuleModal` remains in scope — the ticket's "the Classify modal" was two modals, and hiding one
button halved the surface.

### 2. `RuleModal` gets the floor, not a sheet

**The sheet is already responsive horizontally** — `width: min(720px, 100%)` (`:416`) resolves to 358px at
390px by construction. Both problems are vertical:

- **`6vh` + `84vh`.** Per 010, `vh` ≡ `lvh` ≈ 844 against a visible ~745, putting the sheet's bottom edge
  at ~760px — below the fold — with `position: fixed` preventing any scroll to reach it. Cancel (`:385`)
  lives there. Not fatal (backdrop-tap at `:332` still dismisses) but exactly what 010 predicted. `svh`
  fixes it, and is an existing decision rather than a new one.
- **`position: fixed` + focused `<textarea>`.** Degrades acceptably: the textarea sits at the *top* of the
  sheet (`:335`) with Parse directly beneath (`:343`), so iOS scrolls precisely the two controls you need
  into view.

**No full-screen sheet.** It buys polish, not floor compliance, on a modal the map classifies as
desktop-optimised.

### 3. `.nw-row` changes not at all

The ticket estimated "~200px for a label". At the **14px phone pane padding** (see *The gutter*) the real
figure is **124px**: 390 − 28 = 362, minus `.card`'s 32 = 330px of row, minus 206 for the fixed columns and
gaps.

| Column | At 015's 16px inputs | Verdict |
|---|---|---|
| label `1fr` = 124px | ~18 chars at 13px; long labels wrap | wrapping isn't clipping — clears criterion 2 |
| value `120px` | ~100px of text box; `1234567.89` at 16px ≈ 85px | comfortable — **the column you'd instinctively shrink is the one that can least afford it** |
| currency `70px` | "SGD" ~34 + 18 padding + 2 border + native arrow ~16 ≈ **70px exactly** | the only criterion-2 risk on the row |

Both alternatives were rejected on their costs. **Stacking** turns 17 rows across 4 groups into ~34 lines —
against 015's already-lengthened pitch — and destroys the right-aligned value column you scan down while
filling the form. **Horizontal scroll** violates criterion 1: a form is not a table.

`.nw-formhead` gets `flex-wrap: wrap` on phone as a one-property hedge — Date + Note at 16px is ~344px
against 330px available, and `input type="date"` has a platform- and locale-dependent intrinsic width,
which is not a thing to bet a floor on.

### 4. The editors' tables get containment, not a pattern

**Five tables, not one — and none of them are in 013's inventory**, which covered the 13 tables in the 8
read-only views.

| Table | Cols | Container today | Action |
|---|---|---|---|
| `Classify.jsx:127` rules | 6 | `overflowY: "auto"` → **`overflow-x` computes to `auto`** | none |
| `Classify.jsx:158` unclassified | 5 | inside `.scroll` | none |
| `Classify.jsx:398` MatchTable | 3 | inside `sheet`'s `overflow: auto` | none — 013's ≤4-column bucket |
| `NetWorth.jsx:223` Breakdown | 6 | bare `.card`, no overflow | **wrap** |
| `NetWorth.jsx:267` History | 7 | bare `.card`, no overflow | **wrap** |

Classify's three are contained **for free** — `{ maxHeight: 232, overflowY: "auto" }` (`:126`) makes
`overflow-x` compute to `auto`, because CSS resolves `visible` to `auto` when the other axis isn't
`visible`. So the entire table half of this ticket is two wrappers on NetWorth.

**Why not 013's patterns — and probably why the map excluded the editors from 013 in the first place:
both patterns assume read-only rows.** Breakdown and the unclassified pool carry live `<input>` and
`<select>` controls *inside* their cells. **B** is a markup rewrite into cards, which would have to re-home
working form controls; **A** pins an identity column beside editable cells and needs `border-collapse:
separate` plus z-index layering plus `›` affordances. They were designed for data you read, not data you
edit.

Two things ruled **below** the floor rather than fixed:

- **Reaching the classify control needs sideways scroll** — the `<select>` + Classify button are in the
  last of 5 columns on the unclassified pool. Genuinely awkward, but comfort is the floor/treatment line.
- **History's rows are tappable with no touch affordance** (`:277`). 013 fixed this for read-only views
  with `tr:active` + `›`. Here the row *does* something, so criterion 4 holds; it just doesn't advertise —
  the same as desktop, minus hover.

### The float

`Classify.jsx:116` puts `float: right` on a span holding a message and three buttons, inside an `<h3>`
whose text is "Rules · priority order". At 390px the float is wider than the space left for the heading, so
they collide — the live criterion-2 violation.

**The requirement is that heading and buttons don't collide at 390px; the mechanism is a build-session
call**, with one constraint recorded here: an inline style **cannot be media-queried**, so this has to
become a class — and it must **not** be done by making `.card h3` (styles.css:34) a flex container, which
every card in the app shares.

### The gutter

**012's prototype used 14px side padding for the content pane** (`mobile-shell-prototype.html:44-46`, with
`max(14px, env(safe-area-inset-*))`), not `.main`'s desktop `22px 28px`. 013 and 014 measured inside that
shell, and §3 above depends on it. **So 14px is load-bearing across the map but was never ratified — it
exists only as a number inside a prototype.** Graduated to
[The phone content gutter](021-phone-content-gutter.md).

### Inventory corrections

1. **Drag is a modal behind one button**, not a per-row handle in the rules list.
2. **Two modals share `overlay`/`sheet`** (`:410-417`), not one — and hiding ⇅ Reorder removes one from
   phone entirely.
3. **Five tables across the two editors**, none inventoried by 013.
4. **Containment was already asymmetric** — Classify's three free, NetWorth's two absent.
5. **`.link-btn` has no `:disabled` rule** and its explicit `color` defeats UA greying: both existing
   `disabled` props render invisibly, on desktop as well.
6. **`textarea` is styled nowhere** — a white box on a dark modal at every width.
7. **The label column is 124px, not ~200px.**
