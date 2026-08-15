"""Spending analytics over the cash-flow ledger (`cash_txn`).

All amounts are SGD. "Spend" is the positive magnitude of counted outflows (-amount_sgd
where is_spend); excluded rows (transfers, card-bill payments, income) are filtered out of
every spend metric but remain inspectable via transactions(include_excluded=True).

Every public function accepts an optional Session (`s`) and routes through
db.session_scope, so it composes inside a larger unit of work or opens its own connection.
The seven read shapes share a single WHERE builder (`_where`) rather than each re-deriving
the same is_spend / date / category filters.

Note: summary() and trends() bucket by month with Postgres `to_char`, so their SQL is
Postgres-only; transactions(), categories(), years() and undated() are portable. That split
is a testing split too — tests/test_spending.py runs the portable shapes on SQLite plus
`_where` and `_trend_shape` (trends()' payload fold, where unclassified spend gets its name
and where it used to raise) directly, and tests/test_spending_pg.py runs these two functions'
actual SELECT against a real Postgres, skipping when there is none.

window() straddles that split rather than sitting on one side of it, which is why it is two
queries and a fold instead of one query: its per-source coverage query (MIN/MAX/SUM) is
portable, its per-source-per-month presence query buckets with `to_char` and is Postgres-only,
and the window rule itself is `_window_shape`, a pure function over those two result sets.
So the rule — every clause of it — is tested on any machine with no database at all, and
only the month bucketing needs a server: tests/test_spending.py::TestWindowShape holds the
rule, tests/test_spending_pg.py::TestPresenceQuery holds the bucketing.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_spending.py tests/test_spending_pg.py -q
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


#: Every month-bucketed query carries this on top of `_where`. txn_date is nullable and
#: `to_char(NULL,'YYYY-MM')` is NULL, so counted-but-dateless spend would arrive as a bucket
#: whose `ym` is None: an unlabelled column on the chart, and — once a second month exists —
#: a TypeError out of `_trend_shape`'s `sorted(..., key=ym)`, which is issue #35's crash one
#: level up. Dropping the rows here is also the consistent answer: no date window matches
#: them and years() cannot see them either, which is exactly what undated() is for. They stay
#: in summary()'s total_sgd, because they are spend — see that function's note.
DATED = "txn_date IS NOT NULL"


def summary(frm=None, to=None, s=None):
    """Totals + category / subcategory / month breakdowns for the `frm`/`to` date window.

    total_sgd is every counted line in the window; by_month covers only the dated ones (see
    DATED). Unwindowed, the two therefore differ by exactly undated()'s magnitude — the gap
    that endpoint exists to surface. months counts real months, so avg_month_sgd spreads any
    dateless spend across the months that are known rather than over a bucket that is not a
    month; with a frm/to window the question does not arise, since the window drops those
    rows from the total too."""
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
            f"WHERE {where} AND {DATED} GROUP BY ym ORDER BY ym", p)
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
            f"FROM cash_txn WHERE {where} AND {DATED} "
            f"GROUP BY ym, category ORDER BY ym"), p).mappings().all()
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


# ---------------- the spend-trend window ----------------
# Which months the spend-trend chart may draw, and everything its disclosure prose is
# derived from. The chart itself slices the array trends() already returns; this shape only
# says where to cut it, so trends() is untouched and one payload feeds two charts that
# cannot disagree about a shared month.
#
# "Spend-trend window" in full, every time, because "window" alone is already spoken for in
# this module: summary() and transactions() take a `frm`/`to` *date window*, which is a
# filter the caller chooses. This one is a rule the data decides, and the two are not
# interchangeable — see CONTEXT.md's Spending glossary, which pins both.

#: A source is *material* when its lifetime counted spend is at least this share of all
#: counted spend. Not a knife-edge on the live ledger: the gap between the last material
#: source and the first immaterial one is 18x (6.60% vs 0.36%).
MATERIAL_SHARE = 0.01


def _iso(d):
    """A date column as the `YYYY-MM-DD` string that goes on the wire. Postgres hands back
    `datetime.date`, SQLite hands back a string already, and an all-undated source hands
    back None from MIN/MAX — all three have to survive the same call."""
    return d if d is None or isinstance(d, str) else d.isoformat()


def _month(d):
    """The `YYYY-MM` bucket a date falls in — the same key `to_char(txn_date,'YYYY-MM')`
    produces, taken by slice so the two cannot drift."""
    return None if d is None else _iso(d)[:7]


def _next_month(ym):
    """The month after `ym`, rolling the year. December is the whole of the arithmetic:
    `12 // 12` carries the 1 into the year and `12 % 12 + 1` wraps the month back to 01."""
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def _month_range(start, end):
    """Every calendar month in `[start, end]`, including the ones no row landed in — which
    is the point: a month with no transactions at all is a gap, and it cannot be found by
    walking rows that do not exist."""
    out, m = [], start
    while m <= end:
        out.append(m)
        m = _next_month(m)
    return out


def _bucket(months, keys):
    """Fold a set of month keys into one `excluded` bucket: how many months, how many lines,
    how much money."""
    return {"months": len(keys),
            "n": sum(months[k]["n"] for k in keys),
            # float() before round(), or an empty bucket serializes as `0` where every other
            # bucket says `0.0` — the same money field with two JSON types across one payload.
            "total_sgd": round(float(sum(months[k]["v"] for k in keys)), 2)}


def _window_shape(coverage, presence):
    """The window rule, as a pure function over the two result sets `window()` runs.

    Split out for the same reason `_trend_shape` is: one of the two queries is Postgres-only
    (`to_char`) and this is not, so the rule is testable with no database at all — see
    tests/test_spending.py::TestWindowShape, which is where every clause below is pinned.

    `coverage` is one row per source: `first_txn`, `last_txn`, `total_sgd` (the *dated* sum).
    `presence` is one row per (month, source): `ym`, `source`, `n`, `v`. The rule:

      * **Material source** — lifetime counted spend >= MATERIAL_SHARE of all counted spend.
      * **Start** — the first calendar month beginning *after* the latest first-transaction
        among material sources. Unconditionally the next month: a source whose first line is
        the 1st still only gets counted from the month after, because materiality here is
        about when a source *appeared*, not how much of that month it saw.
      * **Drawable** — a month at or after `start`, that is not the month containing
        MAX(txn_date), and in which *every* material source has at least one counted line.
      * **Window** — `[start, last drawable month]`.

    Materiality is FIRST-APPEARANCE ONLY, never ongoing presence. The two are different
    rules and only the first one is right: a discontinued small source would otherwise
    truncate the window at the month it stopped reporting, and the window exists to exclude
    months a source had not started yet, not months it had finished.

    IMMATERIAL SOURCES ARE FLAGGED, NOT FILTERED. A source silently absent from a payload is
    how the fourth source stayed invisible in the first place, so `sources` carries every
    one of them with its share and its verdict, and the prose derives "two of three sources"
    from the flags rather than having it typed (typed, it is wrong at three of four).

    `gaps` is every non-drawable month *inside* the window, which is a hair wider than the
    spec's "strictly inside": `end` is drawable by construction, but `start` need not be —
    every material source has a first line before `start` begins, and none of that promises
    each one also has a line *in* `start`. Reading "strictly" literally would leave an
    undrawable start month inside the window and unlisted anywhere, which is the silent hole
    this whole endpoint exists to close. The closed interval agrees with the spec everywhere
    the spec's assumption holds.

    `excluded` is SPLIT, NOT TOTALLED, and computed from the *dated* total. Split because
    98.6% of the off-chart money on the live ledger is the leading months and one figure
    would misread it as a rounding tail. Dated because summary()'s total_sgd includes
    undated rows (see DATED) — subtracting it naively would absorb undated spend into the
    outside-the-window figure, and undated spend is undated()'s to report, not this one's.

    IT SPLITS THREE WAYS, NOT TWO. The spec names `before` and `after`; a gap month is a
    third kind of off-chart money, and the two-way split has no room for it. That matters
    because the only subtraction available to a caller is
    `dated_total - before - after`, which counts every gap month's spend as *drawn* — so a
    payload carrying `gaps` but not their money makes the disclosure prose wrong on the day
    the list first fires, and this endpoint exists precisely so that prose is derived rather
    than typed. Empty today, for the same reason `gaps` is. What the chart does with a
    non-empty `gaps` is still out of scope; having the number is not the same as drawing it.

    So: drawn = dated_total - before - after - gaps, and off-chart = before + after + gaps.

    A SECOND DEVIATION, deliberate: the gate's denominator is the *dated* counted total, not
    "all counted spend". The two differ only by undated rows, and undated rows cannot make a
    source present in any month — so a source material on undated money alone would be
    required in every month and no month would ever be drawable, which empties the chart
    permanently rather than protecting it. The share on the wire is the same dated figure the
    gate compared, so a reader can check the verdict against the number beside it. Both halves
    are moot on today's ledger (undated is n=0/$0) and neither would stay moot silently:
    undated() reports the count this rule is blind to.

    With no material source, or no drawable month, there is no window: `start` and `end` are
    both null and every dated month falls in `before`, because with no window there is no
    tail for `after` to mean.
    """
    dated_total = sum(float(c["total_sgd"] or 0) for c in coverage)
    sources = []
    for c in sorted(coverage, key=lambda c: -float(c["total_sgd"] or 0)):
        total, first = float(c["total_sgd"] or 0), _iso(c["first_txn"])
        share = total / dated_total if dated_total else 0.0
        sources.append({
            "source": c["source"],
            "first_txn": first,
            "last_txn": _iso(c["last_txn"]),
            "total_sgd": round(total, 2),
            # Rounded for the wire, compared raw: a 0.996% share rounds to 0.0100 and would
            # otherwise be admitted by the very digits that are there to display it.
            "share": round(share, 4),
            "material": first is not None and share >= MATERIAL_SHARE,
        })

    months: dict[str, dict] = {}
    for r in presence:
        m = months.setdefault(r["ym"], {"n": 0, "v": 0.0, "sources": set()})
        m["n"] += int(r["n"])
        m["v"] += float(r["v"])
        m["sources"].add(r["source"])

    material = {x["source"] for x in sources if x["material"]}
    empty = {"start": None, "end": None, "gaps": [], "sources": sources,
             "excluded": {"before": _bucket(months, sorted(months)),
                          "after": _bucket(months, []),
                          "gaps": _bucket(months, [])}}
    if not material:
        return empty

    start = _next_month(max(_month(x["first_txn"]) for x in sources if x["material"]))
    # MAX(txn_date) over *every* counted line, immaterial sources included: the partial month
    # is the month the ledger currently ends in, whoever reported into it.
    latest = max(_month(c["last_txn"]) for c in coverage if c["last_txn"] is not None)
    drawable = {m for m, d in months.items()
                if m >= start and m != latest and material <= d["sources"]}
    if not drawable:
        return empty

    end = max(drawable)
    gaps = [m for m in _month_range(start, end) if m not in drawable]
    return {
        "start": start,
        "end": end,
        "gaps": gaps,
        "sources": sources,
        "excluded": {"before": _bucket(months, [m for m in months if m < start]),
                     "after": _bucket(months, [m for m in months if m > end]),
                     "gaps": _bucket(months, [m for m in gaps if m in months])},
    }


def window(s=None):
    """Which months the spend-trend chart may draw, plus the material-source coverage its
    disclosure prose is derived from. See `_window_shape` for the rule.

    Two result sets, because they split on portability: the coverage query is per-source
    MIN/MAX/SUM and runs anywhere; the presence query buckets by month with `to_char` and is
    Postgres-only. Both are one pass over cash_txn, so the endpoint costs two queries whatever
    the ledger holds.

    The coverage sum is over dated rows only (`CASE WHEN txn_date IS NOT NULL` rather than a
    `FILTER` clause, which SQLite only learned in 3.30) while the GROUP BY is over all of
    them — so an all-undated source still appears in `sources`, with no coverage and no
    share, instead of vanishing from the payload."""
    where, p = _where()
    with session_scope(s) as s:
        coverage = _rows(s,
            f"SELECT source, MIN(txn_date) first_txn, MAX(txn_date) last_txn, "
            f"COALESCE(SUM(CASE WHEN {DATED} THEN -amount_sgd ELSE 0 END),0) total_sgd "
            f"FROM cash_txn WHERE {where} GROUP BY source", p)
        presence = _rows(s,
            f"SELECT to_char(txn_date,'YYYY-MM') ym, source, COUNT(*) n, "
            f"ROUND(SUM(-amount_sgd),2) v FROM cash_txn "
            f"WHERE {where} AND {DATED} GROUP BY ym, source ORDER BY ym, source", p)
    return _window_shape(coverage, presence)
