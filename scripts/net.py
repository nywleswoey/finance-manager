"""Per-ticker net verdict: is a name +ve or -ve once dividends and option premiums count?

Folds three income streams into ONE number per canonical ticker (all SGD, latest FX):
  stock P/L   = realised + unrealised  (performance.compute -> pl_sgd; needs cost)
  dividends   = cash dividends received (income_sgd; included in pl_sgd when cost known)
  premiums    = realised options P/L on that underlying (options_pl_sgd)

net_sgd = stock P/L (incl. dividends) + option premiums.

Cost-unknown positions (CDP/transferred-in names with no purchase price) can't give a true
stock P/L — for those `net` shows only the KNOWN cash streams (dividends + premiums) and is
flagged with `~` so you don't read a partial number as the full story.

Usage:
  make net                 # all tickers, sorted by net
  .venv/bin/python scripts/net.py            # same
  .venv/bin/python scripts/net.py D05 O5RU   # only these tickers
  .venv/bin/python scripts/net.py --held     # only currently-held (units != 0)
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from portfolio.performance import compute


def main(argv):
    held_only = "--held" in argv
    wanted = {a.upper() for a in argv if not a.startswith("-")}

    rows = compute()

    agg = defaultdict(lambda: {
        "name": "", "market": "", "units": 0.0,
        "stock_pl": 0.0, "div": 0.0, "prem": 0.0,
        "cost_known": True, "has_stock_pl": False,
    })
    for r in rows:
        tk = r["ticker"]
        a = agg[tk]
        a["name"] = r["name"]
        a["market"] = r["market"]
        a["units"] += r["units"] or 0.0
        a["div"] += r["income_sgd"] or 0.0
        a["prem"] += r.get("options_pl_sgd") or 0.0
        if r["cost_known"] and r["pl_sgd"] is not None:
            a["stock_pl"] += r["pl_sgd"]      # already includes that bucket's dividends
            a["has_stock_pl"] = True
        else:
            a["cost_known"] = False

    # options-only underlyings (no stock row at all) still appear via compute()'s cash rows,
    # but a fully-closed name with no current position may not — pull any stragglers in.
    out = []
    for tk, a in agg.items():
        if wanted and tk not in wanted:
            continue
        if held_only and abs(a["units"]) < 1e-6:
            continue
        # net: when stock P/L known it already carries dividends; else only cash streams known
        if a["has_stock_pl"] and a["cost_known"]:
            net = a["stock_pl"] + a["prem"]
            partial = False
        else:
            net = a["div"] + a["prem"] + (a["stock_pl"] if a["has_stock_pl"] else 0.0)
            partial = True
        out.append((tk, a, net, partial))

    out.sort(key=lambda x: x[2], reverse=True)

    print(f"{'TICKER':<8}{'NET S$':>12}  {'STOCK':>11}{'DIV':>10}{'PREM':>11}  {'':2}NAME")
    print("-" * 92)
    pos_sum = neg_sum = 0.0
    for tk, a, net, partial in out:
        sign = "+" if net >= 0 else "-"
        flag = "~" if partial else " "
        stock = f"{a['stock_pl']:>11,.0f}" if a["has_stock_pl"] else f"{'n/a':>11}"
        print(f"{tk:<8}{net:>11,.0f}{sign} {stock}{a['div']:>10,.0f}"
              f"{a['prem']:>11,.0f}  {flag} {a['name'][:34]}")
        pos_sum += net if net >= 0 else 0
        neg_sum += net if net < 0 else 0
    print("-" * 92)
    print(f"{len(out)} tickers   winners +S${pos_sum:,.0f}   losers -S${abs(neg_sum):,.0f}"
          f"   net S${pos_sum + neg_sum:,.0f}")
    print("~ = cost basis unknown (CDP / transferred-in): net shows known cash streams only")


if __name__ == "__main__":
    main(sys.argv[1:])
