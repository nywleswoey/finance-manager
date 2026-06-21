"""Performance engine — per security (native ccy), rolled up to market/account/bucket/total (SGD).

Money-weighted return (XIRR) from dated cashflows: trades (-qty*price), dividends (+),
fees (-), plus the current market value as a terminal inflow. Computed in the security's
native currency (exact); MV / income / P&L converted to SGD at the latest FX for aggregation
(cost leg uses latest FX too — an approximation until historical FX lands).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

import csv
import datetime as _dt
import os
import re

from sqlalchemy import text

from .db import SessionLocal

_ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}
_ROOT = os.path.dirname(os.path.dirname(__file__))


def _num(s):
    s = str(s or "").replace(",", "").replace("$", "").strip()
    if not s or s == "-":
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def cdp_transactions():
    """CDP trades from cdp-stocks.csv (with price + amount) for the transactions view —
    the cost record the CDP statements omit. Returns txn-like dicts."""
    out = []
    p = os.path.join(_ROOT, "data", "cdp-stocks", "transactions.csv")
    if not os.path.exists(p):
        return out
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        code = (r.get("Code") or "").upper()
        out.append({
            "trade_date": _try_date(r.get("Date")), "account": "CDP",
            "ticker": _ALIAS.get(code, code), "name": (r.get("Stock Name") or "").strip(),
            "action": (r.get("Action") or "").strip(), "qty_signed": _num(r.get("Qty")),
            "price": _num(r.get("Unit Price")) or None, "gross_amount": _num(r.get("Amount")),
            "currency": "SGD", "source_file": "cdp-stocks/transactions.csv",
        })
    return out


def _try_date(s):
    try:
        return _dt.datetime.strptime((s or "").strip(), "%d-%b-%y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def cdp_cost():
    """CDP cost/cashflows from cdp-stocks.csv (which has Unit Price + Amount; cdp-statements
    don't). Keyed by canonical ticker -> {flows:[(date,cash)], invested}."""
    out = {}
    p = os.path.join(_ROOT, "data", "cdp-stocks", "transactions.csv")
    if not os.path.exists(p):
        return out
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        code = (r.get("Code") or "").upper()
        code = _ALIAS.get(code, code)
        cash = _num(r.get("Amount"))            # buys negative (cash out), sells positive
        if abs(cash) < 1e-9:
            continue
        try:
            d = _dt.datetime.strptime(r["Date"].strip(), "%d-%b-%y").date()
        except (ValueError, KeyError):
            d = _dt.date.today()
        g = out.setdefault(code, {"flows": [], "invested": 0.0, "buy_cost": 0.0, "buy_qty": 0.0})
        g["flows"].append((d, cash))
        if cash < 0:
            g["invested"] += -cash
            g["buy_cost"] += -cash
            g["buy_qty"] += _num(r.get("Qty"))      # bought qty for avg-cost
    return out

# actions where qty*price is real cash paid/received (CPF/SRS CSVs use 'open market' etc.)
CASH_TRADE = {"buy", "sell", "open market", "ipo", "private placement",
              "rights", "rights issue", "subscription"}
# free / non-cash (bonus, scrip, transfers, gifts, snapshot-diff opens, corp actions)
ZERO_CASH = {"transfer_in", "transfer_out", "gift_in", "gifted stock in", "gifted stock out",
             "bonus", "bonus issuance", "scrip", "script dividend", "scrip dividend",
             "corp action", "corp_action", "open", "open/transfer_in", "transfer in",
             "sell/transfer_out", "stock dividend"}


def _xirr(flows, guess=0.1):
    """flows: list[(date, amount)]; amount<0 out, >0 in. Returns annualised rate or None."""
    flows = [(d, float(a)) for d, a in flows if abs(a) > 1e-9]
    if len(flows) < 2 or not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = min(d for d, _ in flows)
    yrs = [((d - t0).days / 365.0, a) for d, a in flows]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in yrs)

    def dnpv(r):
        return sum(-t * a / (1 + r) ** (t + 1) for t, a in yrs)

    r = guess
    for _ in range(100):                       # Newton
        f = npv(r)
        if abs(f) < 1e-7:
            return r
        d = dnpv(r)
        if abs(d) < 1e-12:
            break
        r -= f / d
        if r <= -0.9999:
            r = -0.99
    lo, hi = -0.9999, 10.0                      # bisection fallback
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def compute(session=None):
    s = session or SessionLocal()
    today = dt.date.today()
    fx = {c: float(r) for c, r in s.execute(text("SELECT currency, rate_to_sgd FROM fx_rate")).all()}
    price = {(sid): float(px) for sid, px in s.execute(text(
        "SELECT DISTINCT ON (security_id) security_id, close FROM price ORDER BY security_id, date DESC")).all()}

    # group txns + dividends per (account, security)
    rows = s.execute(text("""
        SELECT t.account_id, a.name account, a.funding_bucket, t.security_id,
               sec.canonical_ticker, sec.name, sec.market, sec.asset_type, sec.currency,
               t.trade_date, t.action, t.qty_signed, t.price, t.gross_amount
        FROM txn t JOIN account a ON a.id=t.account_id JOIN security sec ON sec.id=t.security_id
    """)).mappings().all()
    divs = s.execute(text("""
        SELECT account_id, security_id, pay_date, gross, currency FROM dividend
    """)).mappings().all()

    cdp = cdp_cost()
    # group per (bucket, security): transfers within a bucket (e.g. CDP->FSM) keep the cost
    # together, so a position transferred into FSM still carries its original CDP purchase cost.
    pos = defaultdict(lambda: {"units": 0.0, "flows": [], "invested": 0.0, "proceeds": 0.0,
                                "income": 0.0, "buy_cost": 0.0, "buy_qty": 0.0, "accounts": set()})
    meta = {}
    for r in rows:
        k = (r["funding_bucket"], r["security_id"])
        meta[k] = r
        p = pos[k]
        p["units"] += float(r["qty_signed"])
        p["accounts"].add(r["account"])
        if r["account"] == "CDP":
            continue                                   # CDP cost comes from cdp-stocks below
        act = r["action"]
        px = float(r["price"]) if r["price"] is not None else None
        if act in CASH_TRADE and px:
            cash = -float(r["qty_signed"]) * px
            p["flows"].append((r["trade_date"] or today, cash))
            if cash < 0:
                p["invested"] += -cash
                p["buy_cost"] += -cash
                p["buy_qty"] += float(r["qty_signed"])
            else:
                p["proceeds"] += cash
        elif act == "fee" and px:
            p["flows"].append((r["trade_date"] or today, -abs(float(r["qty_signed"]) * px)))

    # CDP cost (cdp-stocks) -> the CASH bucket position for that security
    sec_by_ticker = {m["canonical_ticker"]: sid for (b, sid), m in meta.items()}
    for tk, c in cdp.items():
        sid = sec_by_ticker.get(tk)
        k = ("cash", sid)
        if sid is None or k not in pos:
            continue
        pos[k]["flows"].extend(c["flows"])
        pos[k]["invested"] += c["invested"]
        pos[k]["buy_cost"] += c["buy_cost"]
        pos[k]["buy_qty"] += c["buy_qty"]
        pos[k]["proceeds"] += sum(a for _, a in c["flows"] if a > 0)

    bucket_of_acct = {r["account"]: r["funding_bucket"] for r in rows}
    for d in divs:
        # find the bucket this dividend's account belongs to
        b = None
        for r in rows:
            if r["account_id"] == d["account_id"]:
                b = r["funding_bucket"]; break
        k = (b, d["security_id"])
        if k not in pos:
            continue
        amt = float(d["gross"] or 0)
        pos[k]["income"] += amt
        pos[k]["flows"].append((d["pay_date"] or today, amt))

    # corporate-action cost carryover: a closed predecessor's cost follows to the surviving
    # security (e.g. C31 -> 9CI on the 2021 CapitaLand restructuring; rename/split/consolidation)
    ca = s.execute(text("SELECT from_ticker, to_ticker FROM corporate_action "
                        "WHERE type IN ('rename','split','consolidation','merger')")).all()
    tk_k = {m["canonical_ticker"]: (b, sid) for (b, sid), m in meta.items() if b == "cash"}
    for frm, to in ca:
        kf, kt = tk_k.get(frm), tk_k.get(to)
        if kf and kt and pos[kf]["invested"] > 1e-6 and abs(pos[kf]["units"]) < 1e-6 \
                and pos[kt]["invested"] < 1e-6:
            for fld in ("flows",):
                pos[kt][fld].extend(pos[kf][fld])
            for fld in ("invested", "buy_cost", "buy_qty", "proceeds"):
                pos[kt][fld] += pos[kf][fld]; pos[kf][fld] = 0.0
            pos[kf]["flows"] = []

    out = []
    for k, p in pos.items():
        m = meta.get(k)
        if not m:
            continue
        ccy = m["currency"] or "SGD"
        rate = fx.get(ccy, 1.0)
        px = price.get(k[1])
        mv = (p["units"] * px) if px else 0.0
        flows = list(p["flows"])
        if p["units"] > 1e-6 and px:
            flows.append((today, mv))
        cost_known = p["invested"] > 1e-6
        xirr = _xirr(flows) if cost_known else None
        total_pl = (mv + p["proceeds"] + p["income"] - p["invested"]) if cost_known else None
        simple = (total_pl / p["invested"]) if cost_known else None
        # cost basis of CURRENT holding (avg cost × held units) + unrealised P/L
        avg_cost = (p["buy_cost"] / p["buy_qty"]) if p["buy_qty"] > 1e-6 else None
        cost_basis = (avg_cost * p["units"]) if (avg_cost and p["units"] > 1e-6) else None
        unreal = (mv - cost_basis) if cost_basis is not None else None
        out.append({
            "bucket": k[0], "accounts": sorted(p["accounts"]), "ticker": m["canonical_ticker"],
            "name": m["name"], "market": m["market"], "asset_type": m["asset_type"], "currency": ccy,
            "units": round(p["units"], 4), "price": px, "mv_native": round(mv, 2),
            "avg_cost": round(avg_cost, 4) if avg_cost else None,
            "cost_basis_native": round(cost_basis, 2) if cost_basis is not None else None,
            "cost_basis_sgd": round(cost_basis * rate, 2) if cost_basis is not None else None,
            "unrealised_pl_sgd": round(unreal * rate, 2) if unreal is not None else None,
            "invested_native": round(p["invested"], 2), "income_native": round(p["income"], 2),
            "cost_known": cost_known,
            "total_pl_native": round(total_pl, 2) if cost_known else None,
            "invested_sgd": round(p["invested"] * rate, 2) if cost_known else 0.0,
            "mv_sgd": round(mv * rate, 2), "income_sgd": round(p["income"] * rate, 2),
            "pl_sgd": round(total_pl * rate, 2) if cost_known else None,
            "xirr": round(xirr, 4) if xirr is not None else None,
            "simple_return": round(simple, 4) if cost_known else None,
        })
    if session is None:
        s.close()
    return out


def alloc_by_account(session=None):
    """market value per account (SGD) — for allocation charts (no cost needed)."""
    s = session or SessionLocal()
    fx = {c: float(r) for c, r in s.execute(text("SELECT currency, rate_to_sgd FROM fx_rate")).all()}
    price = {sid: float(px) for sid, px in s.execute(text(
        "SELECT DISTINCT ON (security_id) security_id, close FROM price ORDER BY security_id, date DESC")).all()}
    rows = s.execute(text(
        "SELECT account, security_id, currency, units FROM current_position WHERE units > 0")).all()
    if session is None:
        s.close()
    agg = defaultdict(float)
    for acct, sid, ccy, u in rows:
        px = price.get(sid)
        if px:
            agg[acct] += float(u) * px * fx.get(ccy or "SGD", 1.0)
    return {k: {"mv_sgd": round(v, 2)} for k, v in agg.items()}


def rollup(rows, by):
    agg = defaultdict(lambda: {"mv_sgd": 0.0, "income_sgd": 0.0, "pl_sgd": 0.0, "cost_sgd": 0.0})
    for r in rows:
        if r["units"] <= 1e-6:
            continue
        g = agg[r[by]]
        g["mv_sgd"] += r["mv_sgd"]; g["income_sgd"] += r["income_sgd"]
        if r["cost_known"]:                              # only sum P/L where cost is real
            g["pl_sgd"] += r["pl_sgd"] or 0
            g["cost_sgd"] += r["invested_sgd"] or 0
    return {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in agg.items()}


if __name__ == "__main__":
    rows = compute()
    held = [r for r in rows if r["units"] > 1e-6]
    tot_mv = sum(r["mv_sgd"] for r in held)
    tot_inc = sum(r["income_sgd"] for r in held)
    tot_pl = sum(r["pl_sgd"] for r in held if r["cost_known"])
    n_cost = sum(1 for r in held if r["cost_known"])
    print(f"held positions: {len(held)}  ({n_cost} with known cost basis)")
    print(f"portfolio MV:  SGD {tot_mv:,.0f}")
    print(f"dividends:     SGD {tot_inc:,.0f}  (held only)")
    print(f"P/L (cost-known only): SGD {tot_pl:,.0f}")
    print("\nby market:", rollup(held, "market"))
    print("\ntop holdings by MV:")
    for r in sorted(held, key=lambda r: -r["mv_sgd"])[:8]:
        xs = f"{r['xirr']*100:.1f}%" if r["xirr"] is not None else "  - "
        print(f"  {r['name'][:22]:22} {r['ticker']:6} {r['currency']} mv_sgd={r['mv_sgd']:>10,.0f} "
              f"xirr={xs:>7} div={r['income_native']:>9,.0f}")
