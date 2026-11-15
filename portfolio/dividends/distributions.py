"""One distribution seen across brokers: `distinct_distributions` merges the same ticker/rate/date
paid by two accounts into one, `_payments` lists what was actually received, and `_anniversary`
rolls a date a year forward — the primitive projection and yields share."""
from collections import defaultdict

from .attribution import details

SAME_DISTRIBUTION_DAYS = 15  # `distinct_distributions()`'s fallback for a row with no ex_date:
                              # a pay date this close to another account's row of the same ticker,
                              # at the same per-unit rate, is that same distribution settled by a
                              # different broker on its own schedule (C38U: Moomoo and FSM a week
                              # or two apart). Never applied within one account - two close,
                              # equal-rate rows in one account are two distributions.


def _rate_matches(a, b, tol=1e-4):
    """Same per-unit rate up to float/rounding noise."""
    return abs(a - b) <= max(tol, 0.01 * max(abs(a), abs(b)))


def distinct_distributions(ticker, s=None):
    """One entry per distribution of `ticker` - `{ex_date, pay_date, rate, currency}`, oldest
    first - counted ONCE however many accounts received it: the per-unit view the dividend-yield
    columns read. Received cash stays per row in `annual()` / `details()`.

    Rows sharing an ex_date are one distribution. Per account its statement lines are summed
    (component lines 0.60 + 0.15 make the 0.75 rate) and across accounts the largest per-account
    rate is the distribution's - every account was paid the same per-unit rate on its own units.
    A row with no ex_date joins the distribution of a DIFFERENT account within
    SAME_DISTRIBUTION_DAYS of its pay_date at a matching rate, else it stands alone. Rows with
    no rate (nothing to compare or count) are left out."""
    return _distributions([r for r in details(s)["rows"] if r["ticker"] == ticker])


def _distributions(rows):
    """`distinct_distributions()` over one ticker's already-fetched `details()` rows."""
    rows = [r for r in rows if r["rate"] is not None and r["pay_date"] is not None]
    groups = {}
    for r in sorted(rows, key=lambda r: (r["ex_date"] is None, r["pay_date"])):
        key = ("ex", r["ex_date"]) if r["ex_date"] else ("pay", r["pay_date"])
        g = groups.setdefault(key, {"ex_date": r["ex_date"], "pay_date": r["pay_date"],
                                    "currency": r["currency"], "rates": defaultdict(float)})
        g["rates"][r["account"]] += r["rate"]
    for key in sorted(k for k in groups if k[0] == "pay"):
        g = groups[key]
        rate = max(g["rates"].values())
        for other in groups.values():
            if other is not g and other["pay_date"] is not None \
                    and abs((other["pay_date"] - g["pay_date"]).days) <= SAME_DISTRIBUTION_DAYS \
                    and _rate_matches(rate, max(other["rates"].values())) \
                    and other["rates"].keys().isdisjoint(g["rates"]):
                other["rates"].update(g["rates"])
                del groups[key]
                break
    return [{"ex_date": g["ex_date"], "pay_date": g["pay_date"], "currency": g["currency"],
             "rate": round(max(g["rates"].values()), 6)}
            for g in sorted(groups.values(), key=lambda g: g["ex_date"] or g["pay_date"])]


def _payments(rows):
    """One entry per distinct payment (one ticker's rows), oldest first, keyed on pay_date.

    `details()` returns a row per (account, statement line): a statement may split one
    distribution into component lines (0.60 + 0.15) that sum to the rate, while another account
    holding the same distribution carries the combined declared rate (0.75). So per account the
    lines are summed, and across accounts the largest per-account rate is the payment's rate."""
    per_account = defaultdict(float)
    first = {}
    for r in rows:
        per_account[(r["pay_date"], r.get("account"))] += r["rate"]
        first.setdefault(r["pay_date"], r)
    rate = defaultdict(float)
    for (d, _), v in per_account.items():
        rate[d] = max(rate[d], v)
    return [{**first[d], "rate": round(rate[d], 6)} for d in sorted(first)]


def _anniversary(d, year):
    """`d` moved to `year`, Feb 29 -> Feb 28 on a non-leap target."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


DRIFT_DAYS = 45   # how far a payment's date may drift from last year's and still be the same payment
