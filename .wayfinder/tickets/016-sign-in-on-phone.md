---
id: 16
title: Sign-in on a phone
type: grilling
status: open
assignee:
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
