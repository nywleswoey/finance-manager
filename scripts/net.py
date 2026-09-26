"""Per-ticker net verdict: is a name +ve or -ve once dividends and option premiums count?

Prints the fold's own Net per canonical ticker (all SGD, latest FX) — `net_pl_sgd` summed over
the ticker's legs, flagged by its `net_verdict` — beside the three components it is the sum of:

  STOCK  realised + unrealised stock P/L   (stock_pl_sgd; dividends NOT included)
  DIV    cash dividends received           (income_sgd)
  PREM   realised options P/L on that name (options_pl_sgd)

so NET == STOCK + DIV + PREM on every line. What a Net may claim is `performance.net_verdict`'s
rule, read here rather than re-derived:

  (blank)  hero     every entering unit has a known cost
  ~        caveat   some units' cost is unknown: read as free, so the Net is a ceiling
  b        bounded  a split corporate-action carry mis-attributes the cost (#143 §12)
  !        refuse   no unit's cost is known — there is no Net, and NET/STOCK print n/a

Option underlyings never held as stock have no row and are not listed (they are
/api/performance's named residual).

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

FLAG = {"hero": " ", "caveat": "~", "bounded": "b", "refuse": "!"}


def main(argv):
    held_only = "--held" in argv
    wanted = {a.upper() for a in argv if not a.startswith("-")}

    agg = defaultdict(lambda: {"name": "", "units": 0.0, "verdict": "hero",
                               "net": 0.0, "stock": 0.0, "div": 0.0, "prem": 0.0})
    for r in compute():
        a = agg[r["ticker"]]
        a["name"] = r["name"]
        a["verdict"] = r["net_verdict"]          # whole-ticker: identical on every leg
        a["units"] += r["units"] or 0.0
        a["div"] += r["income_sgd"] or 0.0
        a["prem"] += r["options_pl_sgd"] or 0.0
        if r["net_verdict"] != "refuse":         # every other verdict nets every leg
            a["net"] += r["net_pl_sgd"]
            a["stock"] += r["stock_pl_sgd"]

    out = [(tk, a) for tk, a in agg.items()
           if (not wanted or tk in wanted) and not (held_only and abs(a["units"]) < 1e-6)]
    # refusals last: they have no Net to sort by
    out.sort(key=lambda x: (x[1]["verdict"] == "refuse", -x[1]["net"]))

    print(f"{'TICKER':<8}{'NET S$':>12}  {'STOCK':>11}{'DIV':>10}{'PREM':>11}  {'':2}NAME")
    print("-" * 92)
    pos_sum = neg_sum = 0.0
    for tk, a in out:
        if a["verdict"] == "refuse":
            net, stock = f"{'n/a':>12}", f"{'n/a':>11}"
        else:
            net = f"{a['net']:>11,.0f}{'+' if a['net'] >= 0 else '-'}"
            stock = f"{a['stock']:>11,.0f}"
            pos_sum += max(a["net"], 0.0)
            neg_sum += min(a["net"], 0.0)
        print(f"{tk:<8}{net} {stock}{a['div']:>10,.0f}{a['prem']:>11,.0f}  "
              f"{FLAG.get(a['verdict'], '?')} {a['name'][:34]}")
    print("-" * 92)
    print(f"{len(out)} tickers   winners +S${pos_sum:,.0f}   losers -S${abs(neg_sum):,.0f}"
          f"   net S${pos_sum + neg_sum:,.0f}")
    print("~ caveat (unknown-cost units read as free: a ceiling)   b bounded (split carry)   "
          "! refuse (no Net)")


if __name__ == "__main__":
    main(sys.argv[1:])
