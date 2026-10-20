"""portfolio.sgx._get — the SSL context it hands to urlopen — and sgx_schedule()'s per-ex-date
summing/component-breakdown.

SGX's cert chains to GlobalSign Root R46, missing from some platforms' default CA bundle
(macOS's /etc/ssl/cert.pem); certifi's bundle has it, so `_get` must open the request with a
certifi-backed SSLContext rather than the stdlib default. No live network here — `urlopen` is
mocked and the test only checks what context it was called with.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_sgx.py -q
"""
import datetime as dt
import json
import unittest
from unittest.mock import patch

from portfolio import sgx


class TestGet(unittest.TestCase):
    def test_uses_the_shared_certifi_backed_context(self):
        with patch("portfolio.sgx.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            mock_urlopen.return_value.read.return_value = b"{}"
            sgx._get("https://api.sgx.com/corporateactions/v1.0?cat=DIVIDEND")

        _, kwargs = mock_urlopen.call_args
        self.assertIs(kwargs["context"], sgx._SSL_CONTEXT)
        self.assertEqual(kwargs["context"].cert_store_stats()["x509_ca"] > 0, True)

    def test_returns_the_parsed_json_body(self):
        body = {"data": [{"name": "DBS"}]}
        with patch("portfolio.sgx.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.read.return_value = json.dumps(body).encode()
            result = sgx._get("https://api.sgx.com/corporateactions/v1.0?cat=DIVIDEND")

        self.assertEqual(result, body)


class TestSgxScheduleComponents(unittest.TestCase):
    """sgx_schedule()'s per-ex-date `components` breakdown — SBS Transit's real shape (the
    launch brief's captain's intent): an ordinary + a special line item on the same ex-date,
    summed into `inline` as before but also kept apart in `components` for the Dividends tab's
    split-entry UI to offer instead of a free-typed amount."""

    def _records(self, ex_ms, *lines, pay_ms=None, name="SBS TRANSIT LTD"):
        return [{"name": name, "anncType": "DIVIDEND", "exDate": ex_ms,
                 "datePaid": pay_ms, "particulars": line} for line in lines]

    def test_components_list_each_line_items_rate_unsummed(self):
        ex_ms = int(dt.datetime(2026, 8, 20, 12, 0, 0).timestamp() * 1000)
        pay_ms = int(dt.datetime(2026, 8, 28, 12, 0, 0).timestamp() * 1000)
        data = {"data": self._records(
            ex_ms, "Ordinary Dividend - Rate: SGD 0.0845 per unit",
            "Special Dividend - Rate: SGD 0.1597 per unit", pay_ms=pay_ms)}

        with patch.object(sgx, "_get", return_value=data):
            sched = sgx.sgx_schedule("SBS TRANSIT LTD")

        ex = sgx.epoch_date(ex_ms)
        self.assertAlmostEqual(sched[ex]["inline"], 0.2442, places=4)
        self.assertEqual(sched[ex]["components"],
                         [{"currency": "SGD", "amount_per_unit": 0.0845},
                          {"currency": "SGD", "amount_per_unit": 0.1597}])

    def test_a_single_line_item_ex_date_has_one_component(self):
        ex_ms = int(dt.datetime(2025, 5, 2, 12, 0, 0).timestamp() * 1000)
        data = {"data": self._records(ex_ms, "Rate: SGD 0.05 per unit", name="DBS")}

        with patch.object(sgx, "_get", return_value=data):
            sched = sgx.sgx_schedule("DBS")

        ex = sgx.epoch_date(ex_ms)
        self.assertEqual(sched[ex]["components"], [{"currency": "SGD", "amount_per_unit": 0.05}])


if __name__ == "__main__":
    unittest.main()
