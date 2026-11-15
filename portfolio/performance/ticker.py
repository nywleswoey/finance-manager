"""One ticker's legs folded into the Holdings → ticker page: a summary row plus one row per funding
bucket (`fold_ticker`)."""
from __future__ import annotations

from .legs import LEG_FIELDS, is_leg
from .verdict import _breakeven_price


def _sum(legs, k, n=2):
    return round(sum(r[k] for r in legs), n)


def _sum_known(legs, k):
    """Σ over the legs, or null if ANY leg is null. A leg's null means `not known` and nothing
    else (#143 §6 — a closed leg ships a measured 0.0), so a sum missing one leg would be a
    ticker figure short by a bucket: a Realised and an Unrealised that stop adding up to the
    Stock P/L beside them, which is what §14's identity forbids."""
    return None if any(r[k] is None for r in legs) else _sum(legs, k)


def _sum_stream(legs, k):
    """Σ over the legs that carry the stream, or null where no leg does — null on a stream
    field means it never existed (#143 §6), so an options stream on the cash leg is the
    ticker's whole options stream and a cpf leg's null contributes nothing."""
    vals = [r[k] for r in legs if r[k] is not None]
    return round(sum(vals), 2) if vals else None


def fold_ticker(rows, rate):
    """One ticker's `fold_positions` rows folded into the detail page's `summary` and its
    `buckets` split (#143 §2, §4). Pure: plain rows in, one dict out, no DB.

    `rate` is the ticker's SGD-per-unit FX rate — the one thing here that is not on a row and
    cannot be recovered from one. The summary's breakeven has to move an SGD shortfall back into
    the native price it is quoted in, and dividing one of the native/SGD column pairs to get
    there would divide two figures already rounded to the cent and would divide by ZERO on
    exactly the legs this file is careful about (a closed leg's mv, a free lot's cost basis).
    A parameter rather than a field on every row: both callers hold the FX map already, and a
    rate on the row would be a permanent `/api/positions` field no page may read. Every leg of a
    ticker is one currency, so one rate covers the fold.

    Returns `None` when `is_leg` keeps no leg — the caller's 404. A sum over nothing is `0`
    with nothing unknown, which reads `net_pl_sgd: 0, net_verdict: "hero"`: a lie that would
    survive at the wire even where no page renders it. That also covers an emptied predecessor.

    **Net ties with zero tolerance.** The summary's `net_pl_sgd` is the legs' shipped Nets added,
    never recomputed from full-precision quantities beside them, and every component is its
    column added — so `Σ leg Net`, `Σ summary components` and the hero agree to the cent.

    `xirr`, `simple_return`, `pl_sgd` and the singular `bucket` / `status` are **absent**, not
    null: nothing on the page reads them, and `pl_sgd` would be a second Net definition beside
    the one the page standardised on.

    The whole-ticker fields — both verdicts and the four return figures — already ride every
    leg identically (`fold_positions`), so they are read off the first leg, not re-derived.
    """
    legs = sorted((r for r in rows if is_leg(r)), key=lambda r: (-r["mv_sgd"], r["bucket"]))
    if not legs:
        return None
    first = legs[0]
    units = _sum(legs, "units", 4)
    cost_native = _sum_known(legs, "cost_basis_native")
    # the exact weighted average rather than an average of averages. One leg has nothing to
    # weight, and passes its own — which is also the only answer a closed leg has, with no units
    # left to divide by. Several legs holding nothing between them have no weights at all.
    if len(legs) == 1:
        avg_cost = first["avg_cost"]
    elif cost_native is not None and units > 1e-6:
        avg_cost = round(cost_native / units, 4)
    else:
        avg_cost = None
    counts = {c: _sum([r["cost_partition"] for r in legs], c, 4)
              for c in ("units_in", "costed", "free", "unknown")}
    counts["unknown_pct"] = (round(counts["unknown"] / counts["units_in"], 4)
                             if counts["units_in"] > 1e-9 else 0.0)
    nets = [r["net_pl_sgd"] for r in legs]
    summary = {
        "ticker": first["ticker"], "name": first["name"], "market": first["market"],
        "asset_type": first["asset_type"], "currency": first["currency"],
        "accounts": sorted({a for r in legs for a in r["accounts"]}),
        "units": units, "price": first["price"], "avg_cost": avg_cost,
        "cost_basis_native": cost_native, "cost_basis_sgd": _sum_known(legs, "cost_basis_sgd"),
        "mv_native": _sum(legs, "mv_native"), "mv_sgd": _sum(legs, "mv_sgd"),
        "realised_pl_sgd": _sum_known(legs, "realised_pl_sgd"),
        "unrealised_pl_sgd": _sum_known(legs, "unrealised_pl_sgd"),
        "stock_pl_sgd": _sum_known(legs, "stock_pl_sgd"),
        "income_sgd": _sum(legs, "income_sgd"),
        "options_pl_sgd": _sum_stream(legs, "options_pl_sgd"),
        # a refusal nulls every leg's Net together; any other verdict nets every leg
        "net_pl_sgd": None if first["net_verdict"] == "refuse" else round(sum(nets), 2),
        "net_verdict": first["net_verdict"],
        "return_pct": first["return_pct"], "return_verdict": first["return_verdict"],
        "peak_car_sgd": first["peak_car_sgd"], "return_span_days": first["return_span_days"],
        "cost_partition": counts,
        "invested_sgd": _sum_known(legs, "invested_sgd"),
        "invested_native": _sum(legs, "invested_native"), "fees_sgd": _sum(legs, "fees_sgd"),
        "cost_known": all(r["cost_known"] for r in legs),
    }
    # whole-ticker, so any leg's carries it; absent unless a carry reached the name (§12)
    if first.get("provenance"):
        summary["provenance"] = first["provenance"]
    # The ticker's breakeven is solved from the SUMMARY's components, not weighted across the
    # legs' own breakevens — the two are different prices whenever a leg is closed. A closed leg
    # has no breakeven of its own (no units to divide by) but its realised gains and dividends
    # are in the hero, so a weighted mean of the open legs would quote a price that zeroes only
    # part of the number printed above it. Solving the summary spreads the closed legs' money
    # over the units that are still there, which is the only reading under which the tile and
    # the hero are about the same position. Every input is the column as shipped, so a null
    # anywhere — a refusal, an unpriceable leg, or nothing held — refuses here too.
    summary["breakeven_price"] = _breakeven_price(summary, units, rate)
    buckets = [{k: r[k] for k in LEG_FIELDS} for r in
               ({**r, "status": "open" if r["units"] > 1e-6 else "closed"} for r in legs)]
    return {"summary": summary, "buckets": buckets}
