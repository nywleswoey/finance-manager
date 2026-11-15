"""The DB adapters around the pure fold: `compute` / `compute_with_fx` read the ledger and run it;
`alloc_by_account` and `rollup` aggregate rows for the API."""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import text

from ingestion.prices import sg_today

from ..cost_annotations import annotation_map, unmatched
from ..db import fx_map, latest_close, session_scope
from ..money import rate_to_sgd
from .cdp import cdp_cost
from .fold import fold_positions

log = logging.getLogger(__name__)


def _fx_and_price(s):
    """Latest FX (currency -> rate_to_sgd) and latest close per security_id."""
    fx = fx_map(s)
    price = latest_close(s)
    return fx, price


def compute(session=None):
    """Fetch adapter: pull every input the fold needs from the DB, then hand off to the pure
    fold_positions(). The heavy SQL lives here; the cost-basis arithmetic lives in the fold."""
    return compute_with_fx(session)[0]


def compute_with_fx(session=None):
    """`(rows, fx)` — the fold's rows and **the very map they were converted at**, not a second
    reading of it.

    Every SGD figure on a row is a native amount times a rate read once at the top of this
    function. A caller that has to move one of those figures BACK into native — `fold_ticker`
    solving a breakeven price out of an SGD shortfall — needs that object and not a fresh
    `fx_map()`: a rate committed between the two reads makes the price the true one scaled by
    the ratio, so it stops zeroing the Net beside it. Same session is not enough, because
    Postgres takes a fresh snapshot per statement under READ COMMITTED and this function's SQL
    runs for seconds. Returning it is the only way to hold the two together.

    `compute()` is this with the map dropped — one projection, not a second fetch."""
    today = sg_today()
    with session_scope(session) as s:
        fx, price = _fx_and_price(s)
        # group txns + dividends per (account, security)
        txns = [dict(r) for r in s.execute(text("""
            SELECT t.account_id, a.name account, a.funding_bucket, t.security_id,
                   sec.canonical_ticker, sec.name, sec.market, sec.asset_type, sec.currency,
                   t.trade_date, t.action, t.qty_signed, t.price, t.gross_amount, t.fees
            FROM txn t JOIN account a ON a.id=t.account_id JOIN security sec ON sec.id=t.security_id
        """)).mappings().all()]
        divs = [dict(r) for r in s.execute(text("""
            SELECT account_id, security_id, pay_date, gross, currency FROM dividend
        """)).mappings().all()]
        cdp = cdp_cost(s)
        # every row, not only the carry types: a split is counted over all of them (§12)
        corp_actions = s.execute(text(
            "SELECT from_ticker, to_ticker, type FROM corporate_action")).all()
    # the annotation list is curated against THIS ledger, so its audit belongs here rather than
    # in the fold, which is a pure function over whatever rows it is handed (a fabricated
    # two-row book is not missing AAPL's gift; it simply never had one).
    for k, n in unmatched(txns, annotation_map()).items():
        log.warning("cost annotation %s matched %d txn rows, expected 1 — a stale annotation "
                    "silently un-frees a lot; a duplicate annotates one nobody looked at", k, n)
    # options open their own session (see realized_by_ticker); fetched outside the DB block above.
    from ..options import contracts_by_ticker, realized_by_ticker
    options = realized_by_ticker()
    return fold_positions(txns, divs, cdp, corp_actions, options, fx, price, today,
                          contracts=contracts_by_ticker()), fx


def alloc_by_account(session=None):
    """market value per account (SGD) — for allocation charts (no cost needed)."""
    with session_scope(session) as s:
        fx, price = _fx_and_price(s)
        rows = s.execute(text(
            "SELECT account, security_id, currency, units FROM current_position WHERE units > 0")).all()
    agg = defaultdict(float)
    for acct, sid, ccy, u in rows:
        px = price.get(sid)
        if px:
            agg[acct] += float(u) * px * rate_to_sgd(ccy, fx)
    return {k: {"mv_sgd": round(v, 2)} for k, v in agg.items()}


def empty_group():
    """Zeroed rollup-group accumulator. Shared with server.routes.portfolio so the groups it
    synthesises for orphan option underlyings match rollup()'s schema exactly."""
    return {"mv_sgd": 0.0, "income_sgd": 0.0, "capital_sgd": 0.0, "invested_sgd": 0.0,
            "realised_pl_sgd": 0.0, "unrealised_pl_sgd": 0.0, "stock_pl_sgd": 0.0,
            "unsplit_pl_sgd": 0.0}


def rollup(rows, by):
    """Group the fold's rows by `market`, `bucket` or `account` (SGD).

    Every figure is summed where the row ships it and skipped where it ships null — no field
    is gated on `cost_known`. That gate once left a caveat leg whose every unit is unknown out of
    the group Net while its row still shipped a `stock_pl_sgd` and a Net (#143 §8): the row's
    own nulls already say what it does not know."""
    agg = defaultdict(empty_group)
    for r in rows:
        # a row with nothing to add: no units, no stock P/L (a refusal) and no income. Closed
        # positions stay — they still carry realised P/L + dividends. Not `is_leg`: that asks
        # whether a leg is worth a detail-page column, and a closed lot that cost nothing (a
        # gift since sold) fails it while its proceeds are still stock P/L to count here.
        if r["units"] <= 1e-6 and r["stock_pl_sgd"] is None and abs(r["income_sgd"]) < 1e-6:
            continue
        # positions are pooled per funding bucket, so a row can span accounts -> join them
        key = (", ".join(r["accounts"]) if by == "account" else r[by]) or "—"
        g = agg[key]
        g["mv_sgd"] += r["mv_sgd"]; g["income_sgd"] += r["income_sgd"]
        # capital = cost basis of CURRENT holdings (so Capital + Unrealised = Current Value);
        # invested_sgd = total ever deployed incl. since-sold (return denominator)
        g["capital_sgd"] += r["cost_basis_sgd"] or 0
        g["invested_sgd"] += r["invested_sgd"] or 0
        g["realised_pl_sgd"] += r["realised_pl_sgd"] or 0
        g["unrealised_pl_sgd"] += r["unrealised_pl_sgd"] or 0
        # a leg the partition doubts knows the pair's SUM and neither member (#143 §6), so
        # summing the members alone would silently drop its stock P/L out of the group.
        # `stock_pl_sgd` is the accumulator /api/performance builds its Net from, for that
        # reason, and `unsplit_pl_sgd` is the part of it no leg could attribute to either
        # member — so `realised + unrealised + unsplit == stock_pl` on every group, and a
        # page showing the two members can say how much they do not reach rather than
        # printing a short column beside a whole Net.
        if r["stock_pl_sgd"] is not None:
            g["stock_pl_sgd"] += r["stock_pl_sgd"]
            if r["realised_pl_sgd"] is None or r["unrealised_pl_sgd"] is None:
                g["unsplit_pl_sgd"] += r["stock_pl_sgd"]
    return {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in agg.items()}
