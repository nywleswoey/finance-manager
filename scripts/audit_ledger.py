"""Audit the live ledger — tier 3 of #143's Testing Decisions. Run on demand, deliberately outside CI.

Point it at a real book (whatever `DATABASE_URL` resolves to — the local docker one by default)
and it prints two kinds of output, kept apart on purpose:

    PYTHONPATH=. .venv/bin/python scripts/audit_ledger.py

**Invariants — fail loudly.** Claims true of ANY book, so a failure is real news and the run exits
non-zero:

  - the cost partition sums to gross units in on every position
  - exactly one `from_ticker` in `corporate_action` has more than one row (the split carry, #151)
  - `transfer out` — with a space — appears only in `cdp_cost_lot`
  - the fold emits no warning while it computes (no unclassified action, no stale annotation)
  - every `stock dividend` row carries zero quantity
  - every cost lot aimed at a cash leg has CDP `txn` rows behind it (#146)

**Readings — print, never assert.** Pinned to THIS book, which gains trades and re-prices daily;
asserting them would make every new trade a red build. Each is printed beside the figure #143
settled, with `=` or `≠`, and a `≠` never changes the exit status:

  - the seven settled peak capital-at-risk figures, their peak dates, spans and states — a
    foreign name's AMOUNT is converted at latest FX and moves with the rate while its DATE does
    not, so the header prints the rates
  - the caveat set and its unknown percentages
  - the partition totals
  - `cost_known`'s false set, emptied predecessors marked
  - the `/api/performance` identity's named residual

Why a runner at all: this effort was burned once by a printed number nobody could re-derive — #128's
peak of 220,662 had no derivation behind it and cost an entire ticket (#139) to withdraw. The
live-ledger measurement behind the cost partition was throwaway instrumentation. The remedy for an
unreproducible number is a reproducer, so "does PLTR's peak come out 218,495.04?" is now a question
with somewhere to ask it.

Why the two classes, and not one pass/fail list: the seam is durability, not where it runs. A rule
gate over fabricated rows is immortal; a ledger claim is pinned to a moving book, and a committed
assertion pinned to a live figure is the hazard `capture_web_fixtures.py`'s header spends forty
lines cataloguing, with the essay deleted. Folding an unfailable item into a pass/fail list is how
checklists stop being trusted. `tests/test_audit_ledger.py` gates exactly that seam — a failing
invariant goes red, a disagreeing reading does not — over fabricated books, and states no live-book
figure.

Why not CI: CI's Postgres service runs an empty schema for the `*_pg.py` tests. Nothing in CI has
ever seen this book, so there is nothing there for this to read.

When to run it: before any fixture capture (#143's build order, step 3), so a wrong number is not
baked into eight fixtures — and whenever a figure printed somewhere needs re-deriving. Paste the
output where the next reader can diff against it; that is what the readings are for.

The `Settled` figures are #143 §7–§15 as #137 and #139, measured against a 548-row book. They are a record
of what the spec claimed, not a gate: when the book moves they will read `≠`, and the right
response is to read the difference, not to edit the table.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import os
import sys
from collections import defaultdict
from typing import Callable, NamedTuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio.money import rate_to_sgd  # noqa: E402
from portfolio.performance import CDP_ACCOUNT, fold_ticker  # noqa: E402

EPS = 1e-6


@dataclasses.dataclass
class Book:
    """Everything the audit reads, as plain data — fetched once by `fetch()`, fabricated in tests.

      rows              — `performance.compute()`'s output, one row per (bucket, security)
      corporate_actions — every `corporate_action` row as (from_ticker, to_ticker, type)
      actions           — {table: [action string per row]} for the tables carrying an action
      stock_dividends   — txn rows whose action is `stock dividend`: {ticker, trade_date, qty_signed}
      fold_warnings     — every WARNING logged while the performance readings were assembled
      cost_lot_tickers  — tickers with a `cdp_cost_lot` row `cdp_cost()` books (non-transfer, non-zero)
      cdp_txn_tickers   — tickers with at least one `txn` row on the CDP account
      car               — {ticker: ticker_car(...) plus `held`, `currency` and today's `rate`}
      performance       — {by: /api/performance's response for that dimension}
      orphan_options    — {underlying: realised SGD} for option underlyings with no stock row
      counts            — table sizes, dates and rates, printed so a reader knows which book
      fx                — {currency: rate_to_sgd}, latest — what `fold_ticker` converts at
    """
    rows: list
    corporate_actions: list
    actions: dict
    stock_dividends: list
    fold_warnings: list
    cost_lot_tickers: set
    cdp_txn_tickers: set
    car: dict
    performance: dict
    orphan_options: dict
    counts: dict = dataclasses.field(default_factory=dict)
    fx: dict = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------- invariants

class Invariant(NamedTuple):
    name: str
    check: Callable[[Book], list]      # failures, one message each; empty means it holds


def _count(x):
    """A count as the spec prints one: integral where it is, trimmed float where it is not."""
    return f"{x:g}"


def _partition_sums(book):
    out = []
    for r in book.rows:
        p = r["cost_partition"]
        got = p["costed"] + p["free"] + p["unknown"]
        if abs(got - p["units_in"]) > 1e-4:
            out.append(f"{r['bucket']}/{r['ticker']}: costed {_count(p['costed'])} + free "
                       f"{_count(p['free'])} + unknown {_count(p['unknown'])} = {_count(round(got, 4))} "
                       f"≠ units_in {_count(p['units_in'])}")
    return out


def multi_successors(corporate_actions):
    """`SELECT from_ticker FROM corporate_action GROUP BY from_ticker HAVING count(*) > 1`."""
    n = defaultdict(int)
    for frm, _, _ in corporate_actions:
        n[frm] += 1
    return sorted(t for t, c in n.items() if c > 1)


def _one_multi_successor(book):
    """Exactly one, not "at most one": a second multi-successor event is the named trigger for
    `bound` directions conflicting on one name (#143 Further Notes), and a zero means the carry
    that makes 9CI and C38U `bounded` has lost its only input."""
    got = multi_successors(book.corporate_actions)
    if len(got) == 1:
        return []
    return [f"{len(got)} from_tickers have more than one corporate_action row, expected "
            f"exactly 1: {got}"]


def _transfer_out_only_in_cost_lots(book):
    """`transfer out` with a space belongs on `cdp_cost_lot`. `classify()` treats that
    spelling as zero cash; a `txn` row carrying it is still the wrong table."""
    out = []
    for table, actions in sorted(book.actions.items()):
        if table == "cdp_cost_lot":
            continue
        n = sum(1 for a in actions if (a or "").strip().lower() == "transfer out")
        if n:
            out.append(f"{table} carries {n} `transfer out` row(s)")
    return out


def _no_fold_warnings(book):
    return list(book.fold_warnings)


def _stock_dividends_deliver_no_units(book):
    """`ZERO_CASH` suppresses these as echoes of cash dividends already counted from `dividend`.
    One carrying units would be a real delivery the partition has nowhere to put (#143 §7)."""
    return [f"{r['ticker']} {r['trade_date']}: stock dividend qty_signed {float(r['qty_signed'])}"
            for r in book.stock_dividends if abs(float(r["qty_signed"] or 0)) > EPS]


def _cost_lots_backed_by_cdp_rows(book):
    """`cdp_cost()` attaches a lot only to a cash-bucket position that itself holds a CDP txn row
    (#146), so a lot on a ticker CDP never held lands nowhere: its cost and proceeds are dropped
    rather than counted on top of the broker's own record of the same buy. #146 files the one
    instance (H78); this is the query #146 asks tier 3 to carry so a second cannot arrive
    unnoticed.

    Only lots aimed at a live cash leg are named: a ticker with no cash leg (or the blank rows a
    CSV's trailing lines leave behind) describes no position the book still reports."""
    cash_legs = {r["ticker"] for r in book.rows if r["bucket"] == "cash"}
    return [f"{t} has cdp_cost_lot rows and no CDP txn rows — its cost is dropped, not "
            f"attached (#146)"
            for t in sorted((book.cost_lot_tickers & cash_legs) - book.cdp_txn_tickers)]


INVARIANTS = [
    Invariant("partition sums to units in", _partition_sums),
    Invariant("exactly one multi-successor corporate action", _one_multi_successor),
    Invariant("`transfer out` only in cdp_cost_lot", _transfer_out_only_in_cost_lots),
    Invariant("the fold emits no warning (no unclassified action)", _no_fold_warnings),
    Invariant("every stock dividend carries zero quantity", _stock_dividends_deliver_no_units),
    Invariant("cost lots only on tickers CDP holds", _cost_lots_backed_by_cdp_rows),
]


# ---------------------------------------------------------------------------- readings

class SettledPeak(NamedTuple):
    ticker: str
    peak_car_sgd: float
    on: dt.date | None
    span_years: float
    state: str                      # open | closed


class SettledResidual(NamedTuple):
    orphans: float                  # Σ realised SGD of option underlyings never held as stock
    rounding: float


@dataclasses.dataclass
class Settled:
    """What #143 settled, for the readings to be printed beside. A record, never a gate."""
    # #143 §9, as settled by #139 §8
    peak_car: list = dataclasses.field(default_factory=lambda: [
        SettledPeak("PLTR", 218_495.04, dt.date(2024, 1, 2), 5.4, "open"),
        SettledPeak("D05", 96_440.20, dt.date(2020, 3, 16), 8.5, "open"),
        SettledPeak("TSLA", 94_473.75, dt.date(2026, 6, 11), 3.6, "closed"),
        SettledPeak("Q01", 33_461.35, dt.date(2020, 2, 27), 8.8, "open"),
        SettledPeak("O5RU", 39_986.42, dt.date(2019, 12, 28), 8.8, "open"),
        SettledPeak("S51", 1_767.92, dt.date(2021, 9, 22), 3.7, "closed"),
        SettledPeak("AAPL", 0.0, None, 3.7, "open"),
    ])
    # the rates the settled peaks were read at. A foreign name's peak is converted at latest FX,
    # so its AMOUNT moves with the rate while its DATE does not (every leg is single-currency);
    # the reading rescales to these before comparing, which is what makes "does PLTR come out
    # 218,495.04?" answerable on a later rate.
    fx: dict = dataclasses.field(default_factory=lambda: {"USD": 1.281, "HKD": 0.1633})
    # (ticker, unknown share of entering units) — #143 §11
    caveat: list = dataclasses.field(default_factory=lambda: [
        ("S51", 0.400), ("SET", 0.279), ("C38U", 0.075)])
    # #143 §7, after #138 moved C38U's 417 from free to unknown
    # and #199 moved Q01's 17,000 from unknown to costed (derived, not re-measured)
    partition: dict = dataclasses.field(default_factory=lambda: {
        "units_in": 1_574_652, "costed": 1_538_274, "free": 545, "unknown": 35_833})
    # #143 §8 — read under the definition in force when #137 measured it
    cost_known_false: list = dataclasses.field(default_factory=lambda: [
        "0P00006FYT", "AAPL", "AMZN", "ASTREA6B", "C31", "HMN"])
    # #143 §15
    residual: SettledResidual = SettledResidual(5_130.64, 0.03)
    # where the spec's own figure cannot reproduce for a reason already on record — printed
    # under the reading so a `≠` there is not re-investigated from scratch
    notes: dict = dataclasses.field(default_factory=lambda: {
        "O5RU": "#143 §9 disagrees with itself: rule 4's own paragraph takes O5RU to 55,137.42, "
                "the table's 39,986.42 is the series on 2019-12-28 (see "
                "tests/test_performance_live.py)",
        "cost_known": "the six predate §7's redefinition of cost_known (false only when EVERY "
                      "entering unit is unknown), under which free lots and emptied "
                      "predecessors read true",
    })


def _money(x):
    return "—" if x is None else f"{x:,.2f}"


def _mark(same):
    return "=" if same else "≠"


def _by_ticker(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["ticker"]].append(r)
    return out


def caveat_set(rows):
    """`(ticker, unknown_pct, unknown, units_in)` for every ticker whose SUMMED counts carry both
    costed and unknown units — `net_verdict`'s caveat rule, read whole-ticker. Largest share first."""
    out = []
    for tk, rs in _by_ticker(rows).items():
        units_in = sum(r["cost_partition"]["units_in"] for r in rs)
        costed = sum(r["cost_partition"]["costed"] for r in rs)
        unknown = sum(r["cost_partition"]["unknown"] for r in rs)
        if costed > EPS and unknown > EPS:
            out.append((tk, round(unknown / units_in, 4), unknown, units_in))
    return sorted(out, key=lambda t: (-t[1], t[0]))


def partition_totals(rows):
    return {k: sum(r["cost_partition"][k] for r in rows)
            for k in ("units_in", "costed", "free", "unknown")}


def cost_known_false(rows, corporate_actions):
    """`(ticker, is_emptied_predecessor)` for every ticker with a leg whose `cost_known` is false.
    An emptied predecessor is a carry's `from_ticker` holding nothing — its cost moved on."""
    predecessors = {frm for frm, _, _ in corporate_actions}
    out = {}
    for r in rows:
        if not r["cost_known"]:
            emptied = r["ticker"] in predecessors and r["units"] <= EPS
            out[r["ticker"]] = out.get(r["ticker"], True) and emptied
    return sorted(out.items())


def ticker_nets(rows, fx):
    """{ticker: the detail page's hero Net} — `fold_ticker` over each ticker's legs, refusals
    and tickers with no leg left out, because neither has a Net to add.

    `fx` is what the fold converts at: every leg of a ticker is one currency, so the rate is
    looked up once per ticker and handed in rather than read off a row."""
    out = {}
    for tk, rs in _by_ticker(rows).items():
        folded = fold_ticker(rs, rate_to_sgd(rs[0]["currency"], fx))
        if folded and folded["summary"]["net_pl_sgd"] is not None:
            out[tk] = folded["summary"]["net_pl_sgd"]
    return out


def performance_identity(book):
    """{by: (Σ group Net, Σ ticker Net, Σ orphan underlyings, residual)} — #143 §15's stated
    identity, `Σ group = Σ ticker + Σ orphan + rounding`, measured on each dimension."""
    tickers = round(sum(ticker_nets(book.rows, book.fx).values()), 2)
    orphans = round(sum(book.orphan_options.values()), 2)
    out = {}
    for by, groups in book.performance.items():
        group = round(sum(g["net_pl_sgd"] for g in groups.values()), 2)
        out[by] = (group, tickers, orphans, round(group - tickers - orphans, 2))
    return out


def at_settled_fx(car, settled):
    """`(amount, currency, rate)` — a foreign name's peak rescaled from today's rate to the one the
    spec read it at — or None for an SGD name, a measured zero, or when either rate is missing."""
    ccy, rate = car.get("currency"), car.get("rate")
    if ccy in (None, "SGD") or not rate or ccy not in settled.fx or not car["peak_car_sgd"]:
        return None
    return car["peak_car_sgd"] * settled.fx[ccy] / rate, ccy, settled.fx[ccy]


def _peak_car_lines(book, settled):
    """`=` needs the amount (at the spec's rate), the date and the state to agree, and a closed
    name's span too. An open name's span runs to today, so it is printed and not compared."""
    lines = [f"    {'ticker':<8}{'peak CAR':>14}  {'on':<10}  {'span':>5}  {'state':<6}   "
             f"#143 settled"]
    for tk, peak, on, span, state in settled.peak_car:
        want = f"{_money(peak)} on {on or '—'} · {span}y · {state}"
        got = book.car.get(tk)
        if got is None:
            lines.append(f"  ≠ {tk:<8}{'not in this book':>14}{'':>30}   {want}")
            continue
        rescaled = at_settled_fx(got, settled)
        # a rescale of a figure rounded to the cent can land a cent either side
        same_amount = (abs(rescaled[0] - peak) <= 0.02 if rescaled
                       else round(got["peak_car_sgd"], 2) == round(peak, 2))
        years = round(got["return_span_days"] / 365.25, 1)
        got_state = "open" if got["held"] else "closed"
        same = (same_amount and got["peak_car_date"] == on and got_state == state
                and (state == "open" or years == span))
        lines.append(f"  {_mark(same)} {tk:<8}{_money(got['peak_car_sgd']):>14}  "
                     f"{str(got['peak_car_date'] or '—'):<10}  {years:>4}y  {got_state:<6}   "
                     f"{want}")
        if rescaled:
            amount, ccy, rate = rescaled
            lines.append(f"    {'':<8}{_money(amount):>14}  at {ccy} {rate:g}, the rate "
                         f"#143 read it at (today {got['rate']:g})")
        if tk in settled.notes:
            lines.append(f"    note: {settled.notes[tk]}")
    return lines


def _caveat_lines(book, settled):
    got = caveat_set(book.rows)
    want = dict(settled.caveat)
    lines = [f"    {'ticker':<12}{'unknown':>8}  {'of units in':<24} #143 settled"]
    for tk, pct, unknown, units_in in got:
        same = tk in want and round(pct, 3) == round(want[tk], 3)
        spec = f"{want[tk]:.1%}" if tk in want else "not in the settled set"
        lines.append(f"  {_mark(same)} {tk:<12}{pct:>8.1%}  {_count(round(unknown, 4)) + ' of ' + _count(round(units_in, 4)):<24} {spec}")
    for tk in sorted(set(want) - {t[0] for t in got}):
        lines.append(f"  ≠ {tk:<12}{'—':>8}  {'not a caveat in this book':<24} {want[tk]:.1%}")
    return lines


def _partition_lines(book, settled):
    got = partition_totals(book.rows)
    return [f"  {_mark(round(got[k]) == settled.partition[k])} {k:<10}{round(got[k]):>14,}"
            f"   {settled.partition[k]:,}" for k in ("units_in", "costed", "free", "unknown")]


def _cost_known_lines(book, settled):
    got = cost_known_false(book.rows, book.corporate_actions)
    tickers = [t for t, _ in got]
    lines = [f"  {_mark(sorted(tickers) == sorted(settled.cost_known_false))} "
             f"{len(got)} ticker(s): "
             + (", ".join(f"{t}{' (emptied predecessor)' if husk else ''}" for t, husk in got)
                or "none"),
             f"    #143 settled: {len(settled.cost_known_false)} — "
             + ", ".join(settled.cost_known_false)]
    if "cost_known" in settled.notes:
        lines.append(f"    note: {settled.notes['cost_known']}")
    return lines


def _identity_lines(book, settled):
    orphans, rounding = settled.residual
    lines = [f"    {'by':<9}{'Σ group Net':>14}  {'Σ ticker Net':>14}  {'Σ orphans':>11}  "
             f"{'rounding':>9}   #143 settled"]
    for by, (group, tickers, orph, resid) in performance_identity(book).items():
        same = round(orph, 2) == round(orphans, 2) and round(resid, 2) == round(rounding, 2)
        lines.append(f"  {_mark(same)} {by:<9}{_money(group):>14}  {_money(tickers):>14}  "
                     f"{_money(orph):>11}  {_money(resid):>9}   "
                     f"orphans {_money(orphans)} + rounding {_money(rounding)}")
    if book.orphan_options:
        lines.append("    orphan underlyings: " + ", ".join(
            f"{t} {_money(v)}" for t, v in sorted(book.orphan_options.items())))
    return lines


READINGS = [
    ("peak capital-at-risk (#143 §9)", _peak_car_lines),
    ("the caveat set (#143 §11)", _caveat_lines),
    ("partition totals (#143 §7)", _partition_lines),
    ("cost_known false (#143 §8)", _cost_known_lines),
    ("/api/performance identity: Σ group = Σ ticker + Σ orphans + rounding (#143 §15)",
     _identity_lines),
]


def audit(book, settled=None):
    """`(lines, ok)` — `ok` is false exactly when an invariant fails. Readings never touch it."""
    settled = settled or Settled()
    lines, ok = [], True
    if book.counts:
        lines.append("book: " + " · ".join(f"{k} {v}" for k, v in book.counts.items()))
        lines.append("")
    lines.append("INVARIANTS — true of any book; a failure is real news")
    for inv in INVARIANTS:
        failures = inv.check(book)
        ok = ok and not failures
        lines.append(f"  {'FAIL' if failures else 'PASS'}  {inv.name}")
        lines.extend(f"          - {f}" for f in failures)
    lines.append("")
    lines.append("READINGS — pinned to this book; printed, never asserted  (= / ≠ against #143)")
    for title, read in READINGS:
        lines.append(f"  {title}")
        lines.extend("  " + ln for ln in read(book, settled))
    return lines, ok


# ---------------------------------------------------------------------------- the live book

class _WarningCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(f"{record.name}: {record.getMessage()}")


def fetch():
    """Read the book `DATABASE_URL` points at into a `Book`. Read-only."""
    from sqlalchemy import text

    from portfolio.cost_annotations import annotation_map
    from portfolio.db import fx_as_of, session_scope, valuation_as_of
    from portfolio.options import contracts_by_ticker, realized_by_ticker
    from portfolio.performance import (_accumulate_positions, _fx_and_price, cdp_cost, compute,
                                       legs_by_ticker, ticker_car)
    from server import main as server_main

    collect = _WarningCollector()
    root = logging.getLogger("portfolio")
    root.addHandler(collect)
    try:
        rows = compute()
        today = dt.date.today()
        with session_scope() as s:
            def column(sql):
                return [r[0] for r in s.execute(text(sql)).all()]

            corporate_actions = [tuple(r) for r in s.execute(text(
                "SELECT from_ticker, to_ticker, type FROM corporate_action ORDER BY id")).all()]
            actions = {"txn": column("SELECT action FROM txn"),
                       "cdp_cost_lot": column("SELECT action FROM cdp_cost_lot")}
            stock_dividends = [dict(r) for r in s.execute(text(
                "SELECT sec.canonical_ticker ticker, t.trade_date, t.qty_signed FROM txn t "
                "JOIN security sec ON sec.id = t.security_id "
                "WHERE lower(trim(t.action)) = 'stock dividend'")).mappings().all()]
            # the lots `cdp_cost()` actually books — a transfer or a zero amount attaches nothing,
            # and asking it rather than re-spelling its skip rules keeps the two from drifting
            cdp = cdp_cost(s)
            cost_lot_tickers = set(cdp)
            cdp_txn_tickers = set(column(
                "SELECT DISTINCT sec.canonical_ticker FROM txn t JOIN account a ON a.id = t.account_id "
                f"JOIN security sec ON sec.id = t.security_id WHERE a.name = '{CDP_ACCOUNT}'"))
            counts = {t: s.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                      for t in ("txn", "cdp_cost_lot", "dividend", "option_trade", "corporate_action")}
            counts["positions"] = len(rows)
            counts["prices as of"] = valuation_as_of(s)
            counts["fx as of"] = fx_as_of(s)
            fx, _ = _fx_and_price(s)
            counts["fx"] = ", ".join(f"{c} {r:g}" for c, r in sorted(fx.items()) if c != "SGD")

            # Peak capital-at-risk's DATE never reaches the wire (#143 Further Notes), so it is read
            # off the accumulators. The same inputs `compute()` fetches, through the same fold.
            txns = [dict(r) for r in s.execute(text("""
                SELECT t.account_id, a.name account, a.funding_bucket, t.security_id,
                       sec.canonical_ticker, sec.name, sec.market, sec.asset_type, sec.currency,
                       t.trade_date, t.action, t.qty_signed, t.price, t.gross_amount, t.fees
                FROM txn t JOIN account a ON a.id=t.account_id
                JOIN security sec ON sec.id=t.security_id""")).mappings().all()]
            divs = [dict(r) for r in s.execute(text(
                "SELECT account_id, security_id, pay_date, gross, currency FROM dividend"
            )).mappings().all()]
        # every row, not only the carry types: a split is counted over all of them,
        # the same rows compute_with_fx hands the fold.
        pos, meta = _accumulate_positions(
            txns, divs, cdp, corporate_actions, today, annotation_map(), fx)
        contracts = contracts_by_ticker()
        car = {}
        for tk, legs in legs_by_ticker(pos, meta).items():
            cs = contracts.get(tk, ())
            ccy = legs[0][1]["currency"] or "SGD"
            car[tk] = {**ticker_car(legs, cs, fx, today), "currency": ccy, "rate": fx.get(ccy),
                       "held": any(p["units"] > EPS for p, _ in legs) or any(c["open"] for c in cs)}

        held_tickers = {r["ticker"] for r in rows}
        orphan_options = {tk: v["pl_sgd"] for tk, v in realized_by_ticker().items()
                          if tk not in held_tickers}
        server_main._cache.pop("all", None)
        return Book(rows=rows, corporate_actions=corporate_actions, actions=actions,
                    stock_dividends=stock_dividends, fold_warnings=collect.messages,
                    cost_lot_tickers=cost_lot_tickers, cdp_txn_tickers=cdp_txn_tickers, car=car,
                    performance={by: server_main.performance(by=by)
                                 for by in ("market", "bucket", "account")},
                    orphan_options=orphan_options, counts=counts, fx=fx)
    finally:
        root.removeHandler(collect)


def main():
    lines, ok = audit(fetch())
    print(f"audit_ledger · run {dt.date.today()}\n")
    print("\n".join(lines))
    print(f"\n{'all invariants hold' if ok else 'INVARIANT FAILURE — see FAIL above'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
