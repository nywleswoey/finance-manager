"""tests/fold_invariants.py's any-book claims, over the two books that exist in every checkout.

Those claims used to run only against the live ledger (tests/test_performance_live.py), so CI —
whose Postgres has no app schema — skipped every one of them and said nothing. Here they run in
the default suite, with no database, over:

  - **a fabricated ledger** folded by `fold_positions`, the same fold `compute()` hands its
    fetched rows to. It is built to reach every shape an invariant quantifies over — a name
    held in three buckets, a closed leg, a caveat, a refusal, a free lot, a split carry and a
    1:1 carry — and `TestFabricatedBookShapes` fails if a later edit loses one, because an
    invariant over an empty set passes without checking anything.
  - **the committed `/api/positions?closed=true` fixture** the Playwright suite serves
    (web/tests/fixtures/api/positions-closed.json). It is a capture of the live fold, so a
    recapture — or a hand edit, which #211 made — that ships rows breaking a claim fails here
    rather than being rendered as fact. This is the same drift #213 found by accident, caught
    by the same suite that guards the fold.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_fold_invariants.py -q
"""
import datetime as dt
import json
import os
import unittest

from tests.fold_invariants import FoldInvariants
from portfolio import performance as perf

D = dt.date
TODAY = D(2026, 1, 1)
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "tests",
                        "fixtures", "api")

ACCOUNTS = {"FSM": (1, "cash"), "CPF": (2, "cpf"), "SRS": (3, "srs"), "Moomoo": (4, "cash"),
            "Tiger Prime": (5, "cash")}
SECURITIES = {   # ticker: (security_id, market, asset_type, currency)
    "D05": (10, "SG", "stock", "SGD"), "PLTR": (11, "US", "stock", "USD"),
    "S51": (12, "SG", "stock", "SGD"), "ASTREA6B": (13, "SG", "stock", "SGD"),
    "AAPL": (14, "US", "stock", "USD"), "C31": (15, "SG", "stock", "SGD"),
    "9CI": (16, "SG", "stock", "SGD"), "C38U": (17, "SG", "stock", "SGD"),
    "OLD": (18, "SG", "fund", "SGD"), "NEW": (19, "SG", "fund", "SGD"),
}


def _txn(account, ticker, day, action, qty, price=None):
    account_id, bucket = ACCOUNTS[account]
    security_id, market, asset_type, currency = SECURITIES[ticker]
    return dict(account_id=account_id, account=account, funding_bucket=bucket,
                security_id=security_id, canonical_ticker=ticker, name=ticker, market=market,
                asset_type=asset_type, currency=currency, trade_date=day, action=action,
                qty_signed=qty, price=price, gross_amount=None, fees=None)


# One multi-leg book. Each block is a shape some invariant quantifies over; the comment says
# which verdict or cell state it exists to produce.
TXNS = [
    # D05 in three buckets, all costed: a hero with a closed leg (SRS sold out) beside two open.
    _txn("FSM", "D05", D(2020, 3, 16), "buy", 100, 25.0),
    _txn("CPF", "D05", D(2020, 6, 1), "open market", 200, 22.0),
    _txn("SRS", "D05", D(2021, 1, 4), "buy", 50, 24.0),
    _txn("SRS", "D05", D(2023, 5, 2), "sell", -50, 33.0),
    # PLTR in USD with options traded on it: the options stream exists on its cash leg only.
    _txn("Tiger Prime", "PLTR", D(2022, 5, 10), "buy", 300, 8.0),
    _txn("Tiger Prime", "PLTR", D(2024, 2, 1), "sell", -100, 20.0),
    # S51: a priced lot beside an unannotated transfer-in — a caveat, not a refusal.
    _txn("FSM", "S51", D(2021, 9, 22), "buy", 1000, 1.2),
    _txn("FSM", "S51", D(2022, 1, 5), "open/transfer_in", 400),
    # ASTREA6B: every entering unit unknown, then sold — the refusal, and a closed one.
    _txn("FSM", "ASTREA6B", D(2021, 6, 8), "open/transfer_in", 15000),
    _txn("FSM", "ASTREA6B", D(2024, 6, 10), "sell", -15000, 1.0),
    # AAPL: a gift and nothing else — free units, no capital ever at risk.
    _txn("Moomoo", "AAPL", D(2022, 12, 28), "gift_in", 1),
    # C31 -> 9CI (split) and C31 -> C38U (distribution): one event, two successors — bounded.
    # C38U already held stock of its own, so its 417 arrive beside real cost.
    _txn("Moomoo", "C31", D(2021, 4, 28), "buy", 2700, 3.73),
    _txn("Moomoo", "C31", D(2021, 9, 28), "sell/transfer", -2700),
    _txn("Moomoo", "9CI", D(2021, 9, 28), "open/transfer_in", 2700),
    _txn("FSM", "C38U", D(2020, 4, 3), "buy", 3200, 1.59),
    _txn("Moomoo", "C38U", D(2021, 9, 28), "open/transfer_in", 417),
    # OLD -> NEW: a 1:1 fund switch that empties its predecessor.
    _txn("CPF", "OLD", D(2022, 5, 17), "open market", 100, 10.0),
    _txn("CPF", "OLD", D(2023, 4, 24), "open market", -100, 11.0),
    _txn("CPF", "NEW", D(2023, 4, 27), "switch_in", 9),
]
DIVS = [{"account_id": 1, "security_id": 10, "pay_date": D(2022, 5, 1), "gross": 180.0,
         "currency": "SGD"},
        {"account_id": 2, "security_id": 10, "pay_date": D(2022, 5, 1), "gross": 360.0,
         "currency": "SGD"},
        {"account_id": 1, "security_id": 17, "pay_date": D(2022, 8, 1), "gross": 95.0,
         "currency": "SGD"}]
CORP = [("C31", "9CI", "split"), ("C31", "C38U", "distribution"), ("OLD", "NEW", "switch")]
OPTIONS = {"PLTR": {"pl_sgd": 1250.40, "pl_native": 976.88, "trades": 3, "currency": "USD",
                    "market": "US"}}
CONTRACTS = {"PLTR": [{"type": "put", "contracts": 2.0, "strike": 7.0, "multiplier": 100,
                       "currency": "USD", "open_date": D(2022, 3, 1),
                       "expiry_date": D(2022, 4, 14), "close_date": None, "open": False}]}
FX = {"USD": 1.28}
PRICE = {10: 34.5, 11: 72.1, 12: 1.05, 14: 230.0, 16: 2.6, 17: 2.3, 19: 130.0}


def fabricated_rows():
    # annotations={}: this book annotates nothing, so every `open/transfer_in` above is unknown
    # — which is what the caveat, the refusal and the split carry are built on.
    return perf.fold_positions(TXNS, DIVS, {}, CORP, OPTIONS, FX, PRICE, TODAY,
                               annotations={}, contracts=CONTRACTS)


class TestFabricatedBook(FoldInvariants, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = fabricated_rows()
        cls.traded = set(OPTIONS)


class TestFabricatedBookShapes(unittest.TestCase):
    """The fabricated book still reaches every shape the invariants quantify over. Without this
    an edit that drops, say, the caveat leaves every caveat claim passing over nothing."""

    @classmethod
    def setUpClass(cls):
        cls.rows = fabricated_rows()
        cls.verdict = {r["ticker"]: r["net_verdict"] for r in cls.rows}

    def test_every_net_verdict_is_reached(self):
        self.assertEqual(set(self.verdict.values()), {"hero", "caveat", "refuse", "bounded"})

    def test_a_name_is_held_in_three_buckets_and_one_leg_is_closed(self):
        d05 = {r["bucket"]: r["units"] for r in self.rows if r["ticker"] == "D05"}
        self.assertEqual(sorted(d05), ["cash", "cpf", "srs"])
        self.assertEqual(d05["srs"], 0.0)

    def test_the_caveat_the_refusal_and_the_free_lot(self):
        self.assertEqual((self.verdict["S51"], self.verdict["ASTREA6B"]), ("caveat", "refuse"))
        aapl = next(r for r in self.rows if r["ticker"] == "AAPL")
        self.assertEqual(aapl["cost_partition"]["free"], aapl["cost_partition"]["units_in"])
        self.assertEqual(aapl["return_verdict"], "no_capital")

    def test_the_options_stream_and_a_nonzero_peak(self):
        pltr = next(r for r in self.rows if r["ticker"] == "PLTR")
        self.assertIsNotNone(pltr["options_pl_sgd"])
        self.assertGreater(pltr["peak_car_sgd"], 0)
        self.assertIsNotNone(pltr["return_pct"])

    def test_a_split_carry_and_a_one_to_one_carry_both_fire(self):
        bound = {r["ticker"]: r["provenance"]["bound"] for r in self.rows
                 if r["provenance"] and r["provenance"]["bound"]}
        self.assertEqual(bound, {"9CI": "lower", "C38U": "upper"})
        new = next(r for r in self.rows if r["ticker"] == "NEW")
        self.assertEqual((new["provenance"]["from_ticker"], new["provenance"]["bound"]),
                         ("OLD", None))
        self.assertTrue(any(r["provenance"] and r["provenance"]["carried_sgd"] > 0
                            for r in self.rows))


class TestCommittedFixture(FoldInvariants, unittest.TestCase):
    """The rows the Playwright suite renders. `is_leg`-filtered as `/api/positions` ships them,
    so an emptied predecessor is absent — which the whole-ticker claims tolerate, since a husk
    carries no units, no Net and no verdict of its own."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(FIXTURES, "positions-closed.json")) as f:
            cls.rows = json.load(f)["positions"]
        with open(os.path.join(FIXTURES, "options-trades.json")) as f:
            # `realised` is `_is_open()`'s answer carried on the wire — read, not re-derived
            cls.traded = {t["underlying"] for t in json.load(f) if t["realised"]}


if __name__ == "__main__":
    unittest.main()
