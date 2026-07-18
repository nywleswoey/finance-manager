"""Portfolio-level time-weighted return (TWR) from daily price + FX history.

Fetches daily closes (Yahoo) for held securities + daily FX -> values the whole portfolio
each trading day -> links daily sub-period returns excluding external cash flows (buys/sells).
Dividends count as return (not a flow), credited on ex-date because Yahoo's `close` is
unadjusted. TWR strips out contribution timing -> comparable to an index.

The same unit-delta contribution series feeds the money-weighted XIRR, so a position that
arrives without a txn price (transfer, snapshot-diff open, fund switch) still carries a cost
basis instead of landing in the terminal value for free.
Run: PYTHONPATH=. .venv/bin/python -m portfolio.twr
"""
import bisect
import datetime as dt
import json
import urllib.request
from collections import defaultdict

from sqlalchemy import text

from .db import SessionLocal, latest_close

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
# unit outflows that are a COST in kind (fund fee paid by redeeming units). No cash reaches the
# investor, so this is not a withdrawal — leave it out of C_t and let the MV drop bite the return.
COST_IN_KIND = {"fee"}
# unit changes that are neither a contribution nor a withdrawal
NON_EXTERNAL = RETURN_IN_KIND | COST_IN_KIND


def fx_on(fx, ccy, day):
    """SGD rate for `ccy` on `day`. Clamps to the nearest end of the series rather than silently
    falling back to 1.0 (a missing HKD rate defaulting to 1.0 overstates by ~6x). None if the
    currency has no series at all."""
    if ccy in (None, "SGD"):
        return 1.0
    ser = fx.get(ccy)
    if not ser:
        return None
    r = ser.get(day)
    if r is not None:
        return r
    ks = sorted(ser)
    return ser[ks[0]] if day < ks[0] else ser[ks[-1]]


def running_units(txns, sids):
    """sid -> (sorted trade dates, running unit total) for bisect lookup."""
    cum = {}
    for sid in sids:
        evs = sorted((t["trade_date"], float(t["qty_signed"])) for t in txns if t["security_id"] == sid)
        d_, u_, run = [], [], 0.0
        for dd, q in evs:
            run += q
            d_.append(dd)
            u_.append(run)
        cum[sid] = (d_, u_)
    return cum


def units_on(cum, sid, day):
    d_, u_ = cum[sid]
    i = bisect.bisect_right(d_, day) - 1
    return u_[i] if i >= 0 else 0.0


def traded_vwap(txns):
    """sid -> sorted [(date, vwap)] from priced txn rows.

    Volume-weights same-day priced rows into one price per (security, day), so securities
    Yahoo has no daily series for (funds, delisted tickers) still get a nearest-dated cost
    basis. Zero-qty priced rows carry no vwap and are dropped."""
    day_px, day_qty = defaultdict(float), defaultdict(float)
    for t in txns:
        if t["price"] is not None:
            q = abs(float(t["qty_signed"]))
            day_px[(t["security_id"], t["trade_date"])] += q * float(t["price"])
            day_qty[(t["security_id"], t["trade_date"])] += q
    txn_px = defaultdict(list)
    for (sid, day), q in sorted(day_qty.items()):
        if q > 1e-9:
            txn_px[sid].append((day, day_px[(sid, day)] / q))
    return txn_px


def contributions(txns, sids, px, ccy_of, fx):
    """day -> net external contribution (SGD, positive = units in).

    Values that day's net unit change at `px(sid, day)` — the same price used to value MV — so a
    new position nets out instead of registering as return. Valuing by unit delta rather than by
    txn price is what lets price-less rows (transfers, opens, snapshot-diff buys) carry a real
    cost basis. RETURN_IN_KIND and COST_IN_KIND unit changes are not external flows."""
    contrib = defaultdict(float)
    for sid in sids:
        per = defaultdict(float)
        for t in txns:
            if t["security_id"] == sid and t["action"] not in NON_EXTERNAL:
                per[t["trade_date"]] += float(t["qty_signed"])
        for day, dq in per.items():
            if abs(dq) < 1e-9:
                continue
            p = px(sid, day)
            rate = fx_on(fx, ccy_of[sid], day)
            if p is None or rate is None:
                continue
            contrib[day] += dq * p * rate
    return contrib


def _twr(days, txns, prices, ccy_of, fx, contrib, div_by_day=None):
    """True time-weighted return: chain-linked daily sub-period returns over the daily-priced
    sleeve. Each day r_t = (MV_t + D_t - C_t) / MV_{t-1}, where C_t is the net external
    contribution and D_t the dividends going ex that day.

    D_t is needed because Yahoo's `close` is unadjusted: the ex-date price drop lands in MV and
    the cash never returns to the series. Without it TWR understates by roughly the yield.
    Returns (cumulative, annualised)."""
    div_by_day = div_by_day or {}
    price_sids = [sid for sid, p in prices.items() if p]
    cum = running_units(txns, price_sids)

    def mv(day):
        tot = 0.0
        for sid in price_sids:
            u = units_on(cum, sid, day)
            if u <= 1e-9:
                continue
            px = prices[sid].get(day)
            rate = fx_on(fx, ccy_of[sid], day)
            if px is None or rate is None:
                continue
            tot += u * px * rate
        return tot

    factor, prev_mv, first_live = 1.0, None, None
    for day in days:
        m = mv(day)
        if prev_mv is not None and prev_mv > 1e-6:
            r = (m + div_by_day.get(day, 0.0) - contrib.get(day, 0.0)) / prev_mv
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
    # one row per (account, security): the same counter can sit in FSM and CPF at once
    held = s.execute(text(
        "SELECT DISTINCT security_id, canonical_ticker, market, asset_type, currency "
        "FROM current_position WHERE units > 0")).all()
    ids = sorted({h[0] for h in held})
    # txns for held securities (units over time + external cash flows)
    txns = s.execute(text(
        "SELECT security_id, trade_date, action, qty_signed, price, fees, currency FROM txn "
        "WHERE trade_date IS NOT NULL AND security_id = ANY(:ids)"), {"ids": ids}).mappings().all()
    # dividends scoped to held securities: a dividend whose purchase cost never entered `flows`
    # (sold-out position) is a free inflow that inflates XIRR.
    divs = s.execute(text(
        "SELECT security_id, COALESCE(ex_date, pay_date) AS ex_date, pay_date, gross, currency "
        "FROM dividend WHERE pay_date IS NOT NULL AND security_id = ANY(:ids)"),
        {"ids": ids}).mappings().all()
    # last known close per security — covers what Yahoo can't price (funds, delisted tickers)
    last_px = latest_close(s)
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
            fx[c] = {}
    price_sids = [sid for sid, p in prices.items() if p]

    # traded price per (security, day), for securities Yahoo has no daily series for
    txn_px = traded_vwap(txns)

    def px_daily(sid, day):
        """Daily close, forward-filled for a pre-history buy."""
        ser = prices[sid]
        v = ser.get(day)
        if v is not None:
            return v
        fut = [d for d in ser if d >= day]
        return ser[min(fut)] if fut else None

    def px_any(sid, day):
        """As px_daily, falling back to the nearest-dated traded price (the Endowus fee rows carry
        quarterly NAV) and then the last known close, so a fund or a delisted ticker gets a cost
        basis instead of free units. Nearest-by-date, not latest — a 2023 switch must not be
        valued at today's NAV."""
        if prices.get(sid):
            return px_daily(sid, day)
        near = txn_px.get(sid)
        if near:
            return min(near, key=lambda dp: abs((dp[0] - day).days))[1]
        return last_px.get(sid)

    # one definition of external contribution feeds both metrics
    contrib_twr = contributions(txns, price_sids, px_daily, ccy_of, fx)
    contrib_all = contributions(txns, ids, px_any, ccy_of, fx)

    # dividends. TWR credits them on ex-date (when the price drops), scoped to the daily-priced
    # sleeve — crediting a fund's dividend whose MV is absent from the series would be free return.
    # XIRR takes them on pay-date (when the cash lands), clamped to the first trade so t0 doesn't
    # anchor on a pre-history dividend.
    div_by_day = defaultdict(float)
    div_flows = []
    for d in divs:
        if not d["gross"]:
            continue
        g, ccy = float(d["gross"]), d["currency"] or "SGD"
        if d["security_id"] in price_sids:
            rate = fx_on(fx, ccy, d["ex_date"])
            if rate is not None:
                div_by_day[d["ex_date"]] += g * rate
        rate = fx_on(fx, ccy, d["pay_date"])
        if rate is not None and d["pay_date"] >= start:
            div_flows.append((d["pay_date"], g * rate))

    # money-weighted (XIRR): units in => cash out, units out => cash in, valued at the same price
    # MV uses; brokerage fees are a real cost; current market value is the terminal inflow.
    from .performance import _xirr

    flows = [(day, -c) for day, c in contrib_all.items()]
    for t in txns:
        if t["fees"]:
            rate = fx_on(fx, t["currency"] or "SGD", t["trade_date"])
            if rate is not None:
                flows.append((t["trade_date"], -abs(float(t["fees"])) * rate))
    flows.extend(div_flows)

    today = dt.date.today()
    cum_all = running_units(txns, ids)
    mv = 0.0
    for sid in ids:
        u = units_on(cum_all, sid, today)
        px = prices[sid][max(prices[sid])] if prices.get(sid) else last_px.get(sid)
        rate = fx_on(fx, ccy_of[sid], today)
        if u > 1e-9 and px and rate is not None:
            mv += u * px * rate
    if mv > 0:
        flows.append((today, mv))
    xirr = _xirr(flows)
    twr_cum, twr_ann = _twr(days, txns, prices, ccy_of, fx, contrib_twr, div_by_day)
    invested = sum(-a for _, a in flows if a < 0)
    received = sum(a for _, a in flows if a > 0)
    years = max((today - start).days / 365.0, 0.1)
    return {"xirr_annualised": round(xirr, 4) if xirr is not None else None,
            "twr_annualised": round(twr_ann, 4) if twr_ann is not None else None,
            "twr_cumulative": round(twr_cum, 4) if twr_cum is not None else None,
            "invested_sgd": round(invested, 0), "value_plus_income_sgd": round(received, 0),
            "years": round(years, 1), "from": str(start),
            "note": "money-weighted (XIRR, pay-date dividends) + time-weighted (TWR, ex-date "
                    "dividends); fund excluded from the daily series but not from XIRR"}


if __name__ == "__main__":
    print(compute_twr())
