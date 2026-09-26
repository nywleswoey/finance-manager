"""Portfolio product routes: positions, performance, holdings, dividends, transactions, options.

Split out of server/main.py (Slice 3 of the codebase reorg) to match web/src/modules/portfolio.
server.main stays the composition root: app, middleware, auth_gate, health/refresh/cron,
PostHog proxy, StaticFiles. This module owns the portfolio-specific memoization cache (`_cache`)
that /api/refresh-prices and the cron handler in server.main clear — server.main re-exports it so
`server.main._cache` (imported by tests and scripts/audit_ledger.py) stays the same object.
"""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from portfolio import dividends
from portfolio.db import fetch_dicts, fx_as_of, fx_map, session_scope, valuation_as_of
from portfolio.money import rate_to_sgd, to_sgd
from portfolio.nullable import nulls_last, num
from portfolio.options import trades_for
from portfolio.performance import (CDP_ACCOUNT, alloc_by_account, cdp_transactions,
                                   compute_with_fx, empty_group, fold_ticker, is_leg, rollup)
from sqlalchemy import text

router = APIRouter()

_cache: dict = {}


def _cached(key, fn):
    """Memoize fn()'s result in the process-wide _cache under key (cleared by /refresh-prices)."""
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def _read_date(read):
    """`read(session)`'s date as an ISO string, or None — for the cached as-of dates."""
    with session_scope() as s:
        d = read(s)
    return str(d) if d else None


def _as_of():
    """ISO date the DB-priced views are as of, or None — see portfolio.db.valuation_as_of.

    Cached like the fold it describes and cleared by the same /refresh-prices, but not a
    transactional pair with it: the keys fill lazily and independently, and a write that
    bypasses this process (the scheduled ingest, or the cron landing on another warm instance)
    clears no cache here. So a date filled after such a write can sit above a fold filled
    before it. Narrow, self-healing on the next /refresh, and strictly smaller than the
    staleness the memo already carries."""
    return _read_date(valuation_as_of)


def perf_fold():
    """`(rows, fx)` — the fold's rows and the rate their SGD figures were converted at.

    ONE GENERATION, ONE RATE, AND **ONE CACHE KEY** SO NOTHING CAN HOLD HALF OF IT. Every SGD
    figure on a row is a native amount times a rate `compute()` read when this key filled.
    Anything that has to move one of those figures BACK into a native amount — the ticker fold
    solving its breakeven price out of an SGD shortfall — must use THAT rate and not a fresher
    one, or the price it returns is the true one scaled by the ratio between two readings and no
    longer zeroes the Net it sits beside. A live `fx_map()` per request is exactly that bug:
    `_cache` has no TTL, and a write that bypasses this process leaves a warm instance folding at
    yesterday's rate (see `_as_of`).

    THE PAIR IS ONE VALUE RATHER THAN TWO KEYS FILLED TOGETHER, and `compute_with_fx` hands it
    over as one so the map is the one the rows were converted with rather than a second reading
    of it. Two cache keys could be separated by a `_cache.clear()` landing between their fills;
    one key cannot. `perf_all` is a projection of this value and never a second source of it."""
    return _cached("all", compute_with_fx)


def perf_all():
    """The fold's rows. The rate they were converted at rides with them — see `perf_fold`."""
    return perf_fold()[0]


def perf():
    return _cached("rows", lambda: [r for r in perf_all() if r["units"] > 1e-6])


@router.get("/api/overview")
def overview():
    """Open-book market value and dividends, plus the book's Net.

    The Net is Σ `net_pl_sgd` over `perf_all()` where the verdict is not
    `refuse` — closed legs included, option premiums included, a refusal
    omitted. `pl_sgd` on a row is the older figure (cost-known, options
    excluded, rounded on its own). The response key is still named `pl_sgd`;
    renaming it waits until Holdings' P/L column stops reading the row field.
    `cost_sgd` is the invested amount on those same rows, so `return_pct`
    divides the Net it sits beside. Market value, dividends and the rollups
    stay the open book."""
    rows = perf()
    counted = [r for r in perf_all() if r["net_verdict"] != "refuse"]
    mv = sum(r["mv_sgd"] for r in rows)
    income = sum(r["income_sgd"] for r in rows)
    pl = sum(r["net_pl_sgd"] or 0 for r in counted)
    cost = sum(r["invested_sgd"] or 0 for r in counted)
    return {
        "market_value_sgd": round(mv, 2),
        "dividends_sgd": round(income, 2),
        "pl_sgd": round(pl, 2),
        "cost_sgd": round(cost, 2),
        "return_pct": round(pl / cost, 4) if cost else None,
        "positions": len(rows),
        "by_market": rollup(rows, "market"),
        "by_bucket": rollup(rows, "bucket"),
        "by_account": alloc_by_account(),
    }


@router.get("/api/positions")
def positions(closed: bool = False):
    """`{as_of, positions}`. Open positions (units > 0); with closed=true, also closed ones
    (units ≈ 0 that had real activity), each row tagged status=open|closed.

    `as_of` is when the prices below were last refreshed: the older of the newest `price` and
    `fx_rate` row, so an upper bound on the freshness of any one row rather than that row's own
    date (`latest_close` prices each security off its own newest close — a delisted ticker
    stopped years ago and still appears under a same-day `as_of`; portfolio.db has the detail).
    It is NOT /api/return's date, which is Yahoo's newest close — the two
    endpoints read different price sources on purpose (ADR 0001) and so answer as of different
    moments. Issue #56 measured them 29,451 SGD apart; the gap closes by running the price
    ingest, but only the two dates let a reader see the numbers are not comparable.

    An envelope rather than the bare list this used to return, because the date belongs to the
    valuation as a whole, not to any row — closed positions carry no market value at all."""
    out = []
    for r in perf_all():
        is_open = r["units"] > 1e-6
        if not is_open and not (closed and is_leg(r)):   # is_leg drops noise: never really held
            continue
        out.append({**r, "status": "open" if is_open else "closed"})
    # open first (by market value desc), then closed (by Net desc)
    out.sort(key=lambda r: (r["status"] != "open", -(r["mv_sgd"] if r["status"] == "open"
                                                      else (r["net_pl_sgd"] or 0))))
    return {"as_of": _cached("as_of", _as_of), "positions": out}


@router.get("/api/performance")
def performance(by: str = Query("market", enum=["market", "bucket", "account"])):
    r = rollup(perf_all(), by)                          # perf_all -> include closed positions
    # fold in realized options P/L for the same dimension (computed directly from the
    # options book so orphan underlyings with no stock position are still counted)
    from portfolio.options import realized_by
    for k, v in realized_by(by).items():
        r.setdefault(k, empty_group())
        r[k]["options_pl_sgd"] = v
    for g in r.values():
        g.setdefault("options_pl_sgd", 0.0)
        # net = stock P/L + dividends + option premiums. `stock_pl_sgd`, not the pair, because
        # a leg whose partition holds unknown units knows the SUM and neither member (#149 §6):
        # adding the members would drop C38U's and S51's stock P/L out of the group total. On
        # every leg that knows both, stock_pl_sgd is identically their sum, so nothing moves.
        g["net_pl_sgd"] = round(g["stock_pl_sgd"] + g["income_sgd"] + g["options_pl_sgd"], 2)
        # ROI on total money ever deployed (incl. since-sold positions)
        g["return_pct"] = round(g["net_pl_sgd"] / g["invested_sgd"], 4) if g.get("invested_sgd") else None
    return r


def ticker_ledger(s, ticker):
    """One ticker's transactions and dividends across EVERY funding bucket, each row carrying
    its `bucket`, plus the latest FX map. Unsorted and unenriched — `holding` does that.

    Bucket attribution is the join onto `account.funding_bucket`. It replaced a hardcoded
    bucket->accounts literal that duplicated that column and silently dropped any account the
    literal did not list. The `cdp_transactions()` rows carry an account name and no bucket, so
    they take theirs from the same table, by name.

    `a.name <> CDP_ACCOUNT` stays: CDP's statement rows are month-end unit diffs, and its priced
    trades arrive from `cdp_cost_lot` instead. Cash dividends booked as 0-qty `stock dividend`
    txns belong in the dividend history, not the ledger — they do not change the position."""
    txns = fetch_dicts(s,
        "SELECT t.trade_date, a.name account, a.funding_bucket bucket, t.action, t.qty_signed, "
        "t.price, t.gross_amount, t.currency, t.source_file FROM txn t "
        "JOIN account a ON a.id=t.account_id JOIN security sec ON sec.id=t.security_id "
        f"WHERE sec.canonical_ticker=:tk AND a.name <> '{CDP_ACCOUNT}' "
        "AND NOT (t.action ILIKE '%dividend%' AND t.qty_signed = 0)",
        {"tk": ticker})
    divs = fetch_dicts(s,
        "SELECT d.pay_date, a.name account, a.funding_bucket bucket, d.gross, d.currency, d.kind, "
        "d.units, d.amount_per_unit FROM dividend d "
        "JOIN account a ON a.id=d.account_id JOIN security sec ON sec.id=d.security_id "
        "WHERE sec.canonical_ticker=:tk ORDER BY d.pay_date",
        {"tk": ticker})
    bucket_of = dict(s.execute(text("SELECT name, funding_bucket FROM account")).all())
    txns += [{**r, "bucket": bucket_of.get(r["account"])}
             for r in cdp_transactions(s) if r["ticker"] == ticker]
    return txns, divs, fx_map(s)


def _fx_as_of():
    """ISO date of the newest FX row, or None — cached and cleared beside `_as_of`."""
    return _read_date(fx_as_of)


@router.get("/api/holding")
def holding(ticker: str):
    """The whole ticker across every funding bucket: `{as_of, fx_as_of, summary, buckets,
    transactions, dividends, options}` (#143 §2). There is no `bucket` parameter — one caller
    renders one shape.

    `summary` and `buckets` are `performance.fold_ticker`'s, and its `None` is the 404; this
    handler only fetches. `as_of` is `/api/positions`' valuation date verbatim; `fx_as_of` is what
    "at latest FX" is as of. The options table carries no bucket — see BACKEND.md for the stated
    assumption and its trigger."""
    # perf_fold (not perf) so a fully CLOSED ticker still has legs to fold — and it hands over
    # the rows WITH the rate their SGD figures were converted at. The fold takes that rate as a
    # parameter rather than off a row (no page has any use for a rate on the wire), and every leg
    # of a ticker is one currency. TWO MAPS, TWO NAMES, so neither can be reached for by accident:
    # `fold_fx` is the generation these rows belong to and is the only rate the breakeven may be
    # solved at; `ledger_fx` is the dividend rows' own fresher read and converts only those.
    all_rows, fold_fx = perf_fold()
    rows = [r for r in all_rows if r["ticker"] == ticker]
    folded = rows and fold_ticker(rows, rate_to_sgd(rows[0]["currency"], fold_fx))
    if not folded:
        return JSONResponse({"detail": "not found"}, status_code=404)
    with session_scope() as s:
        txns, divs, ledger_fx = ticker_ledger(s, ticker)
    txns.sort(key=nulls_last("trade_date"))
    bal = 0.0
    for t in txns:
        bal += float(t["qty_signed"] or 0)
        t["balance"] = round(bal, 4)
    # enrich each dividend with qty held at pay date + declared rate per unit.
    # prefer statement-stated values; fall back to ledger replay / implied (gross/qty).
    # units_at / implied_rate are the shared pay_date attribution primitives (see dividends.py).
    # gross_sgd mirrors the rest of the detail view (cost/MV/P/L are all SGD); the native
    # gross + rate stay alongside it because they are what the statement actually said.
    for x in divs:
        units = num(x["units"])
        if units is None:
            pairs = [(t["trade_date"], float(t["qty_signed"] or 0)) for t in txns
                     if t["account"] == x["account"]]
            units = dividends.units_at(x["pay_date"], pairs)
        rate = num(x["amount_per_unit"])
        if rate is None:
            rate = dividends.implied_rate(x["gross"], units)
        x["units"] = units
        x["rate"] = rate
        x["gross_sgd"] = round(to_sgd(num(x["gross"]) or 0, x["currency"], ledger_fx), 2)
    return {"as_of": _cached("as_of", _as_of), "fx_as_of": _cached("fx_as_of", _fx_as_of),
            **folded, "transactions": txns, "dividends": divs,
            "options": trades_for(ticker)}


@router.get("/api/dividend-details")
def dividend_details():
    return dividends.details()


@router.get("/api/dividends-annual")
def dividends_annual():
    return dividends.annual()


@router.get("/api/transactions")
def transactions(account: str | None = None, ticker: str | None = None, limit: int = 500):
    # CDP transactions come from cdp-stocks (has price + amount); statements omit them
    rows = []
    if account != CDP_ACCOUNT:                         # CDP comes only from cdp-stocks below
        q = ("SELECT t.trade_date, a.name account, s.canonical_ticker ticker, COALESCE(s.name,'') name, "
             "t.action, t.qty_signed, t.price, t.gross_amount, t.currency, t.source_file "
             "FROM txn t JOIN account a ON a.id=t.account_id JOIN security s ON s.id=t.security_id "
             f"WHERE a.name <> '{CDP_ACCOUNT}'")
        p: dict = {}
        if account:
            q += " AND a.name=:acct"; p["acct"] = account
        if ticker:
            q += " AND s.canonical_ticker=:tk"; p["tk"] = ticker
        with session_scope() as s:
            rows = fetch_dicts(s, q + " LIMIT 2000", p)
    if account in (None, CDP_ACCOUNT):                 # add CDP from cdp-stocks
        cdp = cdp_transactions()
        if ticker:
            cdp = [r for r in cdp if r["ticker"] == ticker]
        rows += cdp
    rows.sort(key=nulls_last("trade_date"))
    return rows[:limit]


@router.get("/api/return")
def portfolio_return():
    if "ret" not in _cache:
        from portfolio.twr import compute_twr
        try:
            _cache["ret"] = compute_twr()
        except Exception as e:
            return {"error": str(e)[:120]}
    return _cache["ret"]


@router.get("/api/options")
def options_summary():
    from portfolio.options import compute
    return _cached("opt", compute)


@router.get("/api/options-trades")
def options_trades(limit: int = 500):
    from portfolio.options import recent
    return recent(limit)


@router.get("/api/accounts")
def accounts():
    with session_scope() as s:
        return fetch_dicts(s, "SELECT name, broker, funding_bucket FROM account "
                              "ORDER BY funding_bucket, name")
