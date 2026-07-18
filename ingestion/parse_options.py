"""Load sold-option trades (wheel strategy) into option_trade.

Two sources, reconciled to one row per contract (underlying, expiry, strike, type):

  1. Tiger — raw flex Activity Statements (data/tiger-prime/*.csv, data/tiger-cash-boost/*.csv),
     `Trades` section, asset type `Option`. Per-file header maps columns by NAME (offsets shift
     across years: 2020=54 cols, else 53). Legs are classified open/close by `Activity Type`
     (`OpenShort`/`Close`); older files leave it blank -> inferred from qty sign (<0 open, >0 close).
     Fees are summed from the named fee columns; Tiger's own `Realized P/L` is used for closed legs.

  2. IBKR — data/ibkr-options/options.csv (the pre-reconciled 12-col export carved from the old
     Tiger archive; IBKR flex files carry no trades, so this is the only record). Loaded under the
     IBKR account.

Realized P&L (native ccy) per contract:
    closed:  sum(Tiger Realized P/L of close legs) + expired credit of any un-closed remainder
    expired: premium_open * contracts * multiplier - fees_open   (full credit kept; assignment's
             stock leg lives in txn and is lumped with expired, as the old archive loader did)
    open:    None (unrealised)

Idempotent via dedup_hash. Run:  PYTHONPATH=. .venv/bin/python -m ingestion.parse_options
"""
import csv
import datetime as dt
import glob
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio.db import SessionLocal
from portfolio.models import OptionTrade
from ingestion.load import ROOT, batch, count, h, maps, num, pdate, prune_stale, upsert

TIGER_GLOBS = ["data/tiger-prime/*.csv", "data/tiger-cash-boost/*.csv"]
IBKR_SRC = os.path.join(ROOT, "data", "ibkr-options", "options.csv")
CCY = {"US": "USD", "HK": "HKD"}
MULT = {"US": 100, "HK": 1}                  # HK contract sizes vary; default 1 (rare here)

# option symbol: bare "AMD 20210917 PUT 77.5" OR wrapped "Advanced Micro Devices (AMD ... )".
_SYM = re.compile(r"([A-Z0-9.]+)\s+(\d{8})\s+(PUT|CALL)\s+([\d.]+)")

# fee columns in the Tiger flex Trades section (everything between Amount and Realized P/L,
# EXCLUDING 'Accrued Interest in Trade'). Summed by NAME so shifting offsets don't matter.
_FEE_COLS = {
    "Transaction Fee", "Other Tripartite fees", "Settlement Fee", "SEC Fee",
    "Option Regulatory Fee", "Stamp Duty", "Transaction Levy", "Clearing Fee",
    "Trading Activity Fee", "Exchange Fee", "Future Regulatory Fee", "Commission",
    "Platform Fee", "Option Settlement Fee", "Subscription Fee", "Redemption Fee",
    "Switching Fee", "PH Stock Transaction Tax", "Tax Service Fee", "AFRC Transaction Levy",
    "Trading Tariff", "Brokerage fee", "Handing Fee", "Securities Management Fee",
    "Transfer Fees (CSDC)", "Transfer Fees (HKSCC)", "Stamp Duty On Stock Borrowing",
    "Consolidated Audit Trail Fee", "Processing Fee", "CM DA SI Fee", "DVP SI Fee",
    "IPO Transaction Fee", "IPO Process Fee", "Ipo Settle Fee", "IPO Channel Fee", "GST",
}


def money(s):
    """Parse '$15.50', '($6.80)', ' $0.00   ' -> float; parens => negative."""
    s = str(s or "").strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    v = num(s.strip("()"))
    if v is None:
        return None
    return -v if neg else v


def _und(ticker):
    """Normalise underlying to the archive's convention (HK counters carry a '.HK' suffix)."""
    t = (ticker or "").upper()
    return t[:-3] if t.endswith(".HK") else t


def _expiry(s):
    """Option expiry is 8-digit YYYYMMDD in the symbol (e.g. '20260710')."""
    try:
        return dt.datetime.strptime(s, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def _flex_option_legs():
    """Yield normalised option legs from all Tiger flex statements."""
    for pat in TIGER_GLOBS:
        for f in sorted(glob.glob(os.path.join(ROOT, pat))):
            hdr = None
            for row in csv.reader(open(f, encoding="utf-8-sig")):
                if not row or row[0] != "Trades":
                    continue
                if len(row) > 4 and row[4] == "Symbol":          # per-file header
                    hdr = {name: i for i, name in enumerate(row)}
                    continue
                if not hdr or len(row) <= 4 or row[3] != "DATA" or row[1] != "Option":
                    continue
                g = lambda name: row[hdr[name]] if name in hdr and hdr[name] < len(row) else ""
                sym = g("Symbol")
                if not sym.strip():                              # continuation row
                    continue
                m = _SYM.search(sym)
                if not m:
                    continue
                und, exp, typ, strike = m.groups()
                qty = num(g("Quantity")) or 0.0
                act = g("Activity Type").strip()
                is_open = act == "OpenShort" or (act == "" and qty < 0)
                is_close = act == "Close" or (act == "" and qty > 0)
                if not (is_open or is_close):
                    continue
                mkt = g("Market") or "US"
                yield dict(
                    underlying=_und(und), expiry=_expiry(exp), option_type=typ.lower(),
                    strike=float(strike), market=mkt, mult=MULT.get(mkt, 100),
                    qty=abs(qty), price=num(g("Trade Price")) or 0.0,
                    fees=abs(sum(num(g(n)) or 0.0 for n in _FEE_COLS if n in hdr)),
                    realized=num(g("Realized P/L")) or 0.0,
                    trade_date=pdate((g("Trade Time") or "")[:10]),
                    is_open=is_open,
                )


def _reconcile(legs, a, alias):
    """Group legs by contract key -> one OptionTrade payload dict each."""
    grp = defaultdict(lambda: {
        "open_ct": 0.0, "open_val": 0.0, "open_fees": 0.0, "open_dates": [],
        "close_ct": 0.0, "close_val": 0.0, "close_fees": 0.0, "close_dates": [],
        "tiger_real": 0.0, "mult": 100, "market": "US",
    })
    for lg in legs:
        k = (lg["underlying"], lg["expiry"], lg["option_type"], lg["strike"])
        d = grp[k]
        d["mult"], d["market"] = lg["mult"], lg["market"]
        val = lg["price"] * lg["qty"] * lg["mult"]
        if lg["is_open"]:
            d["open_ct"] += lg["qty"]; d["open_val"] += val; d["open_fees"] += lg["fees"]
            if lg["trade_date"]:
                d["open_dates"].append(lg["trade_date"])
        else:
            d["close_ct"] += lg["qty"]; d["close_val"] += val; d["close_fees"] += lg["fees"]
            d["tiger_real"] += lg["realized"]
            if lg["trade_date"]:
                d["close_dates"].append(lg["trade_date"])

    from datetime import date
    today = date.today()
    payload, occ = [], Counter()
    for (und, exp, typ, strike), d in grp.items():
        oc, cc = d["open_ct"], d["close_ct"]
        if oc < 1e-9:
            continue                                     # close with no open -> skip (shouldn't happen)
        mult = d["mult"]
        prem_open = d["open_val"] / (oc * mult)
        prem_close = (d["close_val"] / (cc * mult)) if cc > 1e-9 else 0.0
        open_d = min(d["open_dates"]) if d["open_dates"] else None
        close_d = max(d["close_dates"]) if d["close_dates"] else None
        rem = oc - cc                                    # contracts opened but never closed
        if cc > 1e-9:
            outcome = "closed"
            realized = d["tiger_real"]                   # Tiger figure nets the closed round-trips
            if rem > 1e-6:                               # remainder expired worthless -> credit kept
                realized += (d["open_val"] / oc) * rem - (d["open_fees"] / oc) * rem
        elif exp and exp <= today:
            outcome = "expired"                          # incl. assigned (stock leg is in txn)
            realized = d["open_val"] - d["open_fees"]
        else:
            outcome = "open"
            realized = None
        key = (und, typ, str(strike), str(exp), str(open_d))
        occ[key] += 1
        payload.append(dict(
            account_id=a.id, security_id=alias.get(und), underlying=und,
            market=d["market"], option_type=typ, contracts=oc, strike=strike, multiplier=mult,
            open_date=open_d, expiry_date=exp, close_date=close_d,
            premium_open=prem_open, premium_close=prem_close,
            fees_open=d["open_fees"], fees_close=d["close_fees"], realized_pl=realized,
            currency=CCY.get(d["market"], "USD"), outcome=outcome,
            source_file="tiger-flex/options", dedup_hash=h(*key, occ[key]),
        ))
    return payload


def _archive_legs(src, a, alias):
    """Parse the pre-reconciled 12-col archive export (used for IBKR orphans)."""
    if not os.path.exists(src):
        return []
    rows = [r for r in csv.reader(open(src)) if any(c.strip() for c in r)][1:]  # drop blanks + header
    payload, occ = [], Counter()
    for r in rows:
        if len(r) < 11 or not r[1].strip():
            continue
        market, ticker, otype = r[0].strip(), r[1].strip().upper(), r[4].strip().lower()
        contracts, strike = num(r[2]), money(r[3])
        open_d, expiry, close_d = pdate(r[5]), pdate(r[8]), pdate(r[9])
        prem_open, fees_open = money(r[6]), (money(r[7]) or 0.0)
        prem_close = abs(money(r[10]) or 0.0)
        fees_close = (money(r[11]) if len(r) > 11 else 0.0) or 0.0
        mult = MULT.get(market, 100)
        realized = None
        if prem_open is not None and contracts is not None:
            realized = (prem_open - prem_close) * contracts * mult - fees_open - fees_close
        if close_d is None:
            outcome = "open"
        elif (expiry and close_d < expiry) or prem_close > 0:
            outcome = "closed"
        else:
            outcome = "expired"
        key = (ticker, otype, str(strike), str(contracts), str(open_d), str(expiry))
        occ[key] += 1
        payload.append(dict(
            account_id=a.id, security_id=alias.get(ticker), underlying=ticker,
            market=market or None, option_type=otype, contracts=contracts or 0, strike=strike,
            multiplier=mult, open_date=open_d, expiry_date=expiry, close_date=close_d,
            premium_open=prem_open, premium_close=prem_close, fees_open=fees_open,
            fees_close=fees_close, realized_pl=realized, currency=CCY.get(market, "USD"),
            outcome=outcome, source_file="ibkr-options/options.csv", dedup_hash=h(*key, occ[key]),
        ))
    return payload


_UPSERT_COLS = ["premium_open", "premium_close", "fees_open", "fees_close", "close_date",
                "contracts", "realized_pl", "outcome", "security_id", "open_date"]


def load_options(session, acct, alias):
    tiger = acct.get("Tiger Prime")
    if not tiger:
        raise RuntimeError("account 'Tiger Prime' not seeded")
    n = 0
    # Tiger — reconciled from flex statements (replaces the retired archive rows on this account)
    flex = _reconcile(_flex_option_legs(), tiger, alias)
    b = batch(session, "options", "tiger-flex/options", len(flex))
    for p in flex:
        p["batch_id"] = b.id
    # replaces the retired archive rows on this account + any contract gone from the source
    prune_stale(session, OptionTrade, {p["dedup_hash"] for p in flex}, account_id=tiger.id)
    n += upsert(session, OptionTrade, flex, _UPSERT_COLS)
    # IBKR — pre-reconciled orphan export under the IBKR account
    ibkr = acct.get("IBKR")
    if ibkr:
        arc = _archive_legs(IBKR_SRC, ibkr, alias)
        b = batch(session, "options-ibkr", "data/ibkr-options/options.csv", len(arc))
        for p in arc:
            p["batch_id"] = b.id
        prune_stale(session, OptionTrade, {p["dedup_hash"] for p in arc}, account_id=ibkr.id)
        n += upsert(session, OptionTrade, arc, _UPSERT_COLS)
    return n


def main():
    s = SessionLocal()
    acct, alias = maps(s)
    n = load_options(s, acct, alias)
    s.commit()
    total = count(s, OptionTrade)
    print(f"option_trade: +{n} new (total {total})")
    s.close()


if __name__ == "__main__":
    main()
