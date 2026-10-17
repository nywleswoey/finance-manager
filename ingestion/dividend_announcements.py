"""SGX-announced dividends for every CURRENTLY HELD SG security -> `dividend_announcement`.

Feeds the Dividends tab's `<year> expected` projection (portfolio.dividends.projected):
for the rest of the year, a holding's remaining payments use the SGX-declared rate where
one exists here, falling back to last year's payment pattern otherwise. Cached like
ingestion.prices' `price`/`fx_rate` rather than hit per page load. Run:
  PYTHONPATH=. .venv/bin/python -m ingestion.dividend_announcements

SGX's corporate-actions API filters by a security's exact legal name (no ticker/code
param works — unrecognized ones are silently ignored and the WHOLE unfiltered history comes
back). There is no name column seeded for this: `security.name` and its `security_alias` rows
are harvested from brokers' own statement text, which routinely echoes the exchange's
registered name on a dividend line (build/fetch_cpf_srs_dividends.py's curated SEC dict is the
same names, by hand, for the 7 CPF/SRS counters it backfills). So each holding tries its own
name plus every alias as a candidate and keeps the first that SGX actually recognizes
(`sgx_schedule` returns a non-empty schedule only when the name matched — see its docstring).
A holding with no matching candidate is left with nothing here, and `projected()` falls back
to last year's pattern for it — the required graceful degradation, not a special case.
"""
import datetime as dt
import http.client
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import text

from ingestion.prices import sg_today
from portfolio.db import SessionLocal
from portfolio.models import DividendAnnouncement
from portfolio.sgx import sgx_schedule

# how far back to keep: enough to cross-check against, not the security's whole SGX history
LOOKBACK_YEARS = 1

# a broker statement's dividend line routinely appends one of these to the security's own
# name (e.g. "DBS Group Holdings Ltd Cash Dividend") rather than giving the bare name itself
_DIVIDEND_LINE_SUFFIX_RX = re.compile(
    r"\s+(cash dividend|scrip dividend option|cash in lieu)$", re.IGNORECASE)


def _strip_dividend_suffix(name):
    """Strip a trailing broker dividend-line suffix (e.g. ' Cash Dividend') from `name`."""
    return _DIVIDEND_LINE_SUFFIX_RX.sub("", name)


def _looks_like_sgx_code(name):
    """True for a bare SGX stock/fund code (e.g. 'C', 'D05', '0P0001OOJG') rather than a
    plausible SGX registered company name. SGX's corporate-actions API ignores ticker/code
    params (see module docstring), so querying by one is a pointless request."""
    return (
        name and " " not in name
        and (len(name) <= 4 or any(c.isdigit() for c in name))
    )


def _candidate_names(s, security_id):
    """The security's own name, then every alias that is a plausible SGX registered name,
    upper-cased and deduped. The own name is never filtered or stripped - it is trusted
    as-is and always tried first; aliases that are bare SGX codes are dropped, and broker
    dividend-line suffixes are stripped before dedup, so they collapse onto a name already
    in the list rather than firing a separate, doomed lookup."""
    own = s.execute(text("SELECT name FROM security WHERE id=:id"), {"id": security_id}).scalar()
    aliases = s.execute(text(
        "SELECT alias FROM security_alias WHERE security_id=:id"), {"id": security_id}).scalars().all()

    seen, out = set(), []
    own_u = (own or "").strip().upper()
    if own_u:
        seen.add(own_u)
        out.append(own_u)
    for a in aliases:
        stripped = _strip_dividend_suffix((a or "").strip())
        if not stripped or _looks_like_sgx_code(stripped):
            continue
        u = stripped.upper()
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


class SgxUnavailable(RuntimeError):
    """The SGX request itself failed (network, TLS, timeout, unparseable reply)."""


def _resolve(s, security_id):
    """The first candidate name SGX recognizes, with its schedule - or (None, {}).

    A transport failure (the SGX request itself failing, as opposed to SGX answering with
    no match for that name) is raised rather than swallowed: it tells us nothing about
    whether SGX would have recognized that name, so retrying every remaining candidate just
    repeats the same failing request under a different name.
    """
    for name in _candidate_names(s, security_id):
        try:
            sched = sgx_schedule(name)
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise SgxUnavailable(f"sgx lookup failed for {name!r}: {type(e).__name__}: {e}") from e
        time.sleep(0.2)
        if sched:
            return name, sched
    return None, {}


def main(today=None):
    today = today or sg_today()
    cutoff = dt.date(today.year - LOOKBACK_YEARS, 1, 1)
    s = SessionLocal()
    held = s.execute(text(
        "SELECT DISTINCT security_id, canonical_ticker FROM current_position "
        "WHERE market='SG' AND asset_type != 'fund'")).all()

    matched, unmatched, rows_written, failure = [], [], 0, None
    for sid, tk in held:
        try:
            name, sched = _resolve(s, sid)
        except SgxUnavailable as e:
            failure = e
            break
        if not name:
            unmatched.append(tk)
            continue
        matched.append(tk)
        for ex, slot in sched.items():
            # a cash/scrip election makes the regex-summed rate untrustworthy as THE cash
            # rate (see sgx_schedule's docstring) - skip it rather than store a guess.
            if slot["has_opt"] or not slot["inline"] or slot["inline"] <= 0 or ex < cutoff:
                continue
            s.merge(DividendAnnouncement(
                security_id=sid, ex_date=ex, pay_date=slot["pay"],
                amount_per_unit=round(slot["inline"], 6), currency=slot["ccy"] or "SGD",
                source="sgx"))
            rows_written += 1
    s.commit()
    summary = (f"dividend announcements: {len(matched)} securities matched ({rows_written} rows), "
               f"{len(unmatched)} unmatched: {unmatched}")
    if failure:
        unresolved = len(held) - len(matched) - len(unmatched)
        summary += (f"; stopped on {failure} - the {unresolved} unresolved holdings fall back "
                    f"to last year's pattern")
    print(summary)
    s.close()
    return {"matched": matched, "unmatched": unmatched, "rows": rows_written}

if __name__ == "__main__":
    main()
