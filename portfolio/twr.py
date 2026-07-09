"""Portfolio-level time-weighted return (TWR) from daily price + FX history.

Fetches daily closes (Yahoo) for held securities + daily FX -> values the whole portfolio
each trading day -> links daily sub-period returns excluding external cash flows (buys/sells).
Dividends count as return (not a flow). TWR strips out contribution timing -> comparable to
an index. Run: PYTHONPATH=. .venv/bin/python -m portfolio.twr
"""
import datetime as dt
import json
import urllib.request
from collections import defaultdict

from sqlalchemy import text

from .db import SessionLocal

UA = {"User-Agent": "Mozilla/5.0"}


def ysym(tk, market):
    if market == "SG":
        return f"{tk}.SI"
    if market == "HK":
        return f"{int(tk):04d}.HK"
    return tk


def daily(sym, rng="10y"):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range={rng}"
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15))
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    cl = res["indicators"]["quote"][0]["close"]
    out = {}
    for t, c in zip(ts, cl):
        if c is not None:
            out[dt.date.fromtimestamp(t)] = float(c)
    return out


def ffill(series, days):
    out, last = {}, None
    for d in days:
        if d in series:
            last = series[d]
        if last is not None:
            out[d] = last
    return out


# unit inflows that are RETURN in kind, not an external contribution (keep them in the return)
RETURN_IN_KIND = {"stock dividend", "bonus issuance"}


def _twr(days, txns, prices, ccy_of, fx):
    """True time-weighted return: chain-linked daily sub-period returns over the daily-priced
    sleeve. Each day r_t = (MV_t - C_t) / MV_{t-1}, where C_t is the net external contribution.

    C_t is the market value of that day's unit changes (shares entering/leaving — buy, sell,
    transfer, switch, IPO...), valued at the SAME daily price used for MV so a new position
    nets out instead of registering as return. Many source rows carry no price (transfers/
    opens), so we value by unit delta, not txn price. Stock dividends / bonus shares are return
    in kind — excluded from C_t. Returns (cumulative, annualised)."""
    import bisect

    price_sids = [sid for sid, p in prices.items() if p]
    cum = {}                                            # sid -> (sorted dates, running units)
    for sid in price_sids:
        evs = sorted((t["trade_date"], float(t["qty_signed"])) for t in txns if t["security_id"] == sid)
        d_, u_, run = [], [], 0.0
        for dd, q in evs:
            run += q
            d_.append(dd)
            u_.append(run)
        cum[sid] = (d_, u_)

    def units(sid, day):
        d_, u_ = cum[sid]
        i = bisect.bisect_right(d_, day) - 1
        return u_[i] if i >= 0 else 0.0

    def price_on(sid, day):
        px = prices[sid].get(day)
        if px is not None:
            return px
        fut = [d for d in prices[sid] if d >= day]      # pre-history buy: nearest forward close
        return prices[sid][min(fut)] if fut else None

    def mv(day):
        tot = 0.0
        for sid in price_sids:
            u = units(sid, day)
            if u <= 1e-9:
                continue
            px = prices[sid].get(day)
            if px is None:
                continue
            tot += u * px * fx.get(ccy_of[sid], {}).get(day, 1.0)
        return tot

    contrib = defaultdict(float)                        # day -> net external contribution (SGD)
    for sid in price_sids:
        per = defaultdict(float)
        for t in txns:
            if t["security_id"] == sid and t["action"] not in RETURN_IN_KIND:
                per[t["trade_date"]] += float(t["qty_signed"])
        for day, dq in per.items():
            if abs(dq) < 1e-9:
                continue
            px = price_on(sid, day)
            if px is None:
                continue
            contrib[day] += dq * px * fx.get(ccy_of[sid], {}).get(day, 1.0)

    factor, prev_mv, first_live = 1.0, None, None
    for day in days:
        m = mv(day)
        if prev_mv is not None and prev_mv > 1e-6:
            r = (m - contrib.get(day, 0.0)) / prev_mv
            if r > 0:                                   # guard against bad/gap data
                factor *= r
        if m > 1e-6:
            prev_mv = m
            if first_live is None:
                first_live = day
        elif prev_mv is not None:
            prev_mv = m                                 # went flat; keep chaining from here

    if first_live is None:
        return None, None
    yrs = max((days[-1] - first_live).days / 365.0, 0.1)
    ann = factor ** (1 / yrs) - 1
    return factor - 1, ann


def compute_twr():
    s = SessionLocal()
    held = s.execute(text(
        "SELECT security_id, canonical_ticker, market, asset_type, currency FROM current_position "
        "WHERE units > 0")).all()
    # txns for held securities (units over time + external cash flows)
    txns = s.execute(text(
        "SELECT security_id, trade_date, action, qty_signed, price, currency FROM txn "
        "WHERE trade_date IS NOT NULL AND security_id = ANY(:ids)"),
        {"ids": [h[0] for h in held]}).mappings().all()
    s.close()

    start = min((t["trade_date"] for t in txns), default=dt.date.today())
    days = [start + dt.timedelta(d) for d in range((dt.date.today() - start).days + 1)]

    # daily prices (native) + fx
    prices, ccy_of = {}, {}
    for sid, tk, market, atype, ccy in held:
        ccy_of[sid] = ccy or "SGD"
        if atype == "fund":
            continue  # fund: no daily series (Endowus monthly) -> skip from TWR
        try:
            prices[sid] = ffill(daily(ysym(tk, market)), days)
        except Exception:
            prices[sid] = {}
    fx = {"SGD": {d: 1.0 for d in days}}
    for c in ("USD", "HKD", "EUR"):
        try:
            fx[c] = ffill(daily(f"{c}SGD=X"), days)
        except Exception:
            fx[c] = {d: 1.0 for d in days}

    # money-weighted (XIRR): every external cash flow converted at the FX on its own date,
    # plus current market value (SGD) as a terminal inflow. Robust to the zero-value start.
    from .performance import _xirr

    flows = []
    CASH = {"buy", "sell", "open market", "ipo", "private placement", "rights", "rights issue"}
    for t in txns:
        if t["action"] in CASH and t["price"] is not None:
            rate = fx.get(t["currency"] or "SGD", {}).get(t["trade_date"], 1.0)
            flows.append((t["trade_date"], -float(t["qty_signed"]) * float(t["price"]) * rate))
    # dividends as positive flows (historical fx)
    s2 = SessionLocal()
    divs = s2.execute(text("SELECT pay_date, gross, currency FROM dividend WHERE pay_date IS NOT NULL")).all()
    s2.close()
    for d, g, c in divs:
        if g:
            flows.append((d, float(g) * fx.get(c or "SGD", {}).get(d, 1.0)))
    # CDP cost flows (cdp-stocks; CDP DB txns carry no price) — CDP is SGD
    from .performance import cdp_cost
    for tk, c in cdp_cost().items():
        flows.extend(c["flows"])
    # terminal market value (today, SGD) from latest prices
    today = dt.date.today()
    mv = 0.0
    for sid in prices:
        u = sum(float(t["qty_signed"]) for t in txns if t["security_id"] == sid)
        px = prices[sid].get(max(prices[sid], default=today)) if prices[sid] else None
        if u > 1e-9 and px:
            mv += u * px * fx.get(ccy_of[sid], {}).get(max(fx[ccy_of[sid]], default=today), 1.0)
    if mv > 0:
        flows.append((today, mv))
    xirr = _xirr(flows)
    twr_cum, twr_ann = _twr(days, txns, prices, ccy_of, fx)
    invested = sum(-a for _, a in flows if a < 0)
    received = sum(a for _, a in flows if a > 0)
    years = max((today - start).days / 365.0, 0.1)
    return {"xirr_annualised": round(xirr, 4) if xirr is not None else None,
            "twr_annualised": round(twr_ann, 4) if twr_ann is not None else None,
            "twr_cumulative": round(twr_cum, 4) if twr_cum is not None else None,
            "invested_sgd": round(invested, 0), "value_plus_income_sgd": round(received, 0),
            "years": round(years, 1), "from": str(start),
            "note": "money-weighted (XIRR) + time-weighted (TWR); fund excluded from daily series"}


if __name__ == "__main__":
    print(compute_twr())
