# Wayfinder — local-markdown tracker

GitHub Issues is disabled on this repo, so wayfinder maps live here as files.

## Layout
- `map-<slug>.md` — a **map** (label `wayfinder:map`). The index; loaded once per session.
- `tickets/NNN-<slug>.md` — a **ticket** (child issue of a map). Body is one `## Question`.
- `research/<slug>.md` — findings captured by a `research` ticket's subagent.

## Frontmatter convention (the tracker's "fields")
```yaml
id: 3                    # numeric identity, unique per map
title: Rule conflict & ordering
type: grilling           # wayfinder:<type> — research | prototype | grilling | task
status: open             # open | closed
assignee:                # a name = claimed; empty = unclaimed
blocked_by: [1]          # ids of tickets that must close first (native-blocking fallback)
parent: map-spend-classification
```

## Operations
- **Claim**: set `assignee:` to the dev's name **before** any work.
- **Blocked**: a ticket is blocked while any id in `blocked_by` is still `open`.
- **Frontier query**: tickets where `status: open` AND `assignee:` empty AND every `blocked_by` id is `closed`. These are takeable now.
- **Resolve**: append a `## Resolution` section to the ticket, set `status: closed`, then add a one-line pointer to the map's *Decisions so far*.
