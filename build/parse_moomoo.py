#!/usr/bin/env python3
"""Parse Moomoo monthly PDF statements -> normalized share-movement events.

Each statement has a per-symbol table:
  <full name>
  <EXCH> <CCY> startQ startP startV endQ endP endV deltaV BuyQ SellQ TransferIn TransferOut
  <TICKER>
We emit buy/sell/transfer events from BuyQ/SellQ/TransferIn/TransferOut and also
record the ending quantity per symbol per month (to confirm current positions).
"""
import glob, os, re, csv, subprocess, sys

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
NUM = r"[+\-]?[\d,]+(?:\.\d+)?"
# Two table formats both start: <EXCH> <CCY> then numbers.
#  change-table  (11 nums): startQ startP startV endQ endP endV dV buyQ sellQ tin tout  -> endQ = nums[3]
#  holdings-table (8 nums): settledQ unsettledQ Qty mult price mktVal fx ccySGD          -> endQ = nums[2]
ROW = re.compile(r"^\s*(SGX|US|HK|SEHK|NYSE|NASDAQ)\s+([A-Z]{3})\s+((?:" + NUM + r"\s+){7,12}" + NUM + r")\s*$")

def f2(s):
    return float(s.replace(",", "").replace("+", "")) if s not in ("", "-") else 0.0

def parse(path):
    """Return list of (month, ticker, market, endQ) snapshots."""
    month = re.search(r"(\d{6})", path).group(1)
    ym = f"{month[:4]}-{month[4:]}"
    txt = subprocess.run(["pdftotext", "-layout", path, "-"],
                         capture_output=True, text=True).stdout
    lines = txt.splitlines()
    out = []
    for i, ln in enumerate(lines):
        m = ROW.match(ln)
        if not m:
            continue
        exch, ccy = m.group(1), m.group(2)
        nums = [f2(x) for x in m.group(3).split()]
        if len(nums) == 11:      endQ = nums[3]
        elif 8 <= len(nums) <= 9: endQ = nums[2]
        else:                    continue
        tick = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            t = lines[j].strip()
            if re.fullmatch(r"[A-Z0-9]{1,6}", t):
                tick = t; break
        if not tick:
            continue
        mkt = "SG" if exch == "SGX" else ("HK" if exch in ("HK", "SEHK") else "US")
        out.append(dict(month=ym, ticker=tick, market=mkt, currency=ccy, endQ=endQ))
    return out

def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(DATA, "moomoo", "moomoo_*.pdf"))):
        rows += parse(f)
    months = sorted(set(r["month"] for r in rows))
    # endQ per (month, ticker); take max abs if a ticker appears twice in a month
    snap = {}
    mkt = {}
    for r in rows:
        snap[(r["month"], r["ticker"])] = r["endQ"]
        mkt[r["ticker"]] = r["market"]
    tickers = sorted(set(t for _, t in snap))
    # forward-fill each ticker across months, diff consecutive -> share-change events
    ev = []
    for t in tickers:
        prev = 0.0
        last_seen = None
        for mo in months:
            if (mo, t) in snap:
                cur = snap[(mo, t)]
                d = cur - prev
                if abs(d) > 1e-9 and last_seen is not None:  # change vs prior known month
                    ev.append(dict(date=mo + "-28", account="Moomoo", market=mkt[t],
                                   ticker=t, asset_type="stock",
                                   action=("buy" if d > 0 else "sell/transfer"),
                                   qty_signed=d, source="moomoo (pdf snapshot-diff)", raw=mo))
                elif abs(cur) > 1e-9 and last_seen is None:  # first appearance
                    ev.append(dict(date=mo + "-28", account="Moomoo", market=mkt[t],
                                   ticker=t, asset_type="stock", action="open/transfer_in",
                                   qty_signed=cur, source="moomoo (pdf snapshot-diff)", raw=mo))
                prev = cur; last_seen = mo
    print(f"moomoo statements: {len(months)} ({months[0]}..{months[-1]}), tickers: {tickers}")
    print("\n=== Moomoo timeline (snapshot-diff) ===")
    for e in ev:
        print(f"  {e['date']}  {e['ticker']:5} {e['action']:16} {e['qty_signed']:>+10.4f}")
    print("\n=== latest statement ending position vs Holdings.md ===")
    HOLD = {"9CI": 6912, "C38U": 1175, "HMN": 136.94, "AAPL": 1}
    for t in sorted(set(list(HOLD) + tickers)):
        last = max((m for (m, tk) in snap if tk == t), default=None)
        end = snap.get((last, t)) if last else 0.0
        h = HOLD.get(t)
        flag = "" if (h is not None and abs((h or 0) - (end or 0)) < 1e-6) else "  <-- GAP"
        print(f"  {t:5} last-stmt({last})={end!s:>10}  Holdings={h}{flag}")
    out = os.path.join(os.path.dirname(__file__), "moomoo_events.csv")
    cols = ["date","account","market","ticker","asset_type","action","qty_signed","source","raw"]
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for e in ev: w.writerow(e)
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
