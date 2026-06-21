#!/usr/bin/env python3
"""Parse Endowus monthly statements -> fund unit transactions (CPF fund: Amundi Prime USA).

Each statement has a Transactions section:
  Trade date | Transaction type | Details (Buy/Sell <fund>) | Funding Source | Units | Price | Amount
  e.g. 09 Apr 2025  Investment   Buy Amundi Prime USA Fund   CPF OA   16.62603  S$180.44  S$3,000.00
       15 Apr 2025  Endowus Fee  Sell Amundi Prime USA Fund  CPF OA    0.35376  S$174.36     S$61.68
Buy -> +units, Sell -> -units. Dedup across statements (each txn shown once, but be safe).
Also reads the latest holdings snapshot (units) to verify.
"""
import glob, os, re, subprocess, csv
from datetime import datetime

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "endowus statement")
MONEY = r"S\$([\d,]+\.\d+)"
# date  type            Buy|Sell  <fund name>           funding         units      price        amount
TXN = re.compile(
    r"(\d{1,2} \w{3} \d{4})\s+(Investment|Endowus Fee|Rebalancing|Redemption|Subscription)\s+"
    r"(Buy|Sell)\s+(.+?)\s+(CPF OA|SRS|Cash|CPF SA)\s+([\d,]+\.\d+)\s+" + MONEY + r"\s+" + MONEY)

def f(s): return float(s.replace(",", ""))
def iso(d): return datetime.strptime(d, "%d %b %Y").date().isoformat()

def holdings(path):
    """fund unit snapshot from the asset-allocation table (handles 'Equity'/'Equity Fund')."""
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    out = {}
    for m in re.finditer(r"(.+?Fund)\s+Equity(?:\s+Fund)?\s+(CPF OA|CPF SA|SRS|Cash)\s+([\d,]+\.\d+)\s+S\$", txt):
        out[(re.sub(r"\s+", " ", m.group(1)).strip(), m.group(2))] = f(m.group(3))
    return out

def txn_types(path):
    """map date -> transaction type (Investment / Endowus Fee / Redemption) for labelling."""
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    out = {}
    for m in TXN.finditer(txt):                 # later-format rows
        out[iso(m.group(1))] = m.group(2)
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})\s+(Investment|Endowus Fee|Redemption|Subscription)", txt):
        out[datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()] = m.group(2)
    return out

def main():
    files = sorted(glob.glob(os.path.join(DATA, "endowus_*.pdf")))
    # snapshot-diff units per (fund, src) across months — robust to statement-format changes
    snaps = {}; types = {}
    for path in files:
        mo = re.search(r"(\d{6})", path).group(1); ym = f"{mo[:4]}-{mo[4:]}"
        h = holdings(path)
        if h: snaps[ym] = h
        types.update(txn_types(path))
    months = sorted(snaps)
    keys = sorted({k for h in snaps.values() for k in h})
    ev = []
    for k in keys:
        prev = 0.0; seen = False
        for mo in months:
            if k in snaps[mo]:
                cur = snaps[mo][k]; d = cur - prev
                date = mo + "-15"
                if not seen and cur:
                    ev.append((date, k, "subscription", cur))
                elif abs(d) > 1e-9:
                    # label from the txn-type table when a transaction fell in this month
                    tt = next((t for dd, t in types.items() if dd[:7] == mo), None)
                    act = "fee" if (tt == "Endowus Fee" or d < 0) else "buy"
                    ev.append((date, k, act, d))
                prev = cur; seen = True
    net = {}
    for _, k, _, q in ev: net[k] = net.get(k, 0) + q
    print(f"Endowus statements: {len(months)} ({months[0]}..{months[-1]})")
    print("\n=== fund units: reconstructed vs latest statement ===")
    last = snaps[months[-1]]
    for k in keys:
        print(f"  {k[1]:6} {k[0]:24} reconstructed={net.get(k,0):>12.5f}   latest-stmt={last.get(k,'?')}")
    print("\n=== transaction timeline ===")
    for date, k, act, q in ev:
        print(f"  {date}  {k[1]:6} {act:12} {q:>+11.5f}")
    out = os.path.join(os.path.dirname(__file__), "endowus_events.csv")
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "src", "fund", "action", "qty_signed"])
        for date, k, act, q in ev: w.writerow([date, k[1], k[0], act, q])
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
