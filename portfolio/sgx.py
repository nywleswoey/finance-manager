"""SGX corporate-actions dividend schedule — shared by build/fetch_cpf_srs_dividends.py (the
CPF/SRS backfill) and ingestion/dividend_announcements.py (the Dividends tab's `<year>
expected` projection).

`sgx_schedule(name)` is keyed by the security's exact, case-sensitive legal name as SGX's API
matches it server-side (an unrecognized name returns the WHOLE unfiltered dataset rather than
an empty one, so callers must not treat a non-empty result as proof of a match on its own —
compare `r["name"]` against what was asked for, which this function already does).
"""
import json
import re
import urllib.parse
import urllib.request
import datetime as dt

RATE_RX = re.compile(r"\b(SGD|USD|EUR|HKD)\s*([0-9]+(?:\.[0-9]+)?)")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def epoch_date(ms):
    return dt.date.fromtimestamp(ms / 1000) if ms else None


def sgx_schedule(name):
    """{exDate: {pay, ccy, inline, has_opt}} for `name`'s declared cash dividends.

    `inline` sums every SGD/USD/EUR/HKD rate regex-matched out of the announcement's
    `particulars` text for that ex-date (a dividend split across several line items, e.g. an
    ordinary + special rate, sums to the total per-unit cash rate). `has_opt` flags a
    cash/scrip election, where `inline` alone cannot be trusted as the cash rate a holder
    without the scrip option actually receives — callers skip those rather than guess."""
    url = "https://api.sgx.com/corporateactions/v1.0?cat=DIVIDEND&name=" + urllib.parse.quote(name)
    data = _get(url).get("data") or []
    by_ex, seen = {}, set()
    for r in data:
        if r.get("name") != name or r.get("anncType") != "DIVIDEND":
            continue
        ex = epoch_date(r.get("exDate"))
        if not ex:
            continue
        slot = by_ex.setdefault(ex, {"pay": epoch_date(r.get("datePaid")) or epoch_date(r.get("recDate")) or ex,
                                     "ccy": None, "inline": 0.0, "has_opt": False})
        part = r.get("particulars") or ""
        if "Cash Option" in part or "Scrip" in part:
            slot["has_opt"] = True
        m = RATE_RX.search(part)
        if m:
            dkey = (ex, m.group(1), round(float(m.group(2)), 8))
            if dkey in seen:
                continue
            seen.add(dkey)
            slot["ccy"] = slot["ccy"] or m.group(1)
            slot["inline"] = round(slot["inline"] + float(m.group(2)), 8)
    return by_ex
