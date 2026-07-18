#!/usr/bin/env python3
"""Parse Moomoo monthly PDF statements -> normalized share-movement events.

Each statement has a per-symbol table:
  <full name>
  <EXCH> <CCY> startQ startP startV endQ endP endV deltaV BuyQ SellQ TransferIn TransferOut
  <TICKER>
We emit buy/sell/transfer events from BuyQ/SellQ/TransferIn/TransferOut and also
record the ending quantity per symbol per month (to confirm current positions).
"""
import glob, os, re, csv, subprocess

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

TRADE = re.compile(
    r"^\s*(Buy to Open|Sell to Close|Buy to Close|Sell to Open)\s+(SGX|US|HK|SEHK|NYSE|NASDAQ)\s+"
    r"([A-Z]{3})\s+([\d,]+\.\d+)\s+([\d,]+)\s+([\d,]+\.\d+)")

def trades(path):
    """priced trades from the Moomoo 'Transaction Details' section -> per (ym,ticker) totals."""
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    lines = txt.splitlines()
    out = []
    for i, ln in enumerate(lines):
        m = TRADE.match(ln)
        if not m:
            continue
        direction, _, _, price, qty, amount = m.groups()
        tk = ""
        for j in range(i - 2, i + 4):                 # ticker = first token of the time-bearing line
            if 0 <= j < len(lines) and re.search(r"\d\d:\d\d:\d\d", lines[j]):
                first = lines[j].split()[0] if lines[j].split() else ""
                if re.fullmatch(r"[A-Z0-9]{2,6}", first):
                    tk = first
        ym = re.search(r"(\d{6})", path).group(1)
        out.append({"ym": f"{ym[:4]}-{ym[4:]}", "ticker": tk,
                    "qty": f2(qty), "price": f2(price), "amount": f2(amount),
                    "buy": direction.startswith("Buy")})
    return out

def main():
    rows = []
    trade_idx = {}                                    # (ym, ticker) -> {qty, amount, avg_price}
    for f in sorted(glob.glob(os.path.join(DATA, "moomoo", "moomoo_*.pdf"))):
        rows += parse(f)
        for t in trades(f):
            k = (t["ym"], t["ticker"])
            g = trade_idx.setdefault(k, {"qty": 0.0, "amount": 0.0})
            g["qty"] += t["qty"]; g["amount"] += t["amount"]
    for g in trade_idx.values():
        g["avg_price"] = round(g["amount"] / g["qty"], 4) if g["qty"] else None
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
                tr = trade_idx.get((mo, t))           # priced trade this month?
                px = tr["avg_price"] if (tr and abs(abs(tr["qty"]) - abs(d if last_seen else cur)) < 1e-6) else ""
                amt = tr["amount"] if px != "" else ""
                src = "moomoo (trade detail)" if px != "" else "moomoo (pdf snapshot-diff)"
                if abs(d) > 1e-9 and last_seen is not None:  # change vs prior known month
                    ev.append(dict(date=mo + "-28", account="Moomoo", market=mkt[t],
                                   ticker=t, asset_type="stock",
                                   action=("buy" if d > 0 else "sell/transfer"),
                                   qty_signed=d, price=px, amount=amt, source=src, raw=mo))
                elif abs(cur) > 1e-9 and last_seen is None:  # first appearance
                    ev.append(dict(date=mo + "-28", account="Moomoo", market=mkt[t],
                                   ticker=t, asset_type="stock",
                                   action=("buy" if px != "" else "open/transfer_in"),
                                   qty_signed=cur, price=px, amount=amt, source=src, raw=mo))
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
    cols = ["date","account","market","ticker","asset_type","action","qty_signed","price","amount","source","raw"]
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for e in ev: w.writerow(e)
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
