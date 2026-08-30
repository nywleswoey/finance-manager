"""Per-transaction cost annotations — the free/transferred distinction the ledger cannot carry.

Every unpriced carry-in in this book is `open/transfer_in` on one account, and that one string
covers a landed corporate-action carry (9CI 2,700), a real in-specie distribution paid for as
part of a predecessor (C38U 417), and two windfalls (AAPL 1, HMN 153). The action string
therefore cannot decide whether the units were free or merely transferred, and neither can the
account: the broker's export says *transfer* because that is what its system recorded, and
nothing further is in the ledger to read.

So the knowledge lives here, per transaction, and **defaults to `unknown`** — a row nobody has
annotated is refused, not assumed free. The conservative polarity is deliberate: inventing a
free lot silently mints market value at zero cost, while refusing one is visible on screen.

**Per-security was rejected.** It breaks the day a ticker holds both a gift lot and a real
transfer-in, which is not hypothetical — AAPL is one unit of welcome gift beside nothing, and
the same shape on a name with a real position would be indistinguishable.

**Scope**: `open/transfer_in` and *zero-priced* `corp action`. A priced `corp action` is a
rights subscription the holder paid cash for and classifies as `cash` long before it reaches
here (see `performance.classify`), so the scope check below only has to name the action.

Not every free lot needs a row. `gifted stock in` (AMZN ×3, BABA ×1) and `bonus issuance`
(D05 cpf ×1) are mechanical — the broker's own word for a gift or a bonus issue is not
ambiguous — and are read straight off the action string by `performance.FREE_ACTION`.

The key is `(account, canonical ticker, trade_date, action, qty)` rather than `txn.id`, so an
annotation survives a re-ingest that renumbers the table. It is the loader's dedup key *minus*
two things, and both matter to whoever writes the next row:

  - **The occurrence counter.** `ingestion/load.py` hashes these five fields plus "nth identical
    row in this file", precisely because identical lots exist (the two `2-Sep-20 UD1U 11100` SRS
    buys). So a key here does not distinguish twins: two identical annotatable rows on one day
    would both take the annotation. None of the three below has a twin, and `unmatched()` says
    so out loud if that ever changes.
  - **The raw ticker.** The loader keys the ledger's symbol; this keys the canonical ticker the
    fold works in, which is what a curator reading a position can actually see.
"""
from __future__ import annotations

import datetime as dt

# What an annotation may assert. Anything unannotated is `unknown`. NOT the same set as the
# fold's own `_condition()`, which has a fourth internal answer (`pending`) for a row whose
# backing it has yet to resolve — that one is never something a human asserts.
ANNOTATION_CONDITIONS = ("costed", "free", "unknown")

# Actions an annotation may be written against — see **Scope** above.
ANNOTATABLE_ACTIONS = frozenset({"open/transfer_in", "corp action", "corp_action"})

# (account, ticker, trade_date, action, qty, condition, why)
ANNOTATIONS: list[tuple[str, str, dt.date, str, float, str, str]] = [
    ("Moomoo", "AAPL", dt.date(2022, 12, 28), "open/transfer_in", 1, "free", "welcome gift"),
    ("Moomoo", "HMN", dt.date(2023, 5, 28), "open/transfer_in", 153, "free",
     "given as a dividend"),
    ("FSM", "D05", dt.date(2024, 4, 30), "corp action", 280, "free", "bonus shares"),
]


def _key(account, ticker, trade_date, action, qty):
    """The five fields `ingestion.load` hashes a txn row on, normalised for lookup."""
    return (account, ticker, trade_date, action, round(float(qty or 0), 8))


def annotation_map() -> dict[tuple, str]:
    """`{natural key: condition}` — what the fold consults, one entry per annotation."""
    return {_key(*a[:5]): a[5] for a in ANNOTATIONS}


def condition_for(row, annotations: dict[tuple, str]) -> str | None:
    """The annotated condition for one txn mapping-row, or None when none covers it.

    Out-of-scope actions return None without consulting the map, so an annotation can only
    ever speak about the rows it was drawn to speak about."""
    if row["action"] not in ANNOTATABLE_ACTIONS:
        return None
    return annotations.get(_key(row["account"], row["canonical_ticker"], row["trade_date"],
                                row["action"], row["qty_signed"]))


def unmatched(txns, annotations: dict[tuple, str]) -> dict[tuple, int]:
    """Annotation keys that do not match exactly ONE txn row, keyed to the count they matched.

    Both failures are silent otherwise, and both are wrong in the expensive direction. **Zero**
    is a stale annotation — a re-ingest that moves AAPL's trade date by a day turns a measured
    free lot back into an `unknown` one, and the position quietly starts refusing a Net it used
    to answer. **Two or more** annotates a lot nobody looked at, because the key cannot tell
    twins apart (see the module docstring)."""
    seen = {k: 0 for k in annotations}
    for r in txns:
        if r["action"] not in ANNOTATABLE_ACTIONS:
            continue
        k = _key(r["account"], r["canonical_ticker"], r["trade_date"], r["action"],
                 r["qty_signed"])
        if k in seen:
            seen[k] += 1
    return {k: n for k, n in seen.items() if n != 1}
