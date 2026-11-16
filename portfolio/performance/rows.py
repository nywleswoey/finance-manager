"""Per-position XIRR from the fold's cashflows, and `_build_row`: the one serialised row shape
`/api/performance` returns."""
from __future__ import annotations

from ..money import rate_to_sgd
from ..nullable import rounded
from ..xirr import xirr as solve_xirr
from .actions import MIN_XIRR_DAYS


def _xirr_flows(p, px, today, part):
    """`(flows, cost_ok)` — one leg's dated XIRR cashflows, closed by the held units at market
    today, and whether its cost gate passes: units entered, every one of them with a known cost.

    One function because two solves read it: the leg's own `xirr` in `_build_row`, and the
    name's pooled `ticker_xirr` in `fold_positions`, which must gate each leg's cost exactly as
    the leg's own figure is gated. The span gate is not here — it belongs to whichever flows are
    solved (`_spans`)."""
    flows = list(p["flows"])
    if p["units"] > 1e-6 and px:
        flows.append((today, p["units"] * px))
    return flows, part["units_in"] > 1e-6 and part["unknown"] < 1e-6


def _spans(flows):
    """Whether dated flows span long enough for annualisation to mean something."""
    if not flows:
        return False
    return (max(d for d, _ in flows) - min(d for d, _ in flows)).days >= MIN_XIRR_DAYS


def _ticker_xirr(legs):
    """One XIRR per name: every listed leg's flows pooled and solved once, or `None` unless every
    leg passes its own cost gate and the pooled flows span `MIN_XIRR_DAYS`.

    Not a mean of the legs' rates — the mean of two IRRs is not the IRR of the merged flows (D05
    19.8% cash, 28.9% CPF; pooled 21.5%). Pooling adds native amounts, which is sound because
    every leg of a ticker is one security and so one currency. A leg with unknown cost poisons
    the pool rather than dropping out of it: its money is part of the name's, and a pool without
    it would be a rate on some other book. A leg too short to annualise alone does not — the
    span that matters is the pool's, so a days-old lot beside a years-held one still pools."""
    if not legs or not all(ok for _, ok in legs):
        return None
    flows = [f for fl, _ in legs for f in fl]
    return solve_xirr(flows) if _spans(flows) else None


def _build_row(k, p, m, fx, price, today, part, verdict):
    """Assemble one position's output dict (native ccy + SGD) from its accumulated flows/units.
    `part` is the leg's own cost partition and `verdict` its whole ticker's `net_verdict` —
    computed once, before any row is built, because a leg alone cannot know whether its name
    refuses."""
    ccy = m["currency"] or "SGD"
    rate = rate_to_sgd(ccy, fx)
    px = price.get(k[1])
    mv = (p["units"] * px) if px else 0.0
    flows, cost_ok = _xirr_flows(p, px, today, part)
    # `cost_known` is the partition read as a boolean: false only when EVERY entering unit is
    # unknown. Not `unknown == 0` — that would flip C38U (417 of 6,700 unpriced) to false and
    # delete its 7,756.75 Net from Holdings, Performance and Overview. A name with SOME cost
    # still answers "did I make money on this"; only a name with none has to refuse.
    cost_known = part["units_in"] > 1e-6 and part["unknown"] < part["units_in"] - 1e-6
    xirr = solve_xirr(flows) if cost_ok and _spans(flows) else None
    total_pl = (mv + p["proceeds"] + p["income"] - p["invested"]) if cost_known else None
    # a free lot has a cost of zero, so it has no denominator — a percentage return on nothing
    # is not a smaller number, it is not a number.
    simple = (total_pl / p["invested"]) if (cost_known and p["invested"] > 1e-6) else None
    # #143 §6: `null` on the cost-basis family means one thing — *not known*. So it is the
    # PARTITION that decides it, never the unit count. A leg holding unknown units cannot price
    # the shares it still has, and everything derived from that price goes null; a leg whose
    # every unit entered priced CAN price them, even holding none left, and ships the measured
    # zero. Nulling on `units ≈ 0` instead would say `not known` of TSLA and of F34's closed cpf
    # leg — whose Net is exact and whose unrealised is a genuine zero — and stop the bucket
    # column adding up.
    priceable = cost_known and part["unknown"] < 1e-6
    # cost basis of CURRENT holding (avg cost × held units). A priceable leg with nothing in
    # `buy_qty` is the emptied predecessor of a carry (C31, 0P00006FYT), whose scalars the carry
    # zeroed: it prices at zero, because what the carry moved is the money, not the knowledge.
    # The whole family answers together or not at all — `avg_cost: null` beside `cost_basis: 0.0`
    # would be one leg saying both "not known" and "measured zero" of the same fact.
    avg_cost = ((p["buy_cost"] / p["buy_qty"]) if p["buy_qty"] > 1e-6 else 0.0) \
        if priceable else None
    # `is not None`, not truthiness: a free lot's avg cost is 0.0, which is a measured price and
    # must not be read as "no answer" (AAPL's basis is zero because the unit was a gift).
    cost_basis = (avg_cost * p["units"]) if avg_cost is not None else None
    unreal = (mv - cost_basis) if cost_basis is not None else None
    # realised stock P/L = sell proceeds − cost of the shares sold (buy_cost minus the
    # cost still tied up in the current holding).
    realised = (p["proceeds"] - p["buy_cost"] + cost_basis) if cost_basis is not None else None
    # the pair's SUM is sound while neither member is: realised + unrealised is identically
    # proceeds − buy_cost + mv, and that needs no split of the cost between sold and held units.
    # It joins EVERY row, not only the doubted ones — it is what lets a doubted name show a Net
    # that is arithmetically exact, and a row that carries it only sometimes is a row nobody can
    # add up.
    #
    # Null only where the whole TICKER refuses (#143 §8). A leg whose every unit is unknown,
    # beside a leg with real cost, belongs to a caveat, and a caveat's Net stands — so that leg
    # reads its unknown units as free, which is the upper bound the caveat already declares and
    # exactly what a partly-unknown leg (C38U) does with its own unknown units. Nulling it on
    # `cost_known` instead would leave the name's Net short by a whole bucket.
    stock_pl = ((p["proceeds"] - p["buy_cost"] + mv)
                if cost_known or verdict != "refuse" else None)
    return {
        "bucket": k[0], "accounts": sorted(p["accounts"]), "ticker": m["canonical_ticker"],
        "name": m["name"], "market": m["market"], "asset_type": m["asset_type"], "currency": ccy,
        "units": round(p["units"], 4), "price": px, "mv_native": round(mv, 2),
        "avg_cost": rounded(avg_cost, 4),
        "cost_basis_native": rounded(cost_basis, 2),
        "cost_basis_sgd": rounded(cost_basis, 2, rate),
        "unrealised_pl_sgd": rounded(unreal, 2, rate),
        "realised_pl_sgd": rounded(realised, 2, rate),
        # rounded FROM the members where the members exist, not independently beside them: the
        # cent §14 measures on five tickers is `_build_row` rounding each component at 2dp, and
        # a third rounding of the same quantity would put that cent between this field and the
        # two it is the sum of. Where the pair collapses there is nothing to sum, so it rounds
        # the identity instead.
        "stock_pl_sgd": (round(rounded(realised, 2, rate) + rounded(unreal, 2, rate), 2)
                         if realised is not None and unreal is not None
                         else rounded(stock_pl, 2, rate)),
        "invested_native": round(p["invested"], 2), "income_native": round(p["income"], 2),
        "fees_sgd": round(p["fees"] * rate, 2), "cost_known": cost_known,
        "cost_partition": part,
        "total_pl_native": round(total_pl, 2) if cost_known else None,
        "invested_sgd": round(p["invested"] * rate, 2) if cost_known else None,
        "mv_sgd": round(mv * rate, 2), "income_sgd": round(p["income"] * rate, 2),
        "pl_sgd": round(total_pl * rate, 2) if cost_known else None,
        "xirr": rounded(xirr, 4),
        "simple_return": rounded(simple, 4),
    }
