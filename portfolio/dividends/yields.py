"""Trailing and forward dividend yield per current holding (`yields`): regular distributions only,
at the latest price, with the forward leg from SGX declarations where they exist."""
import datetime as dt
import statistics
from collections import defaultdict

from ingestion.prices import sg_today

from ..db import fetch_dicts, fx_map, latest_price, session_scope
from ..money import convert, rate_to_sgd
from ..nullable import cents, iso, num
from .adjustments import _active_adjustment, apply_capital_return
from .attribution import details
from .distributions import DRIFT_DAYS, _anniversary, _distributions
from .overrides import _components_for
from .special import _classify, _net_distributions

PRICE_STALE_DAYS = 7    # a price older than this many days is flagged stale on the yield columns


def _slot_date(d):
    return d["ex_date"] or d["pay_date"]


def _nearest_pairs(anniversaries, dates, tolerance):
    """`{i: j}` pairing each of `anniversaries` with at most one of `dates` within `tolerance`
    days, nearest pairs first, each date used once - unreceived_last_year()'s pairing."""
    pairs = sorted((abs((d - anniv).days), i, j)
                   for i, anniv in enumerate(anniversaries)
                   for j, d in enumerate(dates)
                   if abs((d - anniv).days) <= tolerance)
    match, used = {}, set()
    for _, i, j in pairs:
        if i not in match and j not in used:
            match[i] = j
            used.add(j)
    return match


def _forward(trailing_regular, declared):
    """The next 12 months' regular distributions as `(net_rate, currency, basis)`.

    A trailing regular distribution whose one-year anniversary (of its ex_date, else pay_date)
    is already paired with a later trailing distribution has had its slot paid again inside the
    window, so only that later one rolls forward. Each remaining one's anniversary is paired
    with the nearest SGX-declared announcement (its ex_date), nearest pairs first, as
    unreceived_last_year() pairs. Both pairings allow DRIFT_DAYS, narrowed to half the
    counter's median gap between payments so a monthly payer's slot never pairs with the
    neighbouring month's; a paired one takes the declared rate ("declared"),
    an unpaired one repeats its own net rate ("pattern"). A declared announcement left unpaired
    is a new or initiated distribution and counts on its own ("declared").
    `declared` is `[(announcement, net_rate)]`."""
    def anniversary(d):
        return _anniversary(_slot_date(d), _slot_date(d).year + 1)

    slots = sorted(_slot_date(d) for d in trailing_regular)
    gaps = [(b - a).days for a, b in zip(slots, slots[1:])]
    tolerance = min(DRIFT_DAYS, statistics.median(gaps) / 2) if gaps else DRIFT_DAYS
    repaid = _nearest_pairs([anniversary(d) for d in trailing_regular],
                            [_slot_date(d) for d in trailing_regular], tolerance)
    rolling = [d for i, d in enumerate(trailing_regular) if i not in repaid]
    match = _nearest_pairs([anniversary(d) for d in rolling], [a["ex_date"] for a, _ in declared],
                           tolerance)
    out = []
    for i, d in enumerate(rolling):
        if i in match:
            a, net = declared[match[i]]
            out.append((net, a["currency"], "declared"))
        else:
            out.append((d["net_rate"], d["currency"], "pattern"))
    used = set(match.values())
    out += [(net, a["currency"], "declared") for j, (a, net) in enumerate(declared) if j not in used]
    return out


def yields(s=None, today=None):
    """Per-held-counter trailing/forward regular dividend yield, special portions and
    capital-return payments excluded — the Dividends tab's yield columns.

    For each currently-held ticker: distinct_distributions() for its full per-unit-rate history,
    net of any recorded split's special portion then any active dividend_adjustment
    (`_net_distributions`), then `_classify` to flag any oversized payment. Trailing regular DPS
    sums the net rate of every regular-or-split distribution paid in the last 365 days - a split
    distribution's special portion never counts, whether or not it was also flagged (see
    `has_split` below). Forward regular DPS is `_forward()` over those and every SGX-declared
    announcement (`dividend_announcement`, itself net of capital return - announcements are not
    split, so a future special dividend there is not yet excludable) paid (pay_date, else
    ex_date) in the next 365 days - a ticker built only from declared rates is `basis`
    "declared", only from the trailing pattern "pattern", from both "declared+pattern", from
    neither "none". This is the same rolling-12-months analogue of what projected() already does
    to calendar year-end, over the next 365 days instead.

    Yield = DPS / latest price, each counter in its price's currency (`currency`): a dividend
    paid in another currency (UD1U pays EUR on an SGD quote) is restated in it through the
    latest FX before dividing, so `trailing_dps` / `forward_dps` are in that currency too;
    `dividend_currency` is the currency the counter's latest distribution was paid in.
    `portfolio_*_yield_pct` is the SGD-market-value-weighted average across every priced held
    counter (portfolio.db.fx_map / portfolio.money, which raises rather than silently defaulting
    a missing FX rate to 1:1 - a counter in a currency with no rate gets `None` DPS/yield/market
    value and is left out of the weighted average, not zeroed into it). A counter with dividend
    history but no price shows yield `None` (a dash on the tab); a priced counter with no regular
    dividend shows `0.0` - the two stay visually distinct from each other, and from each other
    alone, consistently.

    `excluded` lists every flagged-and-unsplit trailing distribution across every held counter,
    for the tab's "Excluded as possibly special" list. `regular` lists every OTHER trailing
    distribution with no recorded split (the ordinary case) - together with `excluded` and
    `marked_regular` below, every trailing-window distribution of every held counter appears in
    exactly one of the three, so the Dividends tab can offer a split on any of them, flagged or
    not. `marked_regular` lists every distribution carrying a split (dividend_flag_override),
    trailing window or not, for the tab's split list - `special_per_unit` is the recorded special
    portion (0 for the original "mark as regular" case) and `regular_per_unit` is the rate minus
    it (what `net_rate` further nets of any capital-return adjustment); a split distribution that
    the raw heuristic would also have flagged still carries `baseline`/`baseline_type`/`ratio`
    (the "why this one was flagged" context), null otherwise.

    `awaiting_identification` lists every distribution (trailing window or not, same scope as
    `marked_regular`) with more than one cached `dividend_announcement_component` line STILL
    needing the captain's call once any component already resolved as capital return
    (`capital_return_component`, see `_net_distributions`) is set aside - SGX's corporate-actions
    API never says which of the rest is regular and which is special (#captain's intent). A
    payment whose components aren't all in its own currency is left out (a special portion is
    recorded in the payment's currency - see `identify_components`). Each entry carries
    `components` (the cached per-unit rates, excluding any capital-return component) for the
    Dividends tab to list with a Normal/Special choice; `portfolio.dividends.identify_components`
    turns that choice into the usual `dividend_flag_override` split once every listed component is
    labelled. Until then the payment is untouched - still `excluded` if the raw heuristic flags
    it, `regular` otherwise - exactly as before this existed. A single-component payment, and one
    whose only OTHER component (after the capital-return one) is single, is never listed here;
    `excluded`/`regular`/`marked_regular` each carry `capital_return_component` (None, or the
    matched `{amount_per_unit, currency}`) so the Dividends tab can show what happened either
    way."""
    today = today or sg_today()
    trail_start = today - dt.timedelta(days=365)
    fwd_end = today + dt.timedelta(days=365)

    with session_scope(s) as s:
        fx = fx_map(s)
        prices = latest_price(s)
        securities = {r["ticker"]: r for r in fetch_dicts(s,
            "SELECT canonical_ticker ticker, id security_id, name, market, currency "
            "FROM security")}
        holdings = fetch_dicts(s,
            "SELECT canonical_ticker ticker, SUM(units) units FROM current_position "
            "GROUP BY canonical_ticker HAVING ABS(SUM(units)) > 1e-6")

        adjustments_by_sec = defaultdict(list)
        for r in fetch_dicts(s, "SELECT security_id, amount_per_unit, currency, start_date, "
                                "end_date, note FROM dividend_adjustment"):
            adjustments_by_sec[r["security_id"]].append(
                {**r, "amount_per_unit": num(r["amount_per_unit"])})
        overrides_by_sec = defaultdict(list)
        labels_by_override = defaultdict(list)
        for r in fetch_dicts(s, "SELECT override_id, amount_per_unit, currency, label "
                                "FROM dividend_flag_override_component"):
            labels_by_override[r["override_id"]].append(
                {**r, "amount_per_unit": num(r["amount_per_unit"])})
        for r in fetch_dicts(s, "SELECT id, security_id, ex_date, pay_date, special_per_unit "
                                "FROM dividend_flag_override"):
            overrides_by_sec[r["security_id"]].append(
                {**r, "special_per_unit": num(r["special_per_unit"]),
                 "components": labels_by_override.get(r["id"], [])})
        announced_by_sec = defaultdict(list)
        for r in fetch_dicts(s,
                "SELECT security_id, ex_date, pay_date, amount_per_unit, currency "
                "FROM dividend_announcement "
                "WHERE COALESCE(pay_date, ex_date) > :today AND COALESCE(pay_date, ex_date) <= :fwd_end",
                {"today": today, "fwd_end": fwd_end}):
            announced_by_sec[r["security_id"]].append(
                {**r, "amount_per_unit": num(r["amount_per_unit"])})
        # every announcement, not just the next-365-days window above - the ex-date-less
        # fallback match (`_components_for`, same tolerance `split_components` allows) needs a
        # past payment's own ex_date too, not only an upcoming one's.
        all_announced_by_sec = defaultdict(list)
        for r in fetch_dicts(s, "SELECT security_id, ex_date, pay_date FROM dividend_announcement"):
            all_announced_by_sec[r["security_id"]].append(r)
        components_by_sec = defaultdict(list)
        for r in fetch_dicts(s, "SELECT security_id, ex_date, amount_per_unit, currency "
                                "FROM dividend_announcement_component"):
            components_by_sec[r["security_id"]].append(
                {**r, "amount_per_unit": num(r["amount_per_unit"])})
        rows_by_ticker = defaultdict(list)
        for r in details(s)["rows"]:
            rows_by_ticker[r["ticker"]].append(r)

    rows, excluded, marked_regular, regular, awaiting_identification = [], [], [], [], []
    for h in sorted(holdings, key=lambda h: h["ticker"]):
        tk = h["ticker"]
        sec = securities.get(tk)
        if sec is None:
            continue
        sid = sec["security_id"]
        adjustments = adjustments_by_sec.get(sid, [])
        overrides = overrides_by_sec.get(sid, [])

        distributions = _distributions(rows_by_ticker.get(tk, []))
        for d in distributions:
            comps = _components_for(sid, d["ex_date"], d["pay_date"],
                                    components_by_sec, all_announced_by_sec)
            d["components"] = [{"amount_per_unit": c["amount_per_unit"], "currency": c["currency"]}
                               for c in comps]
        _net_distributions(distributions, adjustments, overrides)
        _classify(distributions)
        for d in distributions:
            # The capital-return component (if matched) is already accounted for automatically -
            # never offered as an identification choice, and never counted toward "more than one
            # rate line, which is special?" ambiguity (see _net_distributions).
            other = [c for c in d["components"] if c is not d["capital_return_component"]]
            d["identification_components"] = other
            d["needs_identification"] = (len(other) > 1 and not d["has_split"] and
                                         all(c["currency"] == d["currency"] for c in d["components"]))

        trailing = [d for d in distributions if trail_start <= d["pay_date"] <= today]
        trailing_regular = [d for d in trailing if not d["flagged"] or d["has_split"]]

        for d in trailing:
            if d["flagged"] and not d["has_split"]:
                excluded.append({
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "net_rate": round(d["net_rate"], 6),
                    "currency": d["currency"], "baseline": d["flag_baseline"],
                    "baseline_type": d["flag_baseline_type"], "ratio": d["flag_ratio"],
                    "capital_return_component": d["capital_return_component"],
                })
            elif not d["has_split"]:
                regular.append({
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "net_rate": round(d["net_rate"], 6),
                    "currency": d["currency"],
                    "capital_return_component": d["capital_return_component"],
                })
        for d in distributions:
            if d["has_split"]:
                marked_regular.append({
                    "id": d["override_id"],
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "net_rate": round(d["net_rate"], 6),
                    "currency": d["currency"], "baseline": d["flag_baseline"],
                    "baseline_type": d["flag_baseline_type"], "ratio": d["flag_ratio"],
                    "special_per_unit": round(d["special_per_unit"], 6),
                    "regular_per_unit": round(d["regular_rate"], 6),
                    "capital_return_component": d["capital_return_component"],
                    "capital_return_in_special": d["capital_return_in_special"],
                })
            if d["needs_identification"]:
                awaiting_identification.append({
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "currency": d["currency"],
                    "components": d["identification_components"],
                })

        declared = [(a, apply_capital_return(a["amount_per_unit"], a["currency"],
                                             a["ex_date"], adjustments)[0])
                    for a in announced_by_sec.get(sid, [])]
        forward = _forward(trailing_regular, declared)
        bits = {b for _, _, b in forward}
        basis = ("none" if not bits else "declared+pattern" if len(bits) == 2 else bits.pop())

        px = prices.get(sid)
        price_val = px["close"] if px else None
        price_date = px["date"] if px else None
        stale_days = (today - price_date).days if price_date else None
        ccy = (px and px["currency"]) or sec["currency"]

        try:
            trailing_dps = round(sum(convert(d["net_rate"], d["currency"], ccy, fx)
                                     for d in trailing_regular), 6)
            fwd_dps = round(sum(convert(v, c, ccy, fx) for v, c, _ in forward), 6)
        except ValueError:
            trailing_dps = fwd_dps = None
        try:
            mv_sgd = float(h["units"]) * price_val * rate_to_sgd(ccy, fx) if price_val is not None else None
        except ValueError:
            mv_sgd = None

        trail_yield = round(trailing_dps / price_val * 100, 3) if price_val and trailing_dps is not None else None
        fwd_yield = round(fwd_dps / price_val * 100, 3) if price_val and fwd_dps is not None else None
        active = _active_adjustment(adjustments, today)

        rows.append({
            "ticker": tk, "name": sec["name"], "market": sec["market"],
            "security_id": sid, "currency": ccy,
            "dividend_currency": distributions[-1]["currency"] if distributions else ccy,
            "price": price_val, "price_date": iso(price_date),
            "price_stale_days": stale_days,
            "price_is_stale": bool(stale_days and stale_days > PRICE_STALE_DAYS),
            "trailing_dps": trailing_dps, "forward_dps": fwd_dps, "forward_basis": basis,
            "trailing_yield_pct": trail_yield, "forward_yield_pct": fwd_yield,
            "mv_sgd": cents(mv_sgd),
            "capital_return": ({"amount_per_unit": num(active["amount_per_unit"]),
                                "currency": active["currency"], "note": active["note"]}
                               if active else None),
            "capital_return_clamped": any(d["capital_return_clamped"] for d in trailing),
        })

    total_mv = sum(r["mv_sgd"] for r in rows if r["mv_sgd"] is not None)

    def _weighted(key):
        counted = [r for r in rows if r["mv_sgd"] is not None and r[key] is not None]
        mv = sum(r["mv_sgd"] for r in counted)
        return round(sum(r["mv_sgd"] * r[key] for r in counted) / mv, 3) if mv else None

    return {
        "as_of": iso(today), "rows": rows,
        "portfolio_trailing_yield_pct": _weighted("trailing_yield_pct"),
        "portfolio_forward_yield_pct": _weighted("forward_yield_pct"),
        "total_mv_sgd": round(total_mv, 2),
        "excluded": sorted(excluded, key=lambda e: (e["pay_date"] or "", e["ticker"])),
        "marked_regular": sorted(marked_regular, key=lambda e: (e["pay_date"] or "", e["ticker"])),
        "regular": sorted(regular, key=lambda e: (e["pay_date"] or "", e["ticker"])),
        "awaiting_identification": sorted(awaiting_identification,
                                          key=lambda e: (e["pay_date"] or "", e["ticker"])),
    }
