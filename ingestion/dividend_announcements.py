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
import os
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


def _candidate_names(s, security_id):
    """The security's own name plus every alias, upper-cased and deduped, own name first."""
    rows = s.execute(text(
        "SELECT name FROM security WHERE id=:id "
        "UNION ALL SELECT alias FROM security_alias WHERE security_id=:id"),
        {"id": security_id}).scalars().all()
    seen, out = set(), []
    for n in rows:
        u = (n or "").strip().upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _resolve(s, security_id):
    """The first candidate name SGX recognizes, with its schedule — or (None, {})."""
    for name in _candidate_names(s, security_id):
        try:
            sched = sgx_schedule(name)
        except Exception as e:
            print(f"  sgx lookup failed for {name!r}: {type(e).__name__}")
            continue
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

    matched, unmatched, rows_written = [], [], 0
    for sid, tk in held:
        name, sched = _resolve(s, sid)
        if not name:
            unmatched.append(tk)
            continue
        matched.append(tk)
        for ex, slot in sched.items():
            # a cash/scrip election makes the regex-summed rate untrustworthy as THE cash
            # rate (see sgx_schedule's docstring) — skip it rather than store a guess.
            if slot["has_opt"] or not slot["inline"] or slot["inline"] <= 0 or ex < cutoff:
                continue
            s.merge(DividendAnnouncement(
                security_id=sid, ex_date=ex, pay_date=slot["pay"],
                amount_per_unit=round(slot["inline"], 6), currency=slot["ccy"] or "SGD",
                source="sgx"))
            rows_written += 1
    s.commit()
    print(f"dividend announcements: {len(matched)} securities matched ({rows_written} rows), "
          f"{len(unmatched)} unmatched: {unmatched}")
    s.close()
    return {"matched": matched, "unmatched": unmatched, "rows": rows_written}


if __name__ == "__main__":
    main()
