"""What a leg row is (`is_leg`) and the detail page's bucket-column keys (`LEG_FIELDS`). Tiny on
purpose: `carry`, `fold` and `ticker` all need it."""
from __future__ import annotations


def is_leg(r):
    """Whether a fold row is a leg worth a column: it holds units, money went in, income came
    out, **or units entered with no recorded cost**. `/api/positions`' closed-row drop rule,
    stated once so that endpoint and the detail page agree on what a leg is. Everything else is
    noise — a column of zeros that explains nothing — or an emptied predecessor whose cost
    carried to its successor.

    **The fourth clause is the refusal, and without it `invested_native: 0.0` means two
    different things.** ASTREA6B's 15,000 units entered and left; its `invested` is zero because
    the amount is UNKNOWN, which is the refusal itself, and the first three clauses read that as
    "never really held". The row then failed every entry point at once — absent from Holdings,
    and 404 from `/api/holding`, because this function is that endpoint's 404 rule — so the one
    name in the book whose cost the ledger does not record was the one name no page could say so
    about. Unknown and zero must not be the same thing in the place that decides whether the
    reader ever sees the row.

    **§13's emptied predecessor is untouched.** A husk's partition is entirely `costed` (C31
    2,700 of 2,700; 0P00006FYT 20,844.85 of 20,844.85) — what carried away is the money, not the
    knowledge — so `unknown` is 0 and it stays dropped. Measured on the live book: this clause
    adds exactly one row, and both husks still fail."""
    return (r["units"] > 1e-6 or bool(r["invested_native"]) or bool(r["income_native"])
            or r["cost_partition"]["unknown"] > 1e-6)


# What one bucket column of the detail page carries (#143 §2). `bucket` and `status` label the
# column; every other key is also a summary key, so a bucket column and the Total column are one
# render path over N+1 objects. No cost basis — the tiles never split — and no return figure.
LEG_FIELDS = ("bucket", "status", "units", "avg_cost", "breakeven_price", "realised_pl_sgd",
              "unrealised_pl_sgd", "stock_pl_sgd", "income_sgd", "options_pl_sgd", "net_pl_sgd")
