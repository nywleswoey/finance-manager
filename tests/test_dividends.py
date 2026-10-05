"""portfolio.dividends — the shared pay_date attribution primitives and details().

Stdlib unittest + in-memory SQLite (no pg), matching tests/test_networth.py. annual() leans
on Postgres (EXTRACT), so it isn't exercised here;
details() is portable (plain SELECT + Python fold) and carries the qty-replay logic.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividends.py -q
"""
import datetime as dt
import unittest
from decimal import Decimal

from portfolio import dividends
from portfolio.models import Account, Dividend, FxRate, Security, Txn
from tests.sqlitetest import make_session

D = dt.date


# ---------------- the shared primitives (pure) ----------------

class TestUnitsAt(unittest.TestCase):
    def test_none_pay_date_has_nothing_to_attribute(self):
        self.assertIsNone(dividends.units_at(None, [(D(2024, 1, 1), 100)]))

    def test_sums_only_trades_on_or_before_pay_date(self):
        txns = [(D(2024, 1, 1), 100), (D(2024, 3, 1), 50), (D(2024, 9, 1), 999)]
        self.assertEqual(dividends.units_at(D(2024, 6, 1), txns), 150.0)  # the 999 is after

    def test_signed_quantities_net_out(self):
        self.assertEqual(dividends.units_at(D(2024, 6, 1),
                                            [(D(2024, 1, 1), 100), (D(2024, 2, 1), -40)]), 60.0)


class TestImpliedRate(unittest.TestCase):
    def test_gross_over_qty(self):
        self.assertEqual(dividends.implied_rate(100, 400), 0.25)

    def test_unusable_qty_is_none(self):
        self.assertIsNone(dividends.implied_rate(100, 0))
        self.assertIsNone(dividends.implied_rate(100, None))


class TestUnreceivedLastYear(unittest.TestCase):
    TODAY = D(2026, 10, 4)

    def _remaining(self, last_year, paid):
        rows = [{"pay_date": d, "rate": r} for d, r in last_year]
        still, _ = dividends.unreceived_last_year(rows, paid, self.TODAY)
        return [r["pay_date"] for r in still]

    def test_a_still_to_come_payment_carries_its_expected_date(self):
        # the anniversary replayed onto this year, so a reader can tell which month it's due.
        rows = [{"pay_date": D(2025, 9, 28), "rate": 0.5}]
        still, _ = dividends.unreceived_last_year(rows, set(), self.TODAY)
        self.assertEqual([r["expected_date"] for r in still], [D(2026, 9, 28)])

    def _overdue(self, last_year, paid):
        rows = [{"pay_date": d, "rate": r} for d, r in last_year]
        _, overdue = dividends.unreceived_last_year(rows, paid, self.TODAY)
        return [(r["pay_date"], r["expected_date"]) for r in overdue]

    def test_a_monthly_receipt_consumes_exactly_one_nearby_payment(self):
        last_year = [(D(2025, m, 30 if m != 2 else 28), 0.1) for m in range(8, 13)]
        paid = {D(2026, 8, 30), D(2026, 9, 30)}
        self.assertEqual(self._remaining(last_year, paid),
                         [D(2025, 10, 30), D(2025, 11, 30), D(2025, 12, 30)])
        self.assertEqual(self._overdue(last_year, paid), [])

    def test_a_late_payment_within_the_drift_window_is_still_projected(self):
        self.assertEqual(self._remaining([(D(2025, 9, 28), 0.5)], set()), [D(2025, 9, 28)])

    def test_bought_mid_year_payments_long_past_are_overdue_not_projected(self):
        # these payments almost always already happened — just not in the ledger yet — so
        # they move to `overdue` instead of vanishing from both received and projected.
        last_year = [(D(2025, 5, 12), 0.5), (D(2025, 7, 20), 0.6)]
        self.assertEqual(self._remaining(last_year, set()), [])
        self.assertEqual(self._overdue(last_year, set()),
                         [(D(2025, 5, 12), D(2026, 5, 12)), (D(2025, 7, 20), D(2026, 7, 20))])

    def test_a_partial_last_year_still_projects_its_late_year_payment(self):
        paid = {D(2026, 5, 10), D(2026, 8, 15)}
        self.assertEqual(self._remaining([(D(2025, 11, 20), 0.6)], paid), [D(2025, 11, 20)])

    def test_one_payment_held_in_two_accounts_is_projected_once(self):
        last_year = [(D(2025, 11, 20), 0.54), (D(2025, 11, 20), 0.54)]
        self.assertEqual(self._remaining(last_year, set()), [D(2025, 11, 20)])

    def test_component_lines_and_a_combined_row_are_one_payment_at_the_combined_rate(self):
        rows = [{"pay_date": D(2025, 11, 20), "rate": 0.60, "account": "FSM"},
                {"pay_date": D(2025, 11, 20), "rate": 0.15, "account": "FSM"},
                {"pay_date": D(2025, 11, 20), "rate": 0.75, "account": "CPF"}]
        still, _ = dividends.unreceived_last_year(rows, set(), self.TODAY)
        self.assertEqual([(r["pay_date"], r["rate"]) for r in still], [(D(2025, 11, 20), 0.75)])

    def test_a_matched_payment_is_never_also_overdue(self):
        # a payment more than DRIFT_DAYS stale that nonetheless matched this year's receipt
        # (e.g. a holding bought back after a long gap) is consumed, not double-counted as overdue.
        paid = {D(2026, 1, 15)}
        last_year = [(D(2025, 1, 10), 0.4)]
        self.assertEqual(self._remaining(last_year, paid), [])
        self.assertEqual(self._overdue(last_year, paid), [])


class TestSgdOrNone(unittest.TestCase):
    def test_converts_when_the_currency_has_a_rate(self):
        self.assertEqual(dividends._sgd_or_none(100, "HKD", {"HKD": 0.17}), (17.0, None))

    def test_sgd_needs_no_fx_row(self):
        self.assertEqual(dividends._sgd_or_none(80, "SGD", {}), (80.0, None))

    def test_a_missing_rate_flags_instead_of_raising(self):
        # projected() is an estimate, not a statement fact — unlike annual(), it must not
        # crash the whole page over one currency with no FX row.
        amt, flag = dividends._sgd_or_none(500, "EUR", {})
        self.assertIsNone(amt)
        self.assertEqual(flag, "no FX rate for EUR")


# ---------------- details() (SQLite) ----------------

class TestDetails(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        self.s.add(Account(id=1, name="CDP", funding_bucket="cash"))
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS", market="SG"))
        self.s.flush()
        self._d = 0

    def tearDown(self):
        self.s.close()

    def _div(self, pay, gross, *, sec=1, declared=None, units=None, ccy="SGD"):
        self._d += 1
        self.s.add(Dividend(account_id=1, security_id=sec, pay_date=pay, kind="cash",
                            gross=Decimal(str(gross)),
                            amount_per_unit=None if declared is None else Decimal(str(declared)),
                            units=None if units is None else Decimal(str(units)),
                            currency=ccy, source_file="unmapped-src", dedup_hash=f"h{self._d}"))

    def _fx(self, ccy, rate):
        self.s.add(FxRate(date=D(2024, 6, 1), currency=ccy, rate_to_sgd=Decimal(str(rate))))

    def _buy(self, day, qty):
        self._d += 1
        self.s.add(Txn(account_id=1, security_id=1, trade_date=day, action="buy",
                       qty_signed=Decimal(str(qty)), dedup_hash=f"t{self._d}"))

    def _by_gross(self, res):
        return {r["gross"]: r for r in res["rows"]}

    def test_statement_declared_rate_and_units_win(self):
        self._div(D(2024, 6, 1), 100, declared=0.5, units=200)
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[100.0]
        self.assertEqual(r["qty"], 200.0)
        self.assertEqual(r["qty_source"], "statement")
        self.assertEqual(r["rate"], 0.5)
        self.assertEqual(r["rate_source"], "declared")
        self.assertEqual(r["flags"], [])

    def test_falls_back_to_ledger_replay_and_implied_rate(self):
        self._buy(D(2024, 1, 1), 400)          # held at pay date
        self._buy(D(2024, 9, 1), 999)          # after pay date, must not count
        self._div(D(2024, 6, 1), 100)          # no declared rate, no stated units
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[100.0]
        self.assertEqual(r["qty"], 400.0)
        self.assertEqual(r["qty_source"], "ledger")
        self.assertEqual(r["implied_rate"], 0.25)
        self.assertEqual(r["rate_source"], "implied")

    def test_unmapped_and_undated_dividend_is_flagged(self):
        self._div(None, 50, sec=None)          # no security -> unmapped; no pay_date -> no date
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[50.0]
        self.assertIn("unmapped ticker", r["flags"])
        self.assertIn("no date", r["flags"])
        self.assertIn("qty unknown — needs manual input", r["flags"])
        self.assertIsNone(r["rate"])

    def test_foreign_gross_is_converted_to_sgd_alongside_the_native_amount(self):
        # the rest of the app reports SGD; a native-only dividend column made HKD 1,000 look
        # like SGD 1,000. Native stays for statement reconciliation.
        self._fx("HKD", 0.17)
        self._div(D(2024, 6, 1), 1000, declared=1, units=1000, ccy="HKD")
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[1000.0]
        self.assertEqual(r["currency"], "HKD")
        self.assertEqual(r["gross"], 1000.0)                  # untouched
        self.assertEqual(r["gross_sgd"], 170.0)
        self.assertEqual(r["rate"], 1.0)                      # declared rate stays native
        self.assertEqual(r["flags"], [])

    def test_sgd_needs_no_fx_row(self):
        # SGD is intentionally absent from fx_rate — it must not be flagged as unpriced.
        self._div(D(2024, 6, 1), 80, declared=1, units=80)
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[80.0]
        self.assertEqual(r["gross_sgd"], 80.0)
        self.assertEqual(r["flags"], [])

    def test_currency_with_no_fx_rate_is_flagged_not_silently_passed_through(self):
        self._div(D(2024, 6, 1), 500, declared=1, units=500, ccy="EUR")   # no EUR fx row
        self.s.commit()
        res = dividends.details(self.s)
        r = self._by_gross(res)[500.0]
        self.assertIsNone(r["gross_sgd"])                      # never 500 unconverted
        self.assertIn("no FX rate for EUR", r["flags"])
        self.assertEqual(res["total_sgd"], 0)                  # excluded, not counted at 1:1

    def test_total_sgd_sums_the_converted_amounts(self):
        self._fx("HKD", 0.17)
        self._div(D(2024, 6, 1), 1000, declared=1, units=1000, ccy="HKD")  # 170
        self._div(D(2024, 7, 1), 30, declared=1, units=30)                 # 30
        self.s.commit()
        self.assertEqual(dividends.details(self.s)["total_sgd"], 200.0)

    def test_totals_are_rounded_once_not_summed_from_rounded_rows(self):
        # 0.03 HKD at 0.17 is 0.0051 SGD, which each row ships as 0.01. Three of them are
        # 0.0153 SGD — 0.02 — and a sum of the shipped rows would say 0.03.
        self._fx("HKD", 0.17)
        for m in (6, 7, 8):
            self._div(D(2024, m, 1), 0.03, declared=0.03, units=1, ccy="HKD")
        self.s.commit()
        res = dividends.details(self.s)
        self.assertEqual([r["gross_sgd"] for r in res["rows"]], [0.01, 0.01, 0.01])
        self.assertEqual(res["total_sgd"], 0.02)

    def test_flagged_sgd_totals_only_the_flagged_rows(self):
        # the page's flagged-only filter reads this rather than re-adding the rows it shows
        self._div(None, 30, declared=1, units=30)                          # flagged: no date
        self._div(D(2024, 7, 1), 70, declared=1, units=70)
        self.s.commit()
        res = dividends.details(self.s)
        self.assertEqual((res["flagged"], res["flagged_sgd"]), (1, 30.0))
        self.assertEqual((res["total"], res["total_sgd"]), (2, 100.0))

    def test_rows_sorted_pay_date_desc_nulls_first(self):
        # newest-first (reverse=True) over nulls_last, which sorts null dates last ascending ->
        # first descending. Undated dividends surface at the top for manual attention.
        self._div(D(2024, 1, 1), 10, declared=1, units=1)
        self._div(D(2024, 9, 1), 20, declared=1, units=1)
        self._div(None, 30, declared=1, units=1)
        self.s.commit()
        res = dividends.details(self.s)
        self.assertEqual(res["total"], 3)
        self.assertEqual([r["gross"] for r in res["rows"]], [30.0, 20.0, 10.0])  # null, then desc


if __name__ == "__main__":
    unittest.main()
