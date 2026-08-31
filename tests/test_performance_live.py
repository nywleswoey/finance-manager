"""The cost partition against the LIVE book — the half of #148's acceptance the fabricated
shapes in tests/test_performance_fold.py cannot reach.

Two claims, deliberately gated differently:

  - **The invariant** — `costed + free + unknown == units_in` on every position — is true of any
    book, so it runs against whatever ledger is loaded. This is the one that must never drift:
    `cost_partition`'s own self-check only logs, so without a test a mis-assignment ships.
  - **The measured totals** — 1,574,652 in / 1,521,274 costed / 545 free / 52,833 unknown, the
    caveat set, the refusal set — are a point-in-time reading of a 548-row ledger, so they are
    asserted only while the book is still that book. A ledger that has grown skips them rather
    than failing; re-measuring is a deliberate act, the way `capture_web_fixtures` is.

Skips cleanly when no Postgres answers — the normal state of a checkout that has not run
`make db-up`, and the same bargain tests/pgtest.py strikes. Run: `pytest -m pg`.

    PYTHONPATH=. .venv/bin/python -m pytest tests/test_performance_live.py -q
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from portfolio.cost_annotations import annotation_map
from portfolio.db import session_scope
from portfolio.options import contracts_by_ticker
from portfolio.performance import (_accumulate_positions, _fx_and_price, cdp_cost, compute,
                                   legs_by_ticker, rollup, ticker_car)

# The ledger #148 was measured against: 548 txn rows / 73 positions. The totals below are
# readings of THAT book and nothing else.
MEASURED_TXN_ROWS = 548
MEASURED = {"units_in": 1_574_652, "costed": 1_521_274, "free": 545, "unknown": 52_833}
MEASURED_CAVEAT = [("S51", 0.4), ("SET", 0.2786), ("Q01", 0.25), ("C38U", 0.0746)]
MEASURED_REFUSAL = ["ASTREA6B"]

# #143 §9's settled peak capital-at-risk, one row per name the spec pinned. The DATE a peak
# falls on is a pure function of the ledger — every leg of these names is single-currency, so
# latest FX scales the whole series and cannot re-rank it — which makes the date the durable
# half of the reading, and it is asserted whatever the FX table says. The AMOUNT is a reading
# of a rate as well as of a book, so the two USD names are gated on MEASURED_FX below the way
# every other figure here is gated on the row count: pinned while the rate is the one they
# were read at, skipped rather than loosened once it moves.
#
# O5RU is the one name whose settled AMOUNT this build does not reproduce, and it is recorded
# rather than normalised. §9 rule 4 states the transfer-phantom correction takes it
# "79,972.84 -> 55,137.42" and says the peak "moves off the artifact onto a real plateau";
# 55,137.42 is what a dated replay produces, on 2023-07-03, where the cash leg holds 37,800
# units costing 49,335.42 beside an SRS leg of 5,802.00. The settled table's 39,986.42 is the
# series' value on 2019-12-28 — exactly the CDP cost pool, before a 5,000-unit buy in 2020 and
# a 3,710-unit rights issue in 2023 — and is also exactly half the withdrawn phantom, which is
# what halving the artifact gives rather than what recomputing the peak gives. The two
# statements in §9 disagree; this follows rule 4's own paragraph.
MEASURED_FX = {"USD": 1.281, "HKD": 0.1633}     # fx_rate's newest row when these were read
MEASURED_PEAK_CAR = {
    "PLTR": (218_495.04, dt.date(2024, 1, 2)),
    "D05": (96_440.20, dt.date(2020, 3, 16)),
    "TSLA": (94_473.75, dt.date(2026, 6, 11)),
    "Q01": (33_461.35, dt.date(2020, 2, 27)),
    "O5RU": (55_137.42, dt.date(2023, 7, 3)),
    "S51": (1_767.92, dt.date(2021, 9, 22)),
    "AAPL": (0.0, None),
}
MEASURED_IN_SGD = {"D05", "Q01", "O5RU", "S51", "AAPL"}      # rate-independent either way
MEASURED_NO_CAPITAL = ["AAPL", "HMN"]


def _rows_or_skip():
    """The loaded ledger, or a skip. Three ways there is nothing to measure, and all three are
    the normal state of a machine that is not the one holding the book:

      - no server answers (`OperationalError`) — a checkout that has not run `make db-up`;
      - the server answers but the app database has no schema (`ProgrammingError`,
        `relation "txn" does not exist`) — which is CI, where the Postgres service exists for
        the `*_pg.py` tests and those build their own throwaway schema;
      - the schema is there and empty.

    Caught as `SQLAlchemyError` rather than the two exact classes because the question this
    asks is "is there a book here", and every negative answer to it arrives as a database
    error. A real book that then fails to fold is a genuine failure and propagates."""
    try:
        with session_scope() as s:
            n = s.execute(text("SELECT count(*) FROM txn")).scalar()
    except SQLAlchemyError as e:
        raise unittest.SkipTest(f"no ledger to measure (start one with `make db-up` and "
                                f"`make ingest`): {type(e).__name__}") from None
    if not n:
        raise unittest.SkipTest("database has no txn rows — nothing to measure")
    return compute(), n


@pytest.mark.pg
class TestLiveBook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.n_txn = _rows_or_skip()

    def _measured_book_or_skip(self):
        if self.n_txn != MEASURED_TXN_ROWS:
            raise unittest.SkipTest(
                f"ledger has {self.n_txn} txn rows, not the {MEASURED_TXN_ROWS} these figures "
                f"were measured against — re-measure deliberately, don't loosen the assertion")

    def test_the_partition_sums_to_units_in_on_every_position(self):
        """True of any book. The one assertion that is not a point-in-time reading."""
        for r in self.rows:
            p = r["cost_partition"]
            self.assertAlmostEqual(p["costed"] + p["free"] + p["unknown"], p["units_in"], 4,
                                   f"{r['bucket']}/{r['ticker']}: {p}")

    def test_unknown_pct_agrees_with_the_counts_it_summarises(self):
        for r in self.rows:
            p = r["cost_partition"]
            want = round(p["unknown"] / p["units_in"], 4) if p["units_in"] else 0.0
            self.assertEqual(p["unknown_pct"], want, f"{r['bucket']}/{r['ticker']}: {p}")

    def test_cost_known_is_false_exactly_where_every_entering_unit_is_unknown(self):
        for r in self.rows:
            p = r["cost_partition"]
            all_unknown = p["units_in"] > 0 and p["unknown"] == p["units_in"]
            self.assertEqual(r["cost_known"], not all_unknown and p["units_in"] > 0,
                             f"{r['bucket']}/{r['ticker']}: {p}")

    def test_uncosted_units_is_gone_and_invested_sgd_is_null_where_cost_is_unknown(self):
        for r in self.rows:
            self.assertNotIn("uncosted_units", r)
            if not r["cost_known"]:
                self.assertIsNone(r["invested_sgd"], r["ticker"])

    def test_the_book_totals(self):
        self._measured_book_or_skip()
        self.assertEqual(len(self.rows), 73)
        for k, want in MEASURED.items():
            got = sum(r["cost_partition"][k] for r in self.rows)
            self.assertEqual(round(got), want, k)

    def test_the_caveat_set_and_the_refusal_set(self):
        self._measured_book_or_skip()
        caveat = sorted(((r["ticker"], r["cost_partition"]["unknown_pct"]) for r in self.rows
                         if r["cost_known"] and r["cost_partition"]["unknown"] > 0),
                        key=lambda t: -t[1])
        self.assertEqual(caveat, MEASURED_CAVEAT)
        self.assertEqual([r["ticker"] for r in self.rows if not r["cost_known"]],
                         MEASURED_REFUSAL)

    def test_the_two_free_lots_reproduce_their_component_sums(self):
        """`free -> cost_basis 0.0` is what makes these sums a number at all — without it
        AAPL's is `null + 0 + 1.22` on a name whose basis is a MEASURED zero."""
        self._measured_book_or_skip()
        for ticker, want in (("AAPL", 427.82), ("HMN", 144.57)):
            r = next(r for r in self.rows if r["ticker"] == ticker)
            self.assertEqual(r["cost_partition"]["free"], r["cost_partition"]["units_in"])
            self.assertEqual(r["avg_cost"], 0.0)
            self.assertEqual(r["cost_basis_sgd"], 0.0)
            # the sum is over the components AS SHIPPED (#143 §14): neither name was ever
            # optioned, so `options_pl_sgd` is null — the stream is absent, and an absent
            # stream contributes nothing rather than a zero somebody has to explain.
            self.assertIsNone(r["options_pl_sgd"], ticker)
            total = (r["unrealised_pl_sgd"] + r["realised_pl_sgd"] + r["income_sgd"])
            self.assertAlmostEqual(total, want, 2, ticker)


    # -- the four cell states (#149) ------------------------------------------------------

    def test_the_options_stream_is_absent_exactly_where_no_options_were_traded(self):
        """True of any book. An optioned name may legitimately ship `0.0` — the stream exists
        and measured zero — so the rule is about ABSENCE, not about the value."""
        from portfolio.options import realized_by_ticker
        traded = realized_by_ticker()
        for r in self.rows:
            want = r["bucket"] == "cash" and r["ticker"] in traded
            self.assertEqual(r["options_pl_sgd"] is not None, want,
                             f"{r['bucket']}/{r['ticker']}: {r['options_pl_sgd']!r}")

    def test_how_many_legs_the_options_row_leaves(self):
        """The measured size of the change: 61 of 73 legs stop carrying `Options 0`."""
        self._measured_book_or_skip()
        self.assertEqual(sum(1 for r in self.rows if r["options_pl_sgd"] is None), 61)

    def test_a_closed_leg_ships_measured_zeros_not_nulls(self):
        """True of any book. This is the one that decides whether a bucket column adds up:
        every leg that sold out but priced every unit it ever held knows its basis is zero."""
        for r in self.rows:
            if r["units"] > 1e-6 or not r["cost_known"] or r["cost_partition"]["unknown"]:
                continue
            for f in ("cost_basis_native", "cost_basis_sgd", "unrealised_pl_sgd"):
                self.assertEqual(r[f], 0.0, f"{r['bucket']}/{r['ticker']}.{f}")

    def test_the_cost_basis_family_answers_together_or_not_at_all(self):
        """True of any book. `avg_cost: null` beside `cost_basis: 0.0` would be one leg saying
        both "not known" and "measured zero" of the same fact — which is what an emptied
        predecessor (C31, 0P00006FYT) used to do."""
        for r in self.rows:
            answered = {f: r[f] is not None for f in
                        ("avg_cost", "cost_basis_native", "cost_basis_sgd")}
            self.assertEqual(len(set(answered.values())), 1, f"{r['ticker']}: {answered}")

    def test_a_leg_holding_unknown_units_nulls_the_whole_cost_basis_family(self):
        """True of any book: an average over a partly-priced lot is not a price, so every
        field derived from one goes null together — never some of them."""
        for r in self.rows:
            family = ("avg_cost", "cost_basis_native", "cost_basis_sgd",
                      "realised_pl_sgd", "unrealised_pl_sgd")
            if r["cost_known"] and not r["cost_partition"]["unknown"]:
                continue
            self.assertEqual([r[f] for f in family], [None] * len(family),
                             f"{r['bucket']}/{r['ticker']}")

    def test_stock_pl_is_on_every_row_and_is_the_pair_wherever_the_pair_is_known(self):
        """True of any book. `realised + unrealised ≡ proceeds − buy_cost + mv`, so the pair's
        sum survives a split nobody can make — which is what lets a caveat show an exact Net."""
        for r in self.rows:
            self.assertIn("stock_pl_sgd", r)
            self.assertEqual(r["stock_pl_sgd"] is None, not r["cost_known"], r["ticker"])
            if r["realised_pl_sgd"] is not None and r["unrealised_pl_sgd"] is not None:
                # exactly, with no tolerance: the field is rounded FROM the members, so §14's
                # measured cent (UD1U, 00468, 01310, 01523, 00101 — `_build_row` rounding each
                # component at 2dp) stays where it already is and does not open a second gap
                # between this field and the two it is the sum of.
                self.assertEqual(round(r["realised_pl_sgd"] + r["unrealised_pl_sgd"], 2),
                                 r["stock_pl_sgd"], f"{r['bucket']}/{r['ticker']}")

    def test_the_caveat_legs_keep_their_stock_pl_out_of_the_pair(self):
        """The names the partition doubts: their components are `not known` and their Net is
        exact — the whole reason the pair ships as a sum as well as as two members. Derived
        from the partition rather than checked against `MEASURED_CAVEAT`, because the claim is
        about every doubted leg, not about which legs this ledger happens to doubt."""
        caveat = {r["ticker"]: r for r in self.rows
                  if r["cost_known"] and r["cost_partition"]["unknown"] > 0}
        self.assertTrue(caveat, "no doubted leg in this book — nothing to assert")
        for t, r in caveat.items():
            self.assertIsNone(r["realised_pl_sgd"], t)
            self.assertIsNone(r["unrealised_pl_sgd"], t)
            self.assertIsNotNone(r["stock_pl_sgd"], t)
            self.assertIsNotNone(r["pl_sgd"], t)          # the Net is still exact

    def test_the_shapes_the_ticket_was_gated_on(self):
        """F34 (one open leg, one closed) and TSLA (closed, no units, real options P/L against
        a `pl_sgd` of 0) — the two live shapes #149's acceptance names."""
        self._measured_book_or_skip()
        legs = {r["bucket"]: r for r in self.rows if r["ticker"] == "F34"}
        self.assertEqual(sorted(legs), ["cash", "cpf"])
        self.assertEqual((legs["cpf"]["cost_basis_sgd"], legs["cpf"]["unrealised_pl_sgd"],
                          legs["cpf"]["realised_pl_sgd"]), (0.0, 0.0, 520.0))
        for r in legs.values():                            # each column adds up on its own
            self.assertAlmostEqual(r["realised_pl_sgd"] + r["unrealised_pl_sgd"]
                                   + r["income_sgd"], r["pl_sgd"], 2, r["bucket"])
        tsla = next(r for r in self.rows if r["ticker"] == "TSLA")
        self.assertEqual((tsla["units"], tsla["cost_basis_sgd"], tsla["unrealised_pl_sgd"],
                          tsla["realised_pl_sgd"], tsla["pl_sgd"]), (0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertNotEqual(tsla["options_pl_sgd"], 0.0)   # the stream exists and is real

    def test_every_group_ties_its_two_members_and_its_unsplit_to_its_stock_pl(self):
        """`Σ group net` must not move because four legs stopped splitting their stock P/L. The
        group carries the whole sum and names the part neither member reached, so what a page
        prints beside Net adds up to it — which is the claim a reader can check."""
        for by in ("market", "bucket", "account"):
            for k, v in rollup(self.rows, by).items():
                self.assertAlmostEqual(v["realised_pl_sgd"] + v["unrealised_pl_sgd"]
                                       + v["unsplit_pl_sgd"], v["stock_pl_sgd"],
                                       delta=0.01, msg=f"{by}/{k}")

    def test_the_unsplit_amount_is_exactly_the_doubted_legs_stock_pl(self):
        """It is not a plug: every cent of it comes from a leg the partition doubts."""
        self._measured_book_or_skip()
        want = sum(r["stock_pl_sgd"] for r in self.rows
                   if r["cost_known"] and r["cost_partition"]["unknown"] > 0)
        got = sum(v["unsplit_pl_sgd"] for v in rollup(self.rows, "bucket").values())
        self.assertAlmostEqual(got, want, delta=0.01)

    def test_peak_capital_at_risk_reproduces_the_settled_figures(self):
        """The question the spec says a build session needs to be able to ask: does the peak
        come out where it was measured? All seven dates and six of the seven amounts reproduce
        to the cent; the seventh is O5RU, recorded above."""
        self._measured_book_or_skip()
        at_measured_fx = _fx_or_none() == MEASURED_FX
        car = _live_ticker_car()
        for ticker, (peak, on) in MEASURED_PEAK_CAR.items():
            got = car[ticker]
            self.assertEqual(got["peak_car_date"], on, ticker)
            if peak is not None and (at_measured_fx or ticker in MEASURED_IN_SGD):
                self.assertAlmostEqual(got["peak_car_sgd"], peak, 2, ticker)
        if not at_measured_fx:
            raise unittest.SkipTest("fx_rate has moved since these amounts were read — the "
                                    "dates and the SGD names were still asserted")

    def test_peak_car_ships_as_a_measured_zero_and_the_verdict_gates_the_render(self):
        """True of any book: the field is never null, so nothing downstream can mistake "no
        capital was ever at risk" for "nobody computed it"."""
        for r in self.rows:
            self.assertIsNotNone(r["peak_car_sgd"], r["ticker"])
            self.assertIn(r["return_verdict"], ("ok", "caveat", "no_capital"), r["ticker"])
            if r["return_verdict"] == "no_capital":
                self.assertEqual(r["peak_car_sgd"], 0.0, r["ticker"])
                self.assertIsNone(r["return_pct"], r["ticker"])

    def test_no_capital_fires_on_the_windfalls_and_not_on_the_gift_that_wrote_puts(self):
        """The live counterexample proving the rule is peak CAR and not `cost_known`: AMZN's
        entering units are 100% free and it still reads a real positive percentage, because
        41,000 USD of put collateral was genuinely at risk behind them."""
        self._measured_book_or_skip()
        held = {r["ticker"]: r for r in self.rows}
        fired = sorted(r["ticker"] for r in self.rows
                       if r["return_verdict"] == "no_capital" and r["cost_partition"]["free"])
        self.assertEqual(fired, MEASURED_NO_CAPITAL)
        amzn = held["AMZN"]
        self.assertEqual(amzn["cost_partition"]["free"], amzn["cost_partition"]["units_in"])
        self.assertEqual(amzn["return_verdict"], "ok")
        self.assertGreater(amzn["return_pct"], 0)

    def test_the_percentage_is_net_over_peak_car_on_every_ticker(self):
        """True of any book, and the one arithmetic claim the hero makes. Summed across a
        ticker's legs, because the figure is whole-ticker: on the one name held in three
        buckets a per-leg reading is a different number entirely (3.9% against 31.2%)."""
        by_ticker = {}
        for r in self.rows:
            g = by_ticker.setdefault(r["ticker"], {"net": 0.0, "row": r})
            # both nulls read as nothing-to-add, for different reasons: `options_pl_sgd` is
            # absent on a never-optioned name (#149), `pl_sgd` refuses on a doubted leg.
            g["net"] += (r["pl_sgd"] or 0.0) + (r["options_pl_sgd"] or 0.0)
        for ticker, g in by_ticker.items():
            r = g["row"]
            if r["return_pct"] is None:
                continue
            self.assertAlmostEqual(r["return_pct"], round(g["net"] / r["peak_car_sgd"], 4), 4,
                                   ticker)

    def test_the_return_fields_agree_across_every_leg_of_a_ticker(self):
        """They are whole-ticker figures riding on per-leg rows, so a consumer holding any one
        leg has the whole-ticker answer — and the four must never disagree between legs."""
        seen = {}
        for r in self.rows:
            got = {k: r[k] for k in ("peak_car_sgd", "return_span_days", "return_pct",
                                     "return_verdict")}
            self.assertEqual(seen.setdefault(r["ticker"], got), got, r["ticker"])


def _fx_or_none():
    """The newest fx_rate row as `{currency: rate}` — what "at latest FX" resolved to."""
    with session_scope() as s:
        return {c: float(r) for c, r in s.execute(text(
            "SELECT currency, rate_to_sgd FROM fx_rate "
            "WHERE date = (SELECT max(date) FROM fx_rate)")).all()}


def _live_ticker_car():
    """`ticker_car` over the live book, keyed by ticker — the peak DATE never reaches the wire
    (#143 Further Notes), so reading it means going through the accumulators."""
    today = dt.date.today()
    with session_scope() as s:
        fx, _ = _fx_and_price(s)
        txns = [dict(r) for r in s.execute(text("""
            SELECT t.account_id, a.name account, a.funding_bucket, t.security_id,
                   sec.canonical_ticker, sec.name, sec.market, sec.asset_type, sec.currency,
                   t.trade_date, t.action, t.qty_signed, t.price, t.gross_amount, t.fees
            FROM txn t JOIN account a ON a.id=t.account_id
            JOIN security sec ON sec.id=t.security_id""")).mappings().all()]
        divs = [dict(r) for r in s.execute(text(
            "SELECT account_id, security_id, pay_date, gross, currency FROM dividend"
        )).mappings().all()]
        cdp = cdp_cost(s)
        corp = s.execute(text(
            "SELECT from_ticker, to_ticker, type FROM corporate_action "
            "WHERE type IN ('rename','split','consolidation','merger','switch')")).all()
    pos, meta = _accumulate_positions(txns, divs, cdp, corp, today, annotation_map())
    contracts = contracts_by_ticker()
    return {tk: ticker_car(ls, contracts.get(tk, ()), fx, today)
            for tk, ls in legs_by_ticker(pos, meta).items()}


if __name__ == "__main__":
    unittest.main()
