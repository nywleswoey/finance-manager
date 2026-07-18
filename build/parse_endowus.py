#!/usr/bin/env python3
"""Parse Endowus monthly statements -> fund unit transactions WITH cost (CPF fund: Amundi Prime USA).

Each statement has a Transactions section. Two layouts seen:
  later ("DD Mon YYYY"):
    09 Apr 2025  Investment   Buy Amundi Prime USA Fund   CPF OA   16.62603  S$180.44  S$3,000.00
    15 Jul 2025  Endowus Fee  Sell Amundi Prime USA Fund  CPF OA    0.30560  S$198.66     S$60.71
  earlier ("DD/MM/YYYY", no funding column, amount printed twice):
    27/04/2023 Investment  Amundi Prime USA  393.2710  S$131.85  S$51,852.90 S$51,852.90
    26/07/2023 Redemption   Amundi Prime USA   0.2850  S$145.62      S$41.47    S$41.47

We emit price + amount (the cost the snapshot-diff approach threw away) so the fund
gets a real cost basis. Action mapping:
  Investment / Buy   -> buy        (cash in; cost booked)
  Redemption / Sell  -> fee        (Amundi redemptions here are trailer-fee deductions)
  Endowus Fee        -> fee
A switch-IN (Amundi Investment whose amount equals a same-period redemption of ANOTHER
fund — the 2023 LionGlobal Infinity -> Amundi switch) is emitted as `switch_in` with NO
price/amount: it is internal, not new capital. Its cost carries from the predecessor via
the `switch` corporate_action (see performance.py / seed.py), so booking it here would
double-count. Infinity itself stays in cpf-stocks/transactions.csv (authoritative cost).
"""
import glob, os, re
from datetime import datetime

from _pdf import raw_text
from _csvout import write_rows

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "endowus statement")
FUND = "Amundi"                     # the fund Endowus is authoritative for (others come from cpf-stocks)
M = r"S\$([\d,]+\.\d+)"            # money

# later format: date  type  Buy|Sell  <fund>  <funding>  units  price  amount
TXN_A = re.compile(
    r"(\d{1,2} \w{3} \d{4})\s+(Investment|Endowus Fee|Rebalancing|Redemption|Subscription)\s+"
    r"(Buy|Sell)\s+(.+?)\s+(?:CPF OA|SRS|Cash|CPF SA)\s+([\d,]+\.\d+)\s+" + M + r"\s+" + M)
# earlier format: date  type  <fund>  units  price  amount [amount]
TXN_B = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s+(Investment|Endowus Fee|Redemption|Subscription)\s+"
    r"(.+?)\s+([\d,]+\.\d+)\s+" + M + r"\s+" + M)

def f(s): return float(s.replace(",", ""))
def isoA(d): return datetime.strptime(d, "%d %b %Y").date().isoformat()
def isoB(d): return datetime.strptime(d, "%d/%m/%Y").date().isoformat()

def text_of(path):
    return raw_text(path)

def holdings(path):
    """fund unit snapshot from the asset-allocation table — used only to sanity-check units."""
    out = {}
    for m in re.finditer(r"(.+?Fund)\s+Equity(?:\s+Fund)?\s+(CPF OA|CPF SA|SRS|Cash)\s+([\d,]+\.\d+)\s+S\$", text_of(path)):
        out[(re.sub(r"\s+", " ", m.group(1)).strip(), m.group(2))] = f(m.group(3))
    return out

def parse_txns(txt):
    """All transactions in one statement: list of (date, type, fund, units, price, amount).
    units signed (Buy/Investment +, Sell/Redemption -). Funding source not tracked here (CPF OA assumed)."""
    rows = []
    for m in TXN_A.finditer(txt):
        date, typ, side, fund, units, price, amt = m.groups()
        q = f(units) * (1 if side == "Buy" else -1)
        rows.append((isoA(date), typ, re.sub(r"\s+", " ", fund).strip(), q, f(price), f(amt)))
    for m in TXN_B.finditer(txt):
        date, typ, fund, units, price, amt = m.groups()
        q = f(units) * (-1 if typ in ("Redemption", "Endowus Fee") else 1)
        rows.append((isoB(date), typ, re.sub(r"\s+", " ", fund).strip(), q, f(price), f(amt)))
    return rows

def main():
    files = sorted(glob.glob(os.path.join(DATA, "endowus_*.pdf")))
    allrows, snaps = [], {}
    for path in files:
        txt = text_of(path)
        allrows += parse_txns(txt)
        h = holdings(path)
        if h:
            mo = re.search(r"(\d{6})", path).group(1); snaps[f"{mo[:4]}-{mo[4:]}"] = h
    # dedup identical (date, type, fund, qty, amount) across statements
    seen, rows = set(), []
    for r in allrows:
        k = (r[0], r[1], r[2], round(r[3], 5), round(r[5], 2))
        if k not in seen:
            seen.add(k); rows.append(r)
    rows.sort()

    # switch-IN detection: an Amundi Investment whose amount matches a same-period (same month)
    # redemption of a DIFFERENT fund => it was funded by a switch, not new capital.
    redemptions = {}            # month -> set of redemption amounts of non-target funds (material)
    for date, typ, fund, q, price, amt in rows:
        if typ in ("Redemption",) and FUND not in fund and amt > 1000:
            redemptions.setdefault(date[:7], set()).add(round(amt, 2))

    ev = []                     # (date, fund, action, qty_signed, price, amount)
    for date, typ, fund, q, price, amt in rows:
        if FUND not in fund:
            continue            # only Amundi; other funds (Infinity) come from cpf-stocks
        if typ in ("Endowus Fee", "Redemption"):
            act = "fee"
        elif round(amt, 2) in redemptions.get(date[:7], set()):
            act = "switch_in"   # internal; cost carries from predecessor via corporate_action
        else:
            act = "buy"
        ev.append((date, fund, act, q, ("" if act == "switch_in" else price),
                   ("" if act == "switch_in" else amt)))

    print(f"Endowus statements: {len(files)}")
    print("\n=== transaction timeline (Amundi) ===")
    for date, fund, act, q, price, amt in ev:
        print(f"  {date}  {act:10} {q:>+12.5f}  price={price or '-':>8}  amt={amt or '-':>10}")
    net = sum(q for _, _, _, q, _, _ in ev)
    last = max((mo for mo in snaps), default=None)
    stmt_units = next(iter(snaps[last].values())) if last else "?"
    print(f"\nreconstructed units={net:.5f}   latest-stmt units={stmt_units}  (as of {last})")
    invested = sum(amt for _, _, act, _, _, amt in ev if act == "buy")
    print(f"external cash booked (buys only): S${invested:,.2f}  (switch-in excluded)")

    out = os.path.join(os.path.dirname(__file__), "endowus_events.csv")
    write_rows(out, ["date", "src", "fund", "action", "qty_signed", "price", "amount"],
               [[date, "CPF OA", fund, act, q, price, amt] for date, fund, act, q, price, amt in ev])
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
