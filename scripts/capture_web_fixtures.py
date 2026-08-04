"""Derive the Playwright suite's API fixtures from the live database — once.

Run this against a locally-running API (`make api`, or uvicorn on any port) with the
dev auth bypass on. It walks every GET endpoint the frontend calls and writes the
response to `web/tests/fixtures/api/`. Those files are committed; the suite never
talks to Postgres or the network.

Why fixtures at all, rather than the real database: every measurement behind the
mobile-responsive spec is data-dependent, and this effort has already been burned by
that once — the Spending overview's top-line-items card measured 415px against
invented rows during planning and 519px against real ones. An assertion about a
measured width is meaningless untethered from fixed data.

Which is also why "derived from the live database" is load-bearing, and why this
script *enforces* the four pathological rows planning surfaced (see PATHOLOGICAL
below) rather than trusting them to show up. Three of the four land naturally in the
windows the frontend asks for; the 65-character merchant does not, so it is spliced
in from a targeted query against the same database — see `_ensure_long_merchant`.

Re-run only when the fixtures genuinely need to move. Regenerating them casually
re-tethers every measured assertion in the suite to whatever the database holds today.

Three fixtures are not reproducible byte-for-byte, because three endpoints compute against
`dt.date.today()`: `return.json` and every `xirr` in `positions.json` /
`positions-closed.json`. Two captures four days apart moved all four of `return.json`'s
computed fields — `xirr_annualised`, `twr_annualised`, `twr_cumulative` and
`value_plus_income_sgd` — and the `xirr` of most positions, while the database held no new
price, FX rate, dividend or transaction between them. Same rows in, different numbers out:
that is the clock, not the data.

Do not tighten this into "only annualised rates move". That reading was written here once
and is wrong — `value_plus_income_sgd` moved by 3,580 SGD and is not a rate, and the exact
path by which `portfolio/twr.py` turns a later `today` into a lower terminal valuation on
frozen data is not pinned down. What IS established is the direction to check in: a moved
number in these three files is worth a `git log` on the database's newest row before it is
worth reading as new data.

None of it changes a rendered width — 19.64% and 19.62% are the same number of characters —
so expect the churn in a recapture diff rather than going looking for a cause.

    PYTHONPATH=. .venv/bin/python -m uvicorn server.main:app --port 8123 &
    .venv/bin/python scripts/capture_web_fixtures.py --base http://localhost:8123
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "tests" / "fixtures" / "api"

# Every GET the frontend makes, as (fixture name, path). The path is exactly what the
# app requests, because the suite's route table keys on it. Where a view varies its
# query from a control (Performance's `by`, Holdings' closed-positions checkbox), each
# variant is captured so the suite can drive the control without falling off its data.
ENDPOINTS: list[tuple[str, str]] = [
    # --- auth ---
    ("auth-me", "/api/auth/me"),
    # --- portfolio ---
    ("overview", "/api/overview"),
    ("return", "/api/return"),
    ("options", "/api/options"),
    ("options-trades", "/api/options-trades?limit=500"),
    ("positions", "/api/positions"),
    ("positions-closed", "/api/positions?closed=true"),
    ("performance-market", "/api/performance?by=market"),
    ("performance-bucket", "/api/performance?by=bucket"),
    ("performance-account", "/api/performance?by=account"),
    ("dividends-annual", "/api/dividends-annual"),
    ("dividend-details", "/api/dividend-details"),
    ("accounts", "/api/accounts"),
    ("transactions", "/api/transactions?"),
    # SecurityDetail's only entry point. PLTR is deliberate: 73 option trades, the
    # longest options history in the database (see PATHOLOGICAL).
    ("holding-pltr", "/api/holding?ticker=PLTR&bucket=cash"),
    # --- net worth ---
    ("networth-items", "/api/networth/items"),
    ("networth-snapshots", "/api/networth/snapshots"),
    ("networth-latest", "/api/networth/latest"),
    # --- spending ---
    ("spending-summary", "/api/spending/summary"),
    ("spending-trends", "/api/spending/trends"),
    ("spending-years", "/api/spending/years"),
    ("spending-undated", "/api/spending/undated"),
    ("spending-categories", "/api/spending/categories"),
    ("spending-transactions", "/api/spending/transactions?limit=1000"),
    ("spending-recurring", "/api/spending/recurring"),
    ("spending-recurring-detect", "/api/spending/recurring/detect"),
    ("classify-unclassified", "/api/spending/classify/unclassified"),
    ("classify-rules", "/api/spending/classify/rules"),
    ("classify-categories", "/api/spending/classify/categories"),
]

# Per-snapshot and per-year paths depend on what the database holds, so they are
# discovered at capture time rather than hardcoded. Names are written into the
# manifest so the suite's route table can be checked against them.
DYNAMIC_NOTE = "discovered at capture time from the data itself"


# Endpoints that are *expected* to fail today, with the reason. A capture that hits an
# unlisted failure stops, because a fixture recording an accident would quietly turn a
# broken endpoint into the baseline. A listed one is recorded with its real status, so
# the suite measures the app as it actually behaves rather than as it should.
#
# Empty, and worth keeping empty: the one entry it ever held was `/api/spending/trends`,
# which sorted a category set containing the null-category row and raised `str < None`.
# Overview.jsx caught that into an empty trend, so the only symptom was a chart that was
# not there — the capture is what made it visible, and the capture is what will make the
# next one visible. Fixed in `portfolio/spending.py` (issue #35); the fixture now holds a
# real chart.
EXPECTED_FAILURES: dict[str, int] = {}


def fetch(base: str, path: str, *, allow_status: int | None = None):
    """Return (status, body). Non-200 is fatal unless it is the expected status."""
    req = urllib.request.Request(base + path, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read()
        if allow_status is not None and e.code == allow_status:
            try:
                return e.code, json.loads(body)
            except ValueError:
                return e.code, {"detail": body.decode("utf-8", "replace")[:200]}
        sys.exit(f"! {path} -> HTTP {e.code}. Is the dev auth bypass on?")
    except urllib.error.URLError as e:
        sys.exit(f"! {path} -> {e.reason}. Is the API running at {base}?")


def get(base: str, path: str) -> tuple[int, object]:
    """Fetch a path, returning (status, body). The status is what the server actually
    returned, not what EXPECTED_FAILURES predicted — which is how `/api/spending/trends`
    came back: the recapture after the fix recorded a 200 alongside the good body rather
    than serving a working response under a 500 and making the fix look like a regression."""
    status, body = fetch(base, path, allow_status=EXPECTED_FAILURES.get(path))
    if status != 200:
        print(f"  (recording HTTP {status} for {path} — a known failure, see EXPECTED_FAILURES)")
    elif path in EXPECTED_FAILURES:
        print(f"  (!) {path} now returns 200 — drop it from EXPECTED_FAILURES")
    return status, body


def write(name: str, payload) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n")
    size = (OUT / f"{name}.json").stat().st_size
    print(f"  {name}.json  ({size:,} bytes)")


# ---------------- the four pathological rows ----------------
# Each of these broke, or nearly broke, a measurement during planning. Fixtures that
# were merely *plausible* would reproduce the original error, so capture asserts they
# are present and fails loudly if the database no longer holds them.
#
# The same four are asserted again on every test run, from the committed files, in
# `web/tests/fixtures/index.js` (PATHOLOGICAL). Deliberately both: here it fails at the
# source, the moment a recapture would have quietly dropped one; there it fails for
# whoever hand-edits a fixture without ever running this script. Move a threshold in one
# place and move it in the other.

def _ensure_long_merchant(base: str, rows: list[dict]) -> list[dict]:
    """Splice in the longest merchant string if it fell outside the captured window.

    The Spending transactions view asks for the newest 1000 rows. The 65-character
    merchant sits older than that, so it is fetched from the same database by its own
    date window and merged back in. Without it the fixture's widest merchant is 64
    characters and the card-width assertions are measuring the wrong worst case.
    """
    longest = max((len(str(r.get("merchant") or "")) for r in rows), default=0)
    # No date window: ask for the whole ledger and let the data say where the worst row
    # is. A hardcoded window would stop finding it as the data ages, and would surface
    # three functions away as an unexplained pathological-row failure.
    _, everything = get(base, "/api/spending/transactions?limit=1000000")
    worst = max(everything, key=lambda r: len(str(r.get("merchant") or "")), default=None)
    if worst is None or len(str(worst.get("merchant") or "")) <= longest:
        return rows
    print(f"  + splicing the {len(worst['merchant'])}-char merchant row "
          f"({worst['txn_date']}) into spending-transactions")
    rows = rows + [worst]
    rows.sort(key=lambda r: str(r.get("txn_date") or ""), reverse=True)
    return rows


def check_pathological(captured: dict[str, object]) -> None:
    summary = captured["spending-summary"]
    trades = captured["options-trades"]
    txns = captured["spending-transactions"]
    holding = captured["holding-pltr"]

    subs = summary.get("by_subcategory") or []
    longest_sub = max((str(s.get("subcategory") or "") for s in subs), key=len, default="")
    groups = summary.get("by_group") or []
    longest_merchant = max((str(r.get("merchant") or "") for r in txns), key=len, default="")
    pltr_trades = [t for t in trades if t.get("underlying") == "PLTR"]

    checks = [
        # A 30-character subcategory name is what makes the top-line-items card need
        # 519px rather than the ~420px the .grid2 minimum optimistically assumes.
        (len(longest_sub) >= 30, f"longest subcategory is {len(longest_sub)} chars "
                                 f"({longest_sub!r}), expected >= 30"),
        # The longest options history in the app. It is what makes SecurityDetail's
        # options table the tallest table anywhere, and the reason SecurityDetail is
        # reached through PLTR rather than whatever sits first in the list.
        (len(pltr_trades) >= 73, f"PLTR has {len(pltr_trades)} option trades, expected >= 73"),
        # 65 characters of unbounded free text in a single cell. This is the row that
        # decides whether a table fits — the rule is "does any column hold unbounded
        # free text?", and this is that text at its worst.
        (len(longest_merchant) >= 65, f"longest merchant is {len(longest_merchant)} chars "
                                      f"({longest_merchant!r}), expected >= 65"),
        # Unclassified spend: category is NULL. It renders as "Uncategorized" and is
        # deliberately not drillable, so it is the one row in the category table with
        # a different shape — and the one a fabricated fixture would never contain.
        (any(g.get("category") is None for g in groups),
         "no null-category row in the spending summary"),
    ]
    # SecurityDetail is reached through PLTR precisely because of its options history. A
    # holding fixture that lost it would silently turn the tallest view in the app into
    # three short tables, and every measurement taken there would be of the wrong view.
    pltr_history = holding.get("options") or []
    checks.append((len(pltr_history) >= 73,
                   f"the holding-pltr fixture carries {len(pltr_history)} option trades, "
                   f"expected >= 73"))

    bad = [msg for ok, msg in checks if not ok]
    if bad:
        print("\n! the fixtures no longer carry the pathological rows they exist for:")
        for msg in bad:
            print(f"    - {msg}")
        sys.exit(1)
    print(f"\n  pathological rows present: {len(longest_sub)}-char subcategory, "
          f"PLTR x{len(pltr_trades)} option trades, {len(longest_merchant)}-char merchant, "
          f"null-category row")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8000",
                    help="base URL of a running API (default: http://localhost:8000)")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print(f"capturing from {base} -> {OUT.relative_to(ROOT)}/")
    captured: dict[str, object] = {}
    manifest: dict[str, dict] = {}

    def record(name: str, path: str, status: int, payload) -> None:
        captured[name] = payload
        manifest[path] = {"file": f"{name}.json", "status": status}
        write(name, payload)

    for name, path in ENDPOINTS:
        status, payload = get(base, path)
        if name == "spending-transactions":
            payload = _ensure_long_merchant(base, payload)
        record(name, path, status, payload)

    # Net-worth snapshot detail: the view opens the newest snapshot. Its id comes from
    # the snapshots list, so it cannot be written down ahead of time.
    for snap in captured["networth-snapshots"]:
        path = f"/api/networth/snapshots/{snap['id']}"
        record(f"networth-snapshot-{snap['id']}", path, *get(base, path))

    # By Category loads one calendar year at a time and defaults to the newest.
    for year in captured["spending-years"]:
        path = f"/api/spending/summary?from={year}-01-01&to={year}-12-31"
        record(f"spending-summary-{year}", path, *get(base, path))

    # The By Category drill-in, on the category holding the 30-character subcategory.
    # Captured so the drilled transaction list has real rows to measure rather than an
    # empty state that would pass every gate trivially.
    newest = captured["spending-years"][0]
    subs = captured["spending-summary"].get("by_subcategory") or []
    worst = max(subs, key=lambda s: len(str(s.get("subcategory") or "")))
    cat, sub = worst["category"], worst["subcategory"]
    path = (f"/api/spending/transactions?from={newest}-01-01&to={newest}-12-31"
            f"&group={urllib.parse.quote(cat)}&subcategory={urllib.parse.quote(sub)}&limit=1000")
    record("spending-transactions-drilled", path, *get(base, path))

    (OUT.parent / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"  manifest.json  ({len(manifest)} paths)")

    check_pathological(captured)
    print(f"\ncaptured {len(manifest)} responses. {DYNAMIC_NOTE.capitalize()} where ids "
          f"or years appear in the path.")


if __name__ == "__main__":
    main()
