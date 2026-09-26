"""Derive the Playwright suite's API fixtures from the live database — once.

Run this against the docker-DB API (`make api-local`, :8001) with the dev auth bypass on.
NOT `make api` (:8000): that serves the deployed Neon DB, and this would capture production. It walks every GET endpoint the frontend calls and writes the
response to `web/tests/fixtures/api/`. Those files are committed; the suite never
talks to Postgres or the network.

Why fixtures at all, rather than the real database: every measurement behind the
mobile-responsive spec is data-dependent, and this effort has already been burned by
that once — the Spending overview's top-line-items card measured 415px against
invented rows during planning and 519px against real ones. An assertion about a
measured width is meaningless untethered from fixed data.

Which is also why "derived from the live database" is load-bearing, and why this
script *enforces* the pathological rows planning surfaced (see `check_pathological`
below) rather than trusting them to show up. Most of them land naturally in the
windows the frontend asks for; the 65-character merchant does not, so it is spliced
in from a targeted query against the same database — see `_ensure_long_merchant`.

Re-run only when the fixtures genuinely need to move. Regenerating them casually
re-tethers every measured assertion in the suite to whatever the database holds today.

Two fixtures are not reproducible byte-for-byte: `return.json`, and every `xirr` in
`positions-closed.json`. They move for three different reasons, and a recapture diff is only
readable if you keep them apart (issues #52 and #56, which are where the numbers below come
from). It was three until #155 stopped capturing `/api/positions` without `?closed=true` —
`positions.json` is referred to below as the fixture the measurements were taken against, which
is history rather than a live path.

1. The clock alone. `twr_annualised` raises a fixed total return to `1/years`, and `xirr`
   / `xirr_annualised` re-solve with the terminal inflow discounted over a longer span —
   so both drift downward on a book that is standing still. Correct arithmetic, nothing to
   investigate. This was the only reason `positions.json` moved across the four-day capture
   #52 measured: its `price`, `mv_native` and `mv_sgd` were byte-identical there.

2. The price ingest running. Those same `price` / `mv_native` / `mv_sgd` fields — and
   `as_of` — come from the `price` and `fx_rate` tables via `latest_close` and `fx_map`, so
   they move when, and only when, a row lands in either. `ingestion/prices.py` writes both
   (`POST /api/refresh-prices`, the local scheduled run, the Vercel cron). They were frozen
   across #52's capture because nothing had ingested in that window, which is a fact about
   that window and not a property of the endpoint. Under a daily schedule, expect every
   priced row to move on every recapture, and `as_of` to be roughly today.

3. The clock reaching a Yahoo close. `portfolio/twr.py` fetches `return.json`'s whole daily
   price and FX series live from Yahoo on every call; it does not read the `price` table
   (only its `last_px` fallback does, for funds and delisted tickers Yahoo cannot price).
   So "the database gained no rows" does not pin `return.json` at all. Advancing `today` is
   the trigger — `ffill` truncates the series at today, so a close Yahoo has already
   printed is invisible until the date reaches it — but Yahoo, not the clock, is the source
   of the new number. That is the likeliest account of the 3,580 SGD in
   `value_plus_income_sgd`: inference from where the prices come from, not something
   re-measured against the original captures, which are gone.

Which gives the split to read a diff by. Run against the real book with the Yahoo series
truncated so no close lands between the two dates, four days apart:

    xirr_annualised     0.1339 -> 0.1336   moved
    twr_annualised      0.0772 -> 0.0771   moved
    twr_cumulative      0.991  -> 0.991
    value_plus_income_sgd  2142504 -> 2142504
    invested_sgd           1634953 -> 1634953

So `twr_cumulative`, `value_plus_income_sgd`, `invested_sgd` and `from` do NOT move while no
close lands. If they have moved, one did — check Yahoo, not the database, because the
database is not where this endpoint gets its prices. Note this is NOT the old "only
annualised rates move" reading the header used to carry and #52 warned off: that one was
unconditional and false. This one is conditional on the price series, and the condition is
the whole point. `tests/test_twr.py` holds both halves as regression tests.

(The two valuation paths disagreeing is a real inconsistency — `/api/return` can report a
market value `/api/positions` does not, and #56 measured 29,451 SGD of it — but it is a
live-correctness question, out of scope for the fixtures. ADR 0001 already records the split
price source as deliberate, so this is a question about the two endpoints agreeing, not about
the design; #56 answers it by ingest plus an `as_of` on each side rather than by unifying
them. Which is also why reasons 2 and 3 are separate above: each endpoint now states the
moment it is speaking about, so a diff where the two `as_of` values move apart is the same
divergence showing up in the fixtures.)

None of it changes a rendered width — 19.64% and 19.62% are the same number of characters —
so expect the churn in a recapture diff rather than going looking for a cause.

An input ingested after the capture is the other cause of a diff, and it reaches every fixture,
not only the two above. A row that lands after a capture moves every value derived from it on
the next recapture, and the row can carry a date from before the capture, so a fixture's own
dates do not rule it out. Issue #213 is the example, AMD's `return_span_days` in
`positions-closed.json`:

    1946  code before #202 (first event to last), book as captured on 2026-09-20:
          2021-04-14, the first AMD contract, to 2026-08-12, the last one then in the book
    1983  the same code on the book after the AMD put opened 2026-09-17, expiring
          2026-09-18, was ingested: 2021-04-14 to 2026-09-18
     584  the #202 held-interval code on that same book, the value the fixture now holds

AMD is closed, so the run date moves none of these. The input moved the value by 37 days
(1946 to 1983), and deleting that one contract gives 1946 back. #213's "33 days" came from
subtracting a 4-day run-date shift from 1983, and that shift applies only to open names.

To sort a recapture diff: run the code that made the old fixture against today's book with
`dt.date.today()` pinned to the old capture date. A value that still differs from the old
fixture is an input change; one that matches moved with the clock. Where that code and the
current code disagree on the same book and pinned date, the change is behaviour. The
2026-09-25 recapture sorted this way had no unexplained value. AMD was input and then
behaviour, and every other value was clock, input, or both.

Should capture be checked rather than left to memory? Yes. Recommended, but not built: drift is
silent, #213 was found by accident, and hand-edited values (#211 edited its spans by hand) mix
captured and derived numbers in one file. A possible follow-up is a `--check` mode that
captures into a temp directory, runs the sort above, and fails on any behaviour change or
unexplained value. It needs the docker book, so it is a local pre-merge step, not a CI one.
Until then, recapture rather than hand-edit when a change moves a fixture value.

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
    # ONE positions route, not two. Holdings asks for `?closed=true` unconditionally (#143
    # §15) — the ticker fold covers the whole ticker whatever the "Show closed positions"
    # checkbox says, so every leg has to be in hand before any row is hidden — and Holdings is
    # this endpoint's only caller in `web/`. The no-parameter route is therefore never
    # requested by the app, so capturing it would commit a fixture nothing can reach. The
    # `closed` parameter stays on the endpoint as API surface.
    ("positions-closed", "/api/positions?closed=true"),
    ("performance-market", "/api/performance?by=market"),
    ("performance-bucket", "/api/performance?by=bucket"),
    ("performance-account", "/api/performance?by=account"),
    ("dividends-annual", "/api/dividends-annual"),
    ("dividend-details", "/api/dividend-details"),
    ("accounts", "/api/accounts"),
    ("transactions", "/api/transactions?"),
    # --- the detail page: nine tickers, and every one of them the only thing that reaches
    # what it reaches (#143, Testing Decisions tier 2). Not "a few representative names": each
    # line below closes a render state no other ticker in the book can.
    #
    # PLTR      the plain hero, the 3-row reconciliation block, and 73 option trades — the
    #           longest options history in the database, which is what makes this page the
    #           tallest view in the app (see PATHOLOGICAL).
    # AAPL      the no-capital hero, and a Dividends row: `holding-pltr.json`'s `dividends`
    #           is `[]` and PLTR structurally cannot have one. Also a hero carrying latest FX.
    # Q01       the caveat — `stock_pl_sgd` carrying a nulled realised/unrealised pair, tiles
    #           reading `not known`, the two-sided percentage sentence. The only caveat in the
    #           book whose uncosted lot is still HELD.
    # F34       multi-bucket columns, the closed-leg measured `0.0`, the dated carry, and the
    #           cross-page gate (Holdings' ticker-mode Net === this payload's summary Net).
    #           Load-bearing three times; single-bucket PLTR cannot carry the cross-page gate
    #           because Σ over one element proves nothing about the fold.
    # TSLA      all-options reconciliation, and the first closed-ticker page any test renders.
    # 9CI       `bounded` with a LOWER bound (`≥`) — a split carry that landed here.
    # C38U      `bounded` with an UPPER bound (`≤`), naming a sibling the reader can reach.
    # ASTREA6B  the only refusal in the book, and the only page with no bottom line.
    # UD1U      income paid in EUR and SGD on an SGD-quoted name. The fold converts each
    #           dividend at its own currency; this payload is what a gate can see that on.
    ("holding-pltr", "/api/holding?ticker=PLTR"),
    ("holding-aapl", "/api/holding?ticker=AAPL"),
    ("holding-q01", "/api/holding?ticker=Q01"),
    ("holding-f34", "/api/holding?ticker=F34"),
    ("holding-tsla", "/api/holding?ticker=TSLA"),
    ("holding-9ci", "/api/holding?ticker=9CI"),
    ("holding-c38u", "/api/holding?ticker=C38U"),
    ("holding-astrea6b", "/api/holding?ticker=ASTREA6B"),
    ("holding-ud1u", "/api/holding?ticker=UD1U"),
    # --- net worth ---
    ("networth-items", "/api/networth/items"),
    ("networth-snapshots", "/api/networth/snapshots"),
    ("networth-latest", "/api/networth/latest"),
    # The composition chart's band-level history. Its own path rather than a widened
    # /snapshots — see portfolio.networth.composition — which also keeps this key free of a
    # date, so a recapture writes the same key and the unmatched-paths gate keeps holding.
    ("networth-composition", "/api/networth/composition"),
    # --- spending ---
    ("spending-summary", "/api/spending/summary"),
    ("spending-trends", "/api/spending/trends"),
    # The spend-trend chart's window rule. Its own path rather than a parameter on
    # `/api/spending/trends` partly for this table: the route key would carry a date, and a
    # dated key goes stale the moment the ledger gains a month.
    ("spending-window", "/api/spending/window"),
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


# ---------------- the seven pathological rows ----------------
# Each of these broke, or nearly broke, a measurement during planning. Fixtures that
# were merely *plausible* would reproduce the original error, so capture asserts they
# are present and fails loudly if the database no longer holds them.
#
# The same seven are asserted again on every test run, from the committed files, in
# `web/tests/fixtures/index.js` (PATHOLOGICAL). Deliberately both: here it fails at the
# source, the moment a recapture would have quietly dropped one; there it fails for
# whoever hand-edits a fixture without ever running this script. Move a threshold in one
# place and move it in the other, and ADD A ROW IN BOTH — the duplication is the point.

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


def _flat_series_span_px(trends: dict, window: dict, plot_px: float = 140.0) -> tuple[str, float]:
    """The spend trend's counterfactual: how many pixels the SMALLEST of the four series
    would get if all four shared one y-axis floored at zero.

    This is the measurement the small-multiples form was chosen on, so it is the one thing
    that can make `charts.spec.js`'s "none is flattened onto the floor" gate vacuous — a
    window whose four series happened to agree in magnitude would pass that gate under a
    shared axis too. 140 is the panel plot height (`SpendTrend.jsx`'s PANEL_H).

    Returns the worst series and its span in pixels. With no window there is nothing to
    measure and the caller is told so by an empty name.
    """
    start, end = window.get("start"), window.get("end")
    if not start or not end:
        return "", float("inf")
    rows = [r for r in trends["series"] if start <= r["ym"] <= end]
    spans = {g: (min(float(r.get(g) or 0) for r in rows), max(float(r.get(g) or 0) for r in rows))
             for g in trends["groups"]}
    ceiling = max(hi for _, hi in spans.values())
    worst = min(spans, key=lambda g: spans[g][1] - spans[g][0])
    lo, hi = spans[worst]
    return worst, (hi - lo) / ceiling * plot_px if ceiling else float("inf")


def check_pathological(captured: dict[str, object]) -> None:
    summary = captured["spending-summary"]
    trades = captured["options-trades"]
    txns = captured["spending-transactions"]
    holding = captured["holding-pltr"]
    refusal = captured["holding-astrea6b"]
    positions = captured["positions-closed"]

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
    # The ~150x spread across the four spend categories inside the trend's own window. It is
    # what makes the spend trend four panels rather than one chart, and a capture that lost
    # it would leave the "no series is flattened onto the floor" gate passing against data a
    # shared axis would also have passed.
    flat_series, flat_px = _flat_series_span_px(captured["spending-trends"], captured["spending-window"])
    checks.append((flat_px < 5,
                   f"the four spend series no longer span two orders of magnitude inside the "
                   f"window: {flat_series or 'no window'} would draw {flat_px:.1f}px of a 140px "
                   f"plot under a shared axis, expected < 5"))
    # SecurityDetail is reached through PLTR precisely because of its options history. A
    # holding fixture that lost it would silently turn the tallest view in the app into
    # three short tables, and every measurement taken there would be of the wrong view.
    pltr_history = holding.get("options") or []
    checks.append((len(pltr_history) >= 73,
                   f"the holding-pltr fixture carries {len(pltr_history)} option trades, "
                   f"expected >= 73"))
    # THE REFUSAL, AS TWO CHECKS AND NOT ONE. ASTREA6B is the only name in the book whose entering
    # units have no recorded cost, so the only page with no bottom line — and the page is reachable
    # only through its Holdings row, because `SecurityDetail` is component state with one caller.
    # Each half is useless without the other, which is why they are counted separately: two checks
    # name WHICH half went missing, where one could only say the state is gone.
    refusal_summary = (refusal or {}).get("summary") or {}
    checks.append((refusal_summary.get("net_verdict") == "refuse"
                   and refusal_summary.get("net_pl_sgd") is None,
                   f"holding-astrea6b is no longer a refusal on the wire: net_verdict="
                   f"{refusal_summary.get('net_verdict')!r}, "
                   f"net_pl_sgd={refusal_summary.get('net_pl_sgd')!r}"))
    refusal_rows = [r for r in (positions.get("positions") or [])
                    if r.get("net_verdict") == "refuse"]
    checks.append((bool(refusal_rows),
                   f"positions-closed carries no refusing row, so no test can click through to "
                   f"the refusal page ({len(positions.get('positions') or [])} rows captured)"))

    bad = [msg for ok, msg in checks if not ok]
    if bad:
        print("\n! the fixtures no longer carry the pathological rows they exist for:")
        for msg in bad:
            print(f"    - {msg}")
        sys.exit(1)
    print(f"\n  pathological rows present: {len(longest_sub)}-char subcategory, "
          f"PLTR x{len(pltr_trades)} option trades, {len(longest_merchant)}-char merchant, "
          f"null-category row, {flat_series} at {flat_px:.1f}px under a shared axis, "
          f"the refusal on the wire and as a Holdings row "
          f"({', '.join(r['ticker'] for r in refusal_rows) or 'none'})")


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
