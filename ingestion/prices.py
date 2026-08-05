"""Phase 3: latest prices + FX into the DB.

Stocks  -> Yahoo Finance (SG: <code>.SI, HK: <4-digit>.HK, MY: <code>.KL, US: <ticker>)
Fund    -> latest Endowus NAV (Amundi Prime USA)
FX      -> Yahoo (USDSGD=X, HKDSGD=X, EURSGD=X); SGD = 1
Only prices held securities (current_position). Run:
  PYTHONPATH=. .venv/bin/python -m ingestion.prices
"""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import text

from portfolio.db import SessionLocal
from portfolio.models import FxRate, Price

ROOT = os.path.dirname(os.path.dirname(__file__))
UA = {"User-Agent": "Mozilla/5.0"}
# The book's timezone. Singapore has had no DST since 1982, so a fixed offset is the whole
# rule — no tzdata needed, which matters because this also runs on Vercel.
SGT = dt.timezone(dt.timedelta(hours=8))


def sg_today():
    """Today in SGT — the date every price/FX row is stamped with.

    On a local run this is just date.today(). It exists for the scheduled Vercel Cron run,
    whose clock is UTC: it fires at 23:15 UTC, which is already the next SGT day, and
    date.today() there would stamp the row a day behind the identical local 06:15 SGT run.
    """
    return dt.datetime.now(SGT).date()


def yahoo_symbol(ticker, market):
    if market == "SG":
        return f"{ticker}.SI"
    if market == "HK":
        return f"{int(ticker):04d}.HK"     # 00010 -> 0010.HK
    if market == "MY":
        return f"{ticker}.KL"              # Bursa Malaysia, e.g. 3255.KL
    return ticker                          # US


def yahoo_price(sym):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
    req = urllib.request.Request(u, headers=UA)
    d = json.load(urllib.request.urlopen(req, timeout=10))
    m = d["chart"]["result"][0]["meta"]
    return float(m["regularMarketPrice"]), m.get("currency")


def endowus_nav():
    """latest Amundi Prime USA NAV per unit from the most recent Endowus statement."""
    files = sorted(glob.glob(os.path.join(ROOT, "data", "endowus statement", "endowus_*.pdf")))
    if not files:
        return None
    txt = subprocess.run(["pdftotext", "-layout", files[-1], "-"], capture_output=True, text=True).stdout
    m = re.search(r"Amundi Prime USA Fund\s+Equity(?:\s+Fund)?\s+\w[\w ]*?\s+[\d,]+\.\d+\s+S\$([\d,]+\.\d+)", txt)
    return float(m.group(1).replace(",", "")) if m else None


def upsert_price(s, security_id, d, close, ccy):
    s.merge(Price(security_id=security_id, date=d, close=close, currency=ccy, source="yahoo"))


def main(today=None):
    s = SessionLocal()
    today = today or sg_today()
    held = s.execute(text(
        "SELECT DISTINCT security_id, canonical_ticker, market, asset_type "
        "FROM current_position WHERE units > 0")).all()
    ok = fail = 0
    failed, fx_failed = [], []
    for sid, tk, market, atype in held:
        try:
            if atype == "fund":
                nav = endowus_nav()
                if nav:
                    upsert_price(s, sid, today, nav, "SGD"); ok += 1
                continue
            px, ccy = yahoo_price(yahoo_symbol(tk, market))
            upsert_price(s, sid, today, px, ccy); ok += 1
        except Exception as e:
            fail += 1
            failed.append(tk)
            print(f"  price fail {tk} ({market}): {type(e).__name__}")
    # FX -> SGD
    s.merge(FxRate(date=today, currency="SGD", rate_to_sgd=1))
    for ccy in ("USD", "HKD", "EUR", "MYR"):
        try:
            rate, _ = yahoo_price(f"{ccy}SGD=X")
            s.merge(FxRate(date=today, currency=ccy, rate_to_sgd=rate))
        except Exception as e:
            fx_failed.append(ccy)
            print(f"  fx fail {ccy}: {type(e).__name__}")
    s.commit()
    print(f"prices: {ok} ok, {fail} fail; fx loaded for {today}")
    s.close()
    return {"ok": ok, "fail": fail, "date": str(today),
            "failed": failed, "fx_failed": fx_failed}


if __name__ == "__main__":
    main()
