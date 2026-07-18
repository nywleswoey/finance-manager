"""Options-trading analytics: realized return from the sold-option (wheel) book.

Realized P&L is stored per trade in native currency (option_trade.realized_pl). Here we
roll it up to SGD (latest FX, matching the rest of the app) and slice by year / ticker /
type, with win-rate and premium-collected. Money-weighted return isn't meaningful for
cash-secured premium selling (no stable capital base), so we report realized P&L, premium
collected, and yield-style ratios instead.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import select

from portfolio.db import SessionLocal, fx_map
from portfolio.models import OptionTrade


def _fx(s):
    fx = fx_map(s)
    fx.setdefault("SGD", 1.0)
    return fx


def _sgd(v, ccy, fx):
    if v is None:
        return 0.0
    return float(v) * fx.get(ccy or "SGD", 1.0)


def _f(x):
    """float(x), passing None through (nullable numeric column -> nullable output)."""
    return float(x) if x is not None else None


def _is_open(t):
    """A contract is open only until it resolves. Expired-worthless legs carry
    outcome='expired' with close_date=None (never bought back) — those are REALIZED,
    not open. Fall back to close_date/realized_pl when outcome is unrecorded."""
    if t.outcome == "open":
        return True
    if t.outcome:                                  # expired | closed | assigned
        return False
    return t.close_date is None and t.realized_pl is None


def _realized_date(t):
    """When the P/L was realized: buy-to-close date, else expiry (expired worthless)."""
    return t.close_date or t.expiry_date


def compute():
    s = SessionLocal()
    fx = _fx(s)
    trades = s.scalars(select(OptionTrade)).all()

    by_year, by_month, by_ticker, by_type, by_ccy = {}, {}, {}, {}, {}
    total_pl = total_prem = 0.0
    wins = losses = closed = 0
    open_trades = []

    def bucket(d, k):
        d.setdefault(k, {"trades": 0, "wins": 0, "premium_sgd": 0.0, "pl_sgd": 0.0, "pl_native": 0.0, "currency": None})
        return d[k]

    for t in trades:
        ccy = t.currency or "USD"
        pl_n = float(t.realized_pl or 0)
        pl = _sgd(t.realized_pl, ccy, fx)
        prem = _sgd((t.premium_open or 0) * (t.contracts or 0) * (t.multiplier or 100), ccy, fx)
        if _is_open(t):
            open_trades.append(t)
            continue
        total_pl += pl
        total_prem += prem
        closed += 1
        if pl_n > 0:
            wins += 1
        elif pl_n < 0:
            losses += 1

        yr = t.open_date.year if t.open_date else 0
        rd = _realized_date(t)
        mo = f"{rd.year:04d}-{rd.month:02d}" if rd else "—"
        for d, key in ((by_year, yr), (by_month, mo), (by_ticker, t.underlying), (by_type, t.option_type), (by_ccy, ccy)):
            row = bucket(d, key)
            row["trades"] += 1
            row["wins"] += 1 if pl_n > 0 else 0
            row["premium_sgd"] += prem
            row["pl_sgd"] += pl
            row["pl_native"] += pl_n
            row["currency"] = ccy if d is by_ticker or d is by_ccy else None

    def listify(d, sort_key="pl_sgd"):
        out = []
        for k, v in d.items():
            v = dict(v)
            v["key"] = k
            v["win_rate"] = (v["wins"] / v["trades"]) if v["trades"] else None
            out.append(v)
        out.sort(key=lambda r: r[sort_key], reverse=True)
        return out

    s.close()
    return {
        "total_pl_sgd": round(total_pl, 2),
        "total_premium_sgd": round(total_prem, 2),
        "trades_closed": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / closed, 4) if closed else None,
        "open_trades": len(open_trades),
        "by_year": sorted(listify(by_year), key=lambda r: r["key"], reverse=True),
        "by_month": sorted(listify(by_month), key=lambda r: r["key"]),
        "by_ticker": listify(by_ticker),
        "by_type": listify(by_type),
        "by_currency": listify(by_ccy),
    }


def _closed_trades():
    """Yield (trade, fx) for each closed (realized) trade — expired legs ARE realized.
    Opens the session and loads FX once; the session stays open until iteration finishes."""
    s = SessionLocal()
    fx = _fx(s)
    try:
        for t in s.scalars(select(OptionTrade)).all():
            if not _is_open(t):
                yield t, fx
    finally:
        s.close()


def realized_by_ticker():
    """Closed-trade realized P/L (SGD + native) keyed by underlying ticker.
    For folding the options income stream into per-security (Holdings) views."""
    out = {}
    for t, fx in _closed_trades():
        r = out.setdefault(t.underlying, {"pl_sgd": 0.0, "pl_native": 0.0, "trades": 0,
                                          "currency": t.currency, "market": t.market})
        r["pl_sgd"] += _sgd(t.realized_pl, t.currency, fx)
        r["pl_native"] += float(t.realized_pl or 0)
        r["trades"] += 1
    return {k: {**v, "pl_sgd": round(v["pl_sgd"], 2), "pl_native": round(v["pl_native"], 2)}
            for k, v in out.items()}


def realized_by(dim):
    """Closed-trade realized P/L (SGD) grouped by dimension: 'market' | 'bucket' | 'account'.
    Options trade on the Tiger Prime cash account, so bucket='cash', account='Tiger Prime'."""
    agg = {}
    for t, fx in _closed_trades():
        if dim == "market":
            key = t.market or "—"
        elif dim == "bucket":
            key = "cash"
        else:                                          # account
            key = "Tiger Prime"
        agg[key] = agg.get(key, 0.0) + _sgd(t.realized_pl, t.currency, fx)
    return {k: round(v, 2) for k, v in agg.items()}


def _trade_dicts(stmt):
    """Run `stmt` (an OptionTrade select) and serialize each row to a dict at latest FX."""
    s = SessionLocal()
    fx = _fx(s)
    out = [_trade_dict(t, fx) for t in s.scalars(stmt).all()]
    s.close()
    return out


def trades_for(underlying):
    """Per-underlying option trade list (for the holding-detail view)."""
    return _trade_dicts(
        select(OptionTrade).filter(OptionTrade.underlying == underlying.upper())
        .order_by(OptionTrade.open_date.desc().nullslast()))


def _trade_dict(t, fx):
    return {
        "underlying": t.underlying, "type": t.option_type,
        "contracts": float(t.contracts or 0), "strike": _f(t.strike),
        "open_date": t.open_date.isoformat() if t.open_date else None,
        "expiry": t.expiry_date.isoformat() if t.expiry_date else None,
        "close_date": t.close_date.isoformat() if t.close_date else None,
        "premium_open": _f(t.premium_open),
        "premium_close": _f(t.premium_close),
        "realized_native": _f(t.realized_pl),
        "realized_sgd": round(_sgd(t.realized_pl, t.currency, fx), 2),
        "currency": t.currency, "outcome": t.outcome,
    }


def recent(limit=200):
    return _trade_dicts(
        select(OptionTrade).order_by(OptionTrade.open_date.desc().nullslast()).limit(limit))


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2))
