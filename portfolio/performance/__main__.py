"""__main__"""
from __future__ import annotations

from .book import compute, rollup

if __name__ == "__main__":
    rows = compute()
    held = [r for r in rows if r["units"] > 1e-6]
    tot_mv = sum(r["mv_sgd"] for r in held)
    tot_inc = sum(r["income_sgd"] for r in held)
    netted = [r for r in rows if r["net_pl_sgd"] is not None]
    tot_net = sum(r["net_pl_sgd"] for r in netted)
    n_refused = len({r["ticker"] for r in rows if r["net_verdict"] == "refuse"})
    print(f"held positions: {len(held)}")
    print(f"portfolio MV:  SGD {tot_mv:,.0f}")
    print(f"dividends:     SGD {tot_inc:,.0f}  (held only)")
    print(f"Net (closed legs + options incl.; {n_refused} refused name(s) omitted): "
          f"SGD {tot_net:,.0f}")
    print("\nby market:", rollup(held, "market"))
    print("\ntop holdings by MV:")
    for r in sorted(held, key=lambda r: -r["mv_sgd"])[:8]:
        xs = f"{r['xirr']*100:.1f}%" if r["xirr"] is not None else "  - "
        print(f"  {r['name'][:22]:22} {r['ticker']:6} {r['currency']} mv_sgd={r['mv_sgd']:>10,.0f} "
              f"xirr={xs:>7} div={r['income_native']:>9,.0f}")
