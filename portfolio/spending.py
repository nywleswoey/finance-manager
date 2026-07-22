"""Spending analytics over the cash-flow ledger (`cash_txn`).

All amounts are SGD. "Spend" is the positive magnitude of counted outflows (-amount_sgd
where is_spend); excluded rows (transfers, card-bill payments, income) are filtered out of
every spend metric but remain inspectable via transactions(include_excluded=True).

Every public function accepts an optional Session (`s`) and routes through
db.session_scope, so it composes inside a larger unit of work or opens its own connection.
The four read shapes share a single WHERE builder (`_where`) rather than each re-deriving
the same is_spend / date / category filters.

Note: summary() and trends() bucket by month with Postgres `to_char`, so their SQL is
Postgres-only; transactions() and categories() are portable (covered by tests/test_spending.py).

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


def trends(frm=None, to=None, s=None):
    """Monthly spend split by group — a stacked time series (one key per group)."""
    where, p = _where(frm=frm, to=to)
    with session_scope(s) as s:
        rows = s.execute(text(
            f"SELECT to_char(txn_date,'YYYY-MM') ym, category, ROUND(SUM(-amount_sgd),2) v "
            f"FROM cash_txn WHERE {where} GROUP BY ym, category ORDER BY ym"), p).mappings().all()
    groups = sorted({r["category"] for r in rows})
    series: dict[str, dict] = {}
    for r in rows:
        m = series.setdefault(r["ym"], {"ym": r["ym"]})
        m[r["category"]] = float(r["v"])
    out = [{**{g: 0 for g in groups}, **m} for m in series.values()]
    return {"groups": groups, "series": sorted(out, key=lambda x: x["ym"])}


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


def categories(s=None):
    """Every (category, subcategory) with its counted spend and line count."""
    where, p = _where()
    with session_scope(s) as s:
        return _rows(s,
            f"SELECT category, subcategory, ROUND(SUM(-amount_sgd),2) v, COUNT(*) n "
            f"FROM cash_txn WHERE {where} GROUP BY category, subcategory ORDER BY category, v DESC", p)
