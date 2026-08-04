"""Spending analytics over the cash-flow ledger (`cash_txn`).

All amounts are SGD. "Spend" is the positive magnitude of counted outflows (-amount_sgd
where is_spend); excluded rows (transfers, card-bill payments, income) are filtered out of
every spend metric but remain inspectable via transactions(include_excluded=True).

Every public function accepts an optional Session (`s`) and routes through
db.session_scope, so it composes inside a larger unit of work or opens its own connection.
The six read shapes share a single WHERE builder (`_where`) rather than each re-deriving
the same is_spend / date / category filters.

Note: summary() and trends() bucket by month with Postgres `to_char`, so their SQL is
Postgres-only; transactions(), categories(), years() and undated() are portable (covered by
tests/test_spending.py). trends() keeps its payload-shaping in `_trend_shape`, which is not
Postgres-anything and is tested directly — that fold is where unclassified spend gets its
name, and where it used to raise.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_spending.py -q
"""
from sqlalchemy import text

from .db import session_scope


def _where(*, spend_only=True, frm=None, to=None, group=None, subcategory=None, source=None):
    """The WHERE clause + bind params shared by every spending query.

    spend_only restricts to counted outflows (is_spend); the transactions view widens it to
    include excluded rows. Date / category / subcategory / source filters are all optional."""
    w, p = [], {}
    if spend_only:
        w.append("is_spend")
    if frm:
        w.append("txn_date >= :frm"); p["frm"] = frm
    if to:
        w.append("txn_date <= :to"); p["to"] = to
    if group:
        w.append("category = :g"); p["g"] = group
    if subcategory:
        w.append("subcategory = :sub"); p["sub"] = subcategory
    if source:
        w.append("source = :src"); p["src"] = source
    return (" AND ".join(w) or "1=1"), p


def _rows(s, sql, p):
    """Run a text() query and return its rows as plain dicts (materialized before the
    session closes)."""
    return [dict(r) for r in s.execute(text(sql), p).mappings().all()]


def summary(frm=None, to=None, s=None):
    """Totals + category / subcategory / month breakdowns for the spend window."""
    where, p = _where(frm=frm, to=to)
    with session_scope(s) as s:
        total = s.execute(
            text(f"SELECT COALESCE(SUM(-amount_sgd),0) FROM cash_txn WHERE {where}"), p).scalar()
        by_group = _rows(s,
            f"SELECT category, ROUND(SUM(-amount_sgd),2) v, COUNT(*) n FROM cash_txn "
            f"WHERE {where} GROUP BY category ORDER BY v DESC", p)
        by_sub = _rows(s,
            f"SELECT category, subcategory, ROUND(SUM(-amount_sgd),2) v, COUNT(*) n FROM cash_txn "
            f"WHERE {where} GROUP BY category, subcategory ORDER BY v DESC", p)
        by_month = _rows(s,
            f"SELECT to_char(txn_date,'YYYY-MM') ym, ROUND(SUM(-amount_sgd),2) v FROM cash_txn "
            f"WHERE {where} GROUP BY ym ORDER BY ym", p)
    months = len(by_month) or 1
    return {
        "total_sgd": round(float(total), 2),
        "avg_month_sgd": round(float(total) / months, 2),
        "months": months,
        "by_group": by_group,
        "by_subcategory": by_sub,
        "by_month": by_month,
    }


#: What unclassified spend (`category IS NULL`) is called in the trends payload. The word
#: is also `catName` in `web/src/api.js`, which names the same rows wherever the null
#: reaches the frontend as a *value* — one name for one thing, on both sides of the wire
#: because only one of them can defer (see `_trend_shape`). Change it here, change it there.
#: `CONTEXT.md`'s Spending glossary is where the term itself is pinned.
UNCLASSIFIED = "Uncategorized"


def _trend_shape(rows):
    """Fold `(ym, category, v)` rows into the stacked-series payload.

    Split out of trends() because the query around it is Postgres-only (`to_char`) and this
    is not, and because this is where the null category is decided — see
    tests/test_spending.py::TestTrendShape, which is the only coverage the endpoint has.

    THE NULL GROUP IS NAMED HERE, WHICH IS WHERE summary() AND trends() PART. summary()
    leaves it null, and can: its `category` is a *value* on a by_group record, so the
    frontend is free to name it at the point of render. These group strings are the *keys*
    of every series row — the frontend feeds each one straight into `<Bar dataKey={g}>` —
    and JSON has no null key, so a `None` here does not survive as a null anyway: it
    serializes to the string "null". The group ends up named either way; naming it
    deliberately is the difference between "Uncategorized" and that.

    It sorts last rather than alphabetically among the real categories, so the unclassified
    band sits at the top of the stack and reads as the residue it is. A real category
    literally named "Uncategorized" would merge into that band and sort with it; the
    classifier does not produce one, and a stack cannot draw two bands under one dataKey
    anyway, so this is the honest failure rather than a silent one to guard against.

    Summing rather than assigning: NULL and '' are distinct GROUP BY keys in SQL and both
    fold to UNCLASSIFIED here, so one month can arrive as two rows for one group. Assignment
    would silently keep the later one and the stack would stop reconciling with summary().
    """
    def name(category):
        return category or UNCLASSIFIED

    groups = sorted({name(r["category"]) for r in rows},
                    key=lambda g: (g == UNCLASSIFIED, g))
    series: dict[str, dict] = {}
    for r in rows:
        m = series.setdefault(r["ym"], {"ym": r["ym"]})
        g = name(r["category"])
        m[g] = m.get(g, 0) + float(r["v"])
    # Every group as a key on every month, zero where absent: a stacked chart reads one
    # dataKey across the whole series, and a missing key is a gap in the stack.
    out = [{**{g: 0 for g in groups}, **m} for m in series.values()]
    return {"groups": groups, "series": sorted(out, key=lambda x: x["ym"])}


def trends(frm=None, to=None, s=None):
    """Monthly spend split by group — a stacked time series (one key per group)."""
    where, p = _where(frm=frm, to=to)
    with session_scope(s) as s:
        rows = s.execute(text(
            f"SELECT to_char(txn_date,'YYYY-MM') ym, category, ROUND(SUM(-amount_sgd),2) v "
            f"FROM cash_txn WHERE {where} GROUP BY ym, category ORDER BY ym"), p).mappings().all()
    return _trend_shape(rows)


def transactions(frm=None, to=None, group=None, subcategory=None, source=None,
                 include_excluded=False, limit=500, s=None):
    """Raw ledger lines for the filter set, newest first. include_excluded widens past the
    is_spend filter to surface transfers / card-bill payments / income."""
    where, p = _where(spend_only=not include_excluded, frm=frm, to=to, group=group,
                      subcategory=subcategory, source=source)
    p["lim"] = min(limit, 2000)
    with session_scope(s) as s:
        return _rows(s,
            f"SELECT txn_date, source, account_label, merchant, description, amount_sgd, "
            f"direction, is_spend, exclude_reason, category, subcategory "
            f"FROM cash_txn WHERE {where} "
            f"ORDER BY txn_date DESC, id DESC LIMIT :lim", p)


def years(s=None):
    """Calendar years spanned by counted spend, newest first — drives the year selector.
    Portable (MIN/MAX only, no date-formatting SQL): returns the contiguous range from the
    earliest to the latest spend date, so a gap year still selectable (shows zero, harmless)."""
    where, p = _where()
    with session_scope(s) as s:
        lo, hi = s.execute(
            text(f"SELECT MIN(txn_date), MAX(txn_date) FROM cash_txn WHERE {where}"), p).one()
    if not lo or not hi:
        return []
    lo_y = lo.year if hasattr(lo, "year") else int(str(lo)[:4])
    hi_y = hi.year if hasattr(hi, "year") else int(str(hi)[:4])
    return list(range(hi_y, lo_y - 1, -1))


def undated(s=None):
    """Counted spend carrying no txn_date: {"n": lines, "total_sgd": magnitude}.

    txn_date is nullable, and every date-windowed view drops those rows — years() cannot see
    them and no `txn_date >= :frm AND txn_date <= :to` window matches them — so per-year totals
    undershoot the all-time total by exactly this amount. Callers surface it so the gap is
    visible rather than silent. Portable (no date-formatting SQL)."""
    where, p = _where()
    with session_scope(s) as s:
        n, total = s.execute(text(
            f"SELECT COUNT(*), COALESCE(SUM(-amount_sgd),0) FROM cash_txn "
            f"WHERE {where} AND txn_date IS NULL"), p).one()
    return {"n": int(n), "total_sgd": round(float(total), 2)}


def categories(s=None):
    """Every (category, subcategory) with its counted spend and line count."""
    where, p = _where()
    with session_scope(s) as s:
        return _rows(s,
            f"SELECT category, subcategory, ROUND(SUM(-amount_sgd),2) v, COUNT(*) n "
            f"FROM cash_txn WHERE {where} GROUP BY category, subcategory ORDER BY category, v DESC", p)
