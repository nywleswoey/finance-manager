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
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from portfolio.db import session_scope
from portfolio.performance import compute, rollup

# The ledger #148 was measured against: 548 txn rows / 73 positions. The totals below are
# readings of THAT book and nothing else.
MEASURED_TXN_ROWS = 548
MEASURED = {"units_in": 1_574_652, "costed": 1_521_274, "free": 545, "unknown": 52_833}
MEASURED_CAVEAT = [("S51", 0.4), ("SET", 0.2786), ("Q01", 0.25), ("C38U", 0.0746)]
MEASURED_REFUSAL = ["ASTREA6B"]


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

    def test_the_options_stream_is_absent_or_a_number_never_a_standing_zero(self):
        """True of any book: `0.0` on a never-optioned name is a permanent `Options 0` line
        on 61 of 73 legs. Absent and zero are different facts and render differently."""
        for r in self.rows:
            o = r["options_pl_sgd"]
            self.assertTrue(o is None or isinstance(o, float), f"{r['ticker']}: {o!r}")
            if o is not None:
                self.assertNotEqual(o, 0.0, f"{r['ticker']} ships a zero-valued stream")

    def test_a_closed_leg_ships_measured_zeros_not_nulls(self):
        """True of any book. This is the one that decides whether a bucket column adds up:
        every leg that sold out but priced every unit it ever held knows its basis is zero."""
        for r in self.rows:
            if r["units"] > 1e-6 or not r["cost_known"] or r["cost_partition"]["unknown"]:
                continue
            for f in ("cost_basis_native", "cost_basis_sgd", "unrealised_pl_sgd"):
                self.assertEqual(r[f], 0.0, f"{r['bucket']}/{r['ticker']}.{f}")

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
                # to the cent, not exactly: `_build_row` rounds each component independently at
                # 2dp, which is a measured 1¢ on five tickers (§14 names them — UD1U, 00468,
                # 01310, 01523, 00101). §14's zero tolerance is on the summary, which rounds
                # once; tightening it here would only push the rounding somewhere less honest.
                self.assertAlmostEqual(r["realised_pl_sgd"] + r["unrealised_pl_sgd"],
                                       r["stock_pl_sgd"], delta=0.01,
                                       msg=f"{r['bucket']}/{r['ticker']}")

    def test_the_caveat_legs_keep_their_stock_pl_out_of_the_pair(self):
        """The four names the partition doubts. Their components are `not known` and their
        Net is exact — the whole reason the pair ships as a sum as well as as two members."""
        self._measured_book_or_skip()
        caveat = {r["ticker"]: r for r in self.rows
                  if r["cost_known"] and r["cost_partition"]["unknown"] > 0}
        self.assertEqual(sorted(caveat), sorted(t for t, _ in MEASURED_CAVEAT))
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

    def test_the_group_net_survives_the_pair_going_null(self):
        """`Σ group net` must not move because four legs stopped splitting their stock P/L:
        the group reads `stock_pl_sgd`, which is what those legs still know."""
        for by in ("market", "bucket", "account"):
            g = rollup(self.rows, by)
            want = sum(r["stock_pl_sgd"] or 0 for r in self.rows
                       if r["cost_known"] and not (r["units"] <= 1e-6 and not r["cost_known"]
                                                   and abs(r["income_sgd"]) < 1e-6))
            self.assertAlmostEqual(sum(v["stock_pl_sgd"] for v in g.values()), want, 2, by)


if __name__ == "__main__":
    unittest.main()
