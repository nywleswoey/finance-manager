"""Load sold-option trades (wheel strategy) from the Tiger options export into option_trade.

Source: data/.archive/tiger-options/options.csv  (columns, by position):
  0 Market 1 Ticker 2 Contracts 3 Strikeprice 4 OptionType 5 CreatedAt(open)
  6 CostCents(premium received/share) 7 Fees(open) 8 Expiry 9 ClosedAt 10 Premium(buy-to-close) 11 Fees(close)

Premium column is the debit paid to close: "$0.00" = expired worthless / assigned (full credit kept),
"($6.80)" = paid 6.80/share to buy back. Realized P&L (native ccy):
    (premium_open - premium_close) * contracts * multiplier - fees_open - fees_close

Idempotent via dedup_hash. Run:  PYTHONPATH=. .venv/bin/python -m ingestion.parse_options
"""
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import func, select

from portfolio.db import SessionLocal
from portfolio.models import OptionTrade
from ingestion.load import ROOT, batch, h, maps, num, pdate, upsert

SRC = os.path.join(ROOT, "data", ".archive", "tiger-options", "options.csv")
ACCOUNT = "Tiger Prime"                      # options traded on the Tiger brokerage (cash bucket)
CCY = {"US": "USD", "HK": "HKD"}
MULT = {"US": 100, "HK": 1}                  # HK contract sizes vary; default 1 (rare here, 5 rows)


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


def load_options(session, acct, alias):
    if not os.path.exists(SRC):
        return 0
    rows = [r for r in csv.reader(open(SRC)) if any(c.strip() for c in r)]  # drop blank lines
    rows = rows[1:]                                                          # drop header
    b = batch(session, "options", "data/.archive/tiger-options/options.csv", len(rows))
    a = acct.get(ACCOUNT)
    if not a:
        raise RuntimeError(f"account {ACCOUNT!r} not seeded")
    payload, occ = [], Counter()
    for r in rows:
        if len(r) < 11:
            continue
        market = r[0].strip()
        ticker = r[1].strip().upper()
        if not ticker:
            continue
        contracts = num(r[2])
        strike = money(r[3])
        otype = r[4].strip().lower()
        open_d = pdate(r[5])
        prem_open = money(r[6])
        fees_open = money(r[7]) or 0.0
        expiry = pdate(r[8])
        close_d = pdate(r[9])
        prem_close = abs(money(r[10]) or 0.0)                # debit to close (always a cost)
        fees_close = money(r[11]) if len(r) > 11 else 0.0
        fees_close = fees_close or 0.0
        mult = MULT.get(market, 100)
        realized = None
        if prem_open is not None and contracts is not None:
            realized = (prem_open - prem_close) * contracts * mult - fees_open - fees_close
        # best-effort outcome: no close => still open; bought back early or for a debit => closed;
        # else expired worthless / assigned (assignment's stock leg lives in txn)
        if close_d is None:
            outcome = "open"
        elif (expiry and close_d < expiry) or prem_close > 0:
            outcome = "closed"
        else:
            outcome = "expired"
        key = (ticker, otype, str(strike), str(contracts), str(open_d), str(expiry))
        occ[key] += 1
        dh = h(*key, occ[key])
        payload.append(dict(
            account_id=a.id, security_id=alias.get(ticker), underlying=ticker,
            market=market or None, option_type=otype, contracts=contracts or 0,
            strike=strike, multiplier=mult, open_date=open_d, expiry_date=expiry,
            close_date=close_d, premium_open=prem_open, premium_close=prem_close,
            fees_open=fees_open, fees_close=fees_close, realized_pl=realized,
            currency=CCY.get(market, "USD"), outcome=outcome,
            source_file="tiger-options/options.csv", batch_id=b.id, dedup_hash=dh,
        ))
    return upsert(session, OptionTrade, payload,
                  ["premium_close", "fees_close", "close_date", "realized_pl", "outcome", "security_id"])


def main():
    s = SessionLocal()
    acct, alias = maps(s)
    n = load_options(s, acct, alias)
    s.commit()
    total = s.scalar(select(func.count()).select_from(OptionTrade))
    print(f"option_trade: +{n} new (total {total})")
    s.close()


if __name__ == "__main__":
    main()
