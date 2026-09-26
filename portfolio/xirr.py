"""Money-weighted return: the one XIRR solver both return engines use.

`performance.py` (per position, native currency) and `twr.py` (portfolio-wide, SGD) are
deliberately separate engines (ADR 0001); this is the piece they share. It used to be a private
of `performance.py` that `twr.py` imported anyway — ADR 0001's Consequences, step 1.
"""


def xirr(flows, guess=0.1):
    """flows: list[(date, amount)]; amount<0 out, >0 in. Returns annualised rate or None."""
    flows = [(d, float(a)) for d, a in flows if abs(a) > 1e-9]
    if len(flows) < 2 or not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = min(d for d, _ in flows)
    yrs = [((d - t0).days / 365.0, a) for d, a in flows]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in yrs)

    def dnpv(r):
        return sum(-t * a / (1 + r) ** (t + 1) for t, a in yrs)

    r = guess
    for _ in range(100):                       # Newton
        f = npv(r)
        if abs(f) < 1e-7:
            return r
        d = dnpv(r)
        if abs(d) < 1e-12:
            break
        r -= f / d
        if r <= -0.9999:
            r = -0.99
    lo, hi = -0.9999, 10.0                      # bisection fallback
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2
