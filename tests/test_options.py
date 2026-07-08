"""Option reconciliation from Tiger flex legs -> contracts. Pure-function tests (no DB).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_options.py -q
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ingestion.parse_options import _SYM, _expiry, _reconcile, _und, money


class _Acct:
    id = 1


def leg(**kw):
    base = dict(underlying="PLTR", expiry=dt.date(2099, 1, 1), option_type="put", strike=10.0,
                market="US", mult=100, qty=1.0, price=1.0, fees=1.0, realized=0.0,
                trade_date=dt.date(2024, 1, 1), is_open=True)
    base.update(kw)
    return base


class HelperTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(money("$15.50"), 15.5)
        self.assertEqual(money("($6.80)"), -6.8)      # parens => negative
        self.assertEqual(money(" $0.00   "), 0.0)
        self.assertIsNone(money(""))

    def test_und_hk_suffix(self):
        self.assertEqual(_und("lnk.hk"), "LNK")       # HK counter suffix stripped
        self.assertEqual(_und("AMD"), "AMD")

    def test_expiry_yyyymmdd(self):
        self.assertEqual(_expiry("20260710"), dt.date(2026, 7, 10))
        self.assertIsNone(_expiry("bad"))

    def test_symbol_regex_both_forms(self):
        bare = _SYM.search("AMD 20210917 PUT 77.5").groups()
        self.assertEqual(bare, ("AMD", "20210917", "PUT", "77.5"))
        wrapped = _SYM.search("Advanced Micro Devices (AMD 20260109 PUT 205.0)").groups()
        self.assertEqual(wrapped, ("AMD", "20260109", "PUT", "205.0"))
        hk = _SYM.search("LNK.HK 20240927 PUT 35.0").groups()
        self.assertEqual(hk[0], "LNK.HK")


class ReconcileTest(unittest.TestCase):
    def one(self, legs):
        rows = _reconcile(legs, _Acct(), {})
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_expired_worthless_keeps_premium(self):
        # sold 2 puts @ $1.50, $3 fees, expired (past expiry, no close leg)
        r = self.one([leg(qty=2.0, price=1.5, fees=3.0, is_open=True,
                          expiry=dt.date(2024, 1, 19))])
        self.assertEqual(r["outcome"], "expired")
        self.assertEqual(r["contracts"], 2.0)
        # premium_open = 1.5/share ; realized = 1.5*2*100 - 3
        self.assertAlmostEqual(r["premium_open"], 1.5)
        self.assertAlmostEqual(r["realized_pl"], 1.5 * 2 * 100 - 3.0)

    def test_closed_uses_tiger_realized(self):
        open_leg = leg(qty=1.0, price=2.0, fees=1.0, is_open=True, trade_date=dt.date(2024, 1, 1),
                       expiry=dt.date(2024, 3, 15))
        close_leg = leg(qty=1.0, price=0.5, fees=1.0, is_open=False, realized=148.0,
                        trade_date=dt.date(2024, 2, 1), expiry=dt.date(2024, 3, 15))
        r = self.one([open_leg, close_leg])
        self.assertEqual(r["outcome"], "closed")
        self.assertAlmostEqual(r["realized_pl"], 148.0)          # Tiger's figure, not recomputed
        self.assertAlmostEqual(r["premium_close"], 0.5)
        self.assertEqual(r["close_date"], dt.date(2024, 2, 1))

    def test_open_unexpired_is_none(self):
        r = self.one([leg(is_open=True, expiry=dt.date(2099, 12, 31))])
        self.assertEqual(r["outcome"], "open")
        self.assertIsNone(r["realized_pl"])

    def test_activity_split_by_contract_key(self):
        # two different strikes -> two contracts
        rows = _reconcile([leg(strike=10.0), leg(strike=12.0)], _Acct(), {})
        self.assertEqual(len(rows), 2)

    def test_weighted_premium_across_multiple_opens(self):
        r = self.one([leg(qty=1.0, price=1.0, expiry=dt.date(2024, 1, 19)),
                      leg(qty=3.0, price=2.0, expiry=dt.date(2024, 1, 19))])
        self.assertEqual(r["contracts"], 4.0)
        self.assertAlmostEqual(r["premium_open"], (1.0 * 1 + 2.0 * 3) / 4)   # weighted = 1.75


if __name__ == "__main__":
    unittest.main()
