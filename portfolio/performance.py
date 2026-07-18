"""Performance engine — per security (native ccy), rolled up to market/account/bucket/total (SGD).

Money-weighted return (XIRR) from dated cashflows: trades (-qty*price), dividends (+),
fees (-), plus the current market value as a terminal inflow. Computed in the security's
native currency (exact); MV / income / P&L converted to SGD at the latest FX for aggregation
(cost leg uses latest FX too — an approximation until historical FX lands).
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict

from sqlalchemy import text

from .db import fx_map, latest_close, session_scope

log = logging.getLogger(__name__)

_ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}


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


def cdp_transactions(session=None):
    """CDP trades from the cdp_cost_lot table (priced) for the transactions view — the cost
    record the CDP statements omit. Loaded from data/cdp-stocks/transactions.csv by
    ingestion.load_cdp_cost. Returns txn-like dicts."""
    with session_scope(session) as s:
        rows = s.execute(text(
            "SELECT trade_date, ticker, stock_name, action, qty, unit_price, amount, currency "
            "FROM cdp_cost_lot ORDER BY trade_date")).mappings().all()
    return [{
        "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None, "account": "CDP",
        "ticker": r["ticker"], "name": r["stock_name"] or "", "action": r["action"] or "",
        "qty_signed": float(r["qty"] or 0),
        "price": float(r["unit_price"]) if r["unit_price"] is not None else None,
        "gross_amount": float(r["amount"]) if r["amount"] is not None else None,
        "currency": r["currency"] or "SGD", "source_file": "cdp-stocks/transactions.csv",
    } for r in rows]


# CDP rows that move stock between custodians rather than trade it. The CSV records these at
# market value with a POSITIVE Amount (the 2020-03-19 CDP->FSM migration of D05 and O5RU), which
# reads exactly like a sale. Booking them as proceeds hands the position its cost back in cash
# while the units re-enter at FSM as a free `transfer in` — cash out AND units kept.
CDP_TRANSFER = {"transfer out", "transfer in", "transfer_out", "transfer_in"}


def cdp_cost(session=None):
    """CDP cost/cashflows from the cdp_cost_lot table (Unit Price + Amount; cdp-statements
    don't carry them). Keyed by canonical ticker -> {flows:[(date,cash)], invested}.

    Transfers are skipped: the position is grouped per (funding_bucket, security), so a CDP->FSM
    move keeps both legs in the same position and the cost carries across on its own."""
    with session_scope(session) as s:
        rows = s.execute(text(
            "SELECT ticker, trade_date, qty, amount, action FROM cdp_cost_lot")).all()
    out = {}
    for ticker, d, qty, amount, action in rows:
        if (action or "").strip().lower() in CDP_TRANSFER:
            continue
        cash = float(amount or 0)                # buys negative (cash out), sells positive
        if abs(cash) < 1e-9:
            continue
        g = out.setdefault(ticker, {"flows": [], "invested": 0.0, "buy_cost": 0.0, "buy_qty": 0.0})
        g["flows"].append((d or dt.date.today(), cash))
        if cash < 0:
            g["invested"] += -cash
            g["buy_cost"] += -cash
            g["buy_qty"] += float(qty or 0)      # bought qty for avg-cost
    return out

# actions where qty*price is real cash paid/received (CPF/SRS CSVs use 'open market' etc.)
CASH_TRADE = {"buy", "sell", "open market", "ipo", "private placement",
              "rights", "rights issue", "subscription"}
# free / non-cash (bonus, scrip, transfers, gifts, snapshot-diff opens, corp actions)
ZERO_CASH = {"transfer_in", "transfer_out", "gift_in", "gifted stock in", "gifted stock out",
             "bonus", "bonus issuance", "scrip", "script dividend", "scrip dividend",
             "corp action", "corp_action", "open", "open/transfer_in", "transfer in",
             "sell/transfer_out", "sell/transfer", "stock dividend",
             "switch_in"}      # fund-switch IN leg: units only; cost carries from predecessor
# 'corp action' is a catch-all in the FSM ledger. A PRICED row is an entitlement the holder paid
# cash for — the ESR-LOGOS (UD1U) rights issues at 0.49 / 0.595 / 0.408, C38U, O5RU, S51. A
# zero-priced row is a bonus or consolidation (D05's 280 bonus shares). Only the first costs money.
PRICED_CORP_ACTION = {"corp action", "corp_action"}
# a fund fee paid by redeeming units (Endowus). No cash leaves the investor's pocket, so the
# unit drop already carries the whole cost through market value — booking a cash outflow too
# would charge the fee twice.
COST_IN_KIND = {"fee"}
# XIRR annualises, so a position held for days turns a rounding move into a triple-digit rate
# (1600 HEIM bought yesterday, -0.2% -> -79.6% p.a.). Below this span the number is noise.
MIN_XIRR_DAYS = 30


def classify(act, px):
    """How a txn row affects cost basis.

    cash         — real money moved; qty*price is the flow
    uncosted     — a trade whose price the source never carried. The units still land in market
                   value, so booking them at zero cost would invent a free lot.
    cost_in_kind — units redeemed to pay a fee; the market-value drop already carries the cost
    zero         — free units (bonus, scrip) or an internal move whose cost carries across
    unknown      — an action string nobody has classified; caller should shout, not assume free
    """
    if act in CASH_TRADE:
        return "cash" if px else "uncosted"
    if act in PRICED_CORP_ACTION:
        return "cash" if px else "zero"
    if act in COST_IN_KIND:
        return "cost_in_kind"
    if act in ZERO_CASH:
        return "zero"
    return "unknown"


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


def _fx_and_price(s):
    """Latest FX (currency -> rate_to_sgd) and latest close per security_id."""
    fx = fx_map(s)
    price = latest_close(s)
    return fx, price


def _carry_corporate_actions(s, pos, meta):
    """Carry a closed predecessor's cost onto the surviving security (e.g. C31 -> 9CI on the
    2021 CapitaLand restructuring; rename/split/consolidation/merger/switch). Mutates pos."""
    ca = s.execute(text("SELECT from_ticker, to_ticker, type FROM corporate_action "
                        "WHERE type IN ('rename','split','consolidation','merger','switch')")).all()
    # match predecessor/successor within the SAME funding bucket (corp actions are bucket-agnostic)
    tk_k = {(b, m["canonical_ticker"]): (b, sid) for (b, sid), m in meta.items()}
    buckets = {b for (b, _) in pos}
    switched = set()                       # successor keys whose cost carried through a cash switch
    for frm, to, typ in ca:
        for b in buckets:
            kf, kt = tk_k.get((b, frm)), tk_k.get((b, to))
            if not (kf and kt):
                continue
            if not (pos[kf]["invested"] > 1e-6 and abs(pos[kf]["units"]) < 1e-6):
                continue                   # predecessor must be a closed position carrying cost
            if typ == "switch":
                # cash switch (e.g. CPF fund switch): the redemption proceeds were reinvested
                # into the successor, not withdrawn. Carry the cost basis + the BUY legs only;
                # DROP the redemption inflow so it isn't double-counted as a gain. Successor may
                # already hold its own later top-up cost, so don't require it to be empty.
                pos[kt]["flows"].extend([fl for fl in pos[kf]["flows"] if fl[1] < 0])
                for fld in ("invested", "buy_cost"):
                    pos[kt][fld] += pos[kf][fld]
                switched.add(kt)
            elif pos[kt]["invested"] < 1e-6:        # non-cash conversion: successor starts empty
                pos[kt]["flows"].extend(pos[kf]["flows"])
                for fld in ("invested", "buy_cost", "buy_qty", "proceeds"):
                    pos[kt][fld] += pos[kf][fld]
            else:
                continue
            for fld in ("invested", "buy_cost", "buy_qty", "proceeds"):
                pos[kf][fld] = 0.0
            pos[kf]["flows"] = []
    # a switched holding rebased its units (predecessor units != successor units), so its carried
    # buy_qty is meaningless. The position was never sold for cash (only fee nibbles), so treat the
    # whole current holding as carrying the full invested cost: cost_basis = invested, realised = 0.
    for k in switched:
        if pos[k]["units"] > 1e-6:
            pos[k]["buy_cost"] = pos[k]["invested"]
            pos[k]["buy_qty"] = pos[k]["units"]


def _apply_txn(p, r, today):
    """Fold one non-CDP txn row into its position accumulator `p`. Returns the action
    string if it couldn't be classified (caller should warn), else None."""
    act = r["action"]
    px = float(r["price"]) if r["price"] is not None else None
    fee = abs(float(r["fees"])) if r["fees"] is not None else 0.0   # native ccy, same as px*qty
    kind = classify(act, px)
    if kind == "cash":
        # fees are a real cost: bigger outflow on a buy, smaller net inflow on a sell
        cash = -float(r["qty_signed"]) * px - fee
        p["fees"] += fee
        p["flows"].append((r["trade_date"] or today, cash))
        if cash < 0:
            p["invested"] += -cash
            p["buy_cost"] += -cash
            p["buy_qty"] += float(r["qty_signed"])
        else:
            p["proceeds"] += cash
    elif kind == "uncosted":
        if float(r["qty_signed"]) > 0:
            p["uncosted_units"] += float(r["qty_signed"])
    elif kind == "unknown":
        return act                                     # don't silently hand out free units
    return None


def _build_row(k, p, m, fx, price, today):
    """Assemble one position's output dict (native ccy + SGD) from its accumulated flows/units."""
    ccy = m["currency"] or "SGD"
    rate = fx.get(ccy, 1.0)
    px = price.get(k[1])
    mv = (p["units"] * px) if px else 0.0
    flows = list(p["flows"])
    if p["units"] > 1e-6 and px:
        flows.append((today, mv))
    cost_known = p["invested"] > 1e-6
    # XIRR is only meaningful when every unit that entered has a known cost and the flows
    # span long enough for annualisation to mean something.
    span = (max(d for d, _ in flows) - min(d for d, _ in flows)).days if flows else 0
    xirr_ok = cost_known and p["uncosted_units"] < 1e-6 and span >= MIN_XIRR_DAYS
    xirr = _xirr(flows) if xirr_ok else None
    total_pl = (mv + p["proceeds"] + p["income"] - p["invested"]) if cost_known else None
    simple = (total_pl / p["invested"]) if cost_known else None
    # cost basis of CURRENT holding (avg cost × held units) + unrealised P/L
    avg_cost = (p["buy_cost"] / p["buy_qty"]) if p["buy_qty"] > 1e-6 else None
    cost_basis = (avg_cost * p["units"]) if (avg_cost and p["units"] > 1e-6) else None
    unreal = (mv - cost_basis) if cost_basis is not None else None
    # realised stock P/L = sell proceeds − cost of the shares sold (buy_cost minus the
    # cost still tied up in the current holding). Closed positions: cost_basis None -> all sold.
    realised = (p["proceeds"] - p["buy_cost"] + (cost_basis or 0.0)) if cost_known else None
    return {
        "bucket": k[0], "accounts": sorted(p["accounts"]), "ticker": m["canonical_ticker"],
        "name": m["name"], "market": m["market"], "asset_type": m["asset_type"], "currency": ccy,
        "units": round(p["units"], 4), "price": px, "mv_native": round(mv, 2),
        "avg_cost": round(avg_cost, 4) if avg_cost else None,
        "cost_basis_native": round(cost_basis, 2) if cost_basis is not None else None,
        "cost_basis_sgd": round(cost_basis * rate, 2) if cost_basis is not None else None,
        "unrealised_pl_sgd": round(unreal * rate, 2) if unreal is not None else None,
        "realised_pl_sgd": round(realised * rate, 2) if realised is not None else None,
        "invested_native": round(p["invested"], 2), "income_native": round(p["income"], 2),
        "fees_sgd": round(p["fees"] * rate, 2), "cost_known": cost_known,
        "uncosted_units": round(p["uncosted_units"], 4),
        "total_pl_native": round(total_pl, 2) if cost_known else None,
        "invested_sgd": round(p["invested"] * rate, 2) if cost_known else 0.0,
        "mv_sgd": round(mv * rate, 2), "income_sgd": round(p["income"] * rate, 2),
        "pl_sgd": round(total_pl * rate, 2) if cost_known else None,
        "xirr": round(xirr, 4) if xirr is not None else None,
        "simple_return": round(simple, 4) if cost_known else None,
    }


def compute(session=None):
    today = dt.date.today()
    with session_scope(session) as s:
        fx, price = _fx_and_price(s)

        # group txns + dividends per (account, security)
        rows = s.execute(text("""
            SELECT t.account_id, a.name account, a.funding_bucket, t.security_id,
                   sec.canonical_ticker, sec.name, sec.market, sec.asset_type, sec.currency,
                   t.trade_date, t.action, t.qty_signed, t.price, t.gross_amount, t.fees
            FROM txn t JOIN account a ON a.id=t.account_id JOIN security sec ON sec.id=t.security_id
        """)).mappings().all()
        divs = s.execute(text("""
            SELECT account_id, security_id, pay_date, gross, currency FROM dividend
        """)).mappings().all()

        cdp = cdp_cost(s)
        # group per (bucket, security): transfers within a bucket (e.g. CDP->FSM) keep the cost
        # together, so a position transferred into FSM still carries its original CDP purchase cost.
        pos = defaultdict(lambda: {"units": 0.0, "flows": [], "invested": 0.0, "proceeds": 0.0,
                                    "income": 0.0, "buy_cost": 0.0, "buy_qty": 0.0, "fees": 0.0,
                                    "uncosted_units": 0.0, "accounts": set()})
        meta = {}
        _unknown_actions = set()
        for r in rows:
            k = (r["funding_bucket"], r["security_id"])
            meta[k] = r
            p = pos[k]
            p["units"] += float(r["qty_signed"])
            p["accounts"].add(r["account"])
            if r["account"] == "CDP":
                continue                                   # CDP cost comes from cdp-stocks below
            unk = _apply_txn(p, r, today)
            if unk is not None:
                _unknown_actions.add(unk)

        if _unknown_actions:
            log.warning("unclassified txn action(s) %s — treated as zero-cash; units may be uncosted",
                        sorted(_unknown_actions))

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

        bucket_by_acct_id = {r["account_id"]: r["funding_bucket"] for r in rows}
        for d in divs:
            k = (bucket_by_acct_id.get(d["account_id"]), d["security_id"])
            if k not in pos:
                continue
            amt = float(d["gross"] or 0)
            pos[k]["income"] += amt
            pos[k]["flows"].append((d["pay_date"] or today, amt))

        _carry_corporate_actions(s, pos, meta)

    out = []
    for k, p in pos.items():
        m = meta.get(k)
        if not m:
            continue
        out.append(_build_row(k, p, m, fx, price, today))
    # fold in the options income stream per underlying (realized, SGD). Options trade on the
    # cash account, so attach to the cash-bucket row for that security; orphan underlyings
    # (no stock position) are still counted in the Performance rollup via options.realized_by().
    from .options import realized_by_ticker
    opt = realized_by_ticker()
    for r in out:
        o = opt.get(r["ticker"]) if r["bucket"] == "cash" else None
        r["options_pl_sgd"] = o["pl_sgd"] if o else 0.0
    return out


def alloc_by_account(session=None):
    """market value per account (SGD) — for allocation charts (no cost needed)."""
    with session_scope(session) as s:
        fx, price = _fx_and_price(s)
        rows = s.execute(text(
            "SELECT account, security_id, currency, units FROM current_position WHERE units > 0")).all()
    agg = defaultdict(float)
    for acct, sid, ccy, u in rows:
        px = price.get(sid)
        if px:
            agg[acct] += float(u) * px * fx.get(ccy or "SGD", 1.0)
    return {k: {"mv_sgd": round(v, 2)} for k, v in agg.items()}


def rollup(rows, by):
    agg = defaultdict(lambda: {"mv_sgd": 0.0, "income_sgd": 0.0, "pl_sgd": 0.0, "cost_sgd": 0.0,
                               "capital_sgd": 0.0, "invested_sgd": 0.0,
                               "realised_pl_sgd": 0.0, "unrealised_pl_sgd": 0.0})
    for r in rows:
        # include closed positions (units≈0): they still carry realised P/L + dividends.
        if r["units"] <= 1e-6 and not r["cost_known"] and abs(r["income_sgd"]) < 1e-6:
            continue
        # positions are pooled per funding bucket, so a row can span accounts -> join them
        key = (", ".join(r["accounts"]) or "—") if by == "account" else r[by]
        g = agg[key]
        g["mv_sgd"] += r["mv_sgd"]; g["income_sgd"] += r["income_sgd"]
        if r["cost_known"]:                              # only sum P/L where cost is real
            g["pl_sgd"] += r["pl_sgd"] or 0
            g["cost_sgd"] += r["invested_sgd"] or 0
            # capital = cost basis of CURRENT holdings (so Capital + Unrealised = Current Value);
            # invested_sgd = total ever deployed incl. since-sold (return denominator)
            g["capital_sgd"] += r["cost_basis_sgd"] or 0
            g["invested_sgd"] += r["invested_sgd"] or 0
            g["realised_pl_sgd"] += r["realised_pl_sgd"] or 0
            g["unrealised_pl_sgd"] += r["unrealised_pl_sgd"] or 0
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
