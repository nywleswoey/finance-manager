"""portfolio.sgx._get — the SSL context it hands to urlopen.

SGX's cert chains to GlobalSign Root R46, missing from some platforms' default CA bundle
(macOS's /etc/ssl/cert.pem); certifi's bundle has it, so `_get` must open the request with a
certifi-backed SSLContext rather than the stdlib default. No live network here — `urlopen` is
mocked and the test only checks what context it was called with.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_sgx.py -q
"""
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


if __name__ == "__main__":
    unittest.main()
