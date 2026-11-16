"""Price refresh: the signed-in UI's POST and the Vercel Cron's GET, one implementation.

Both run `ingestion.prices.main()` (upserts price / fx_rate for every current position) and
then clear the portfolio fold's memo so the next /api/overview recomputes at the new prices.
The cron route is the one hole in the cookie gate — `server.main` lists CRON_PATH as public —
so it authenticates itself against CRON_SECRET here. Tests: tests/test_cron.py.
"""
import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ingestion import prices
from portfolio.config import settings
from server.routes.portfolio import _cache

router = APIRouter()
log = logging.getLogger("api")

CRON_PATH = "/api/cron/refresh-prices"


def _refresh_prices():
    """Fetch latest prices + FX for held tickers, then invalidate the cache."""
    # called through the module so tests can stub `prices.main` without the network
    result = prices.main()    # blocking; upserts price/fx_rate for current_position
    _cache.clear()            # next overview/positions recompute with fresh prices
    return result             # {ok, fail, date, failed, fx_failed}


@router.post("/api/refresh-prices")
def refresh_prices():
    """Manual refresh from the signed-in UI."""
    return _refresh_prices()


@router.get(CRON_PATH)
def cron_refresh_prices(request: Request):
    """The same refresh, on a schedule (Vercel Cron — see DEPLOY.md §6).

    GET, because Vercel invokes a cron path with GET and nothing else; this is the one route
    where a mutating GET is not a choice. It bypasses the cookie gate (a cron request has no
    session) and instead compares the `Authorization: Bearer <CRON_SECRET>` header Vercel
    sends against the env var — constant-time, and denying when CRON_SECRET is unset, so a
    project that never set it has a dead route rather than an open one (SECURITY-15).

    A cloud run prices stocks + FX only: the Endowus NAV is scraped from a statement PDF in
    data/, which is gitignored and therefore absent from the deployment. That one fund's NAV
    moves only on the local scheduled run.
    """
    expected, got = settings.cron_secret, request.headers.get("authorization", "")
    if not expected or not hmac.compare_digest(got, f"Bearer {expected}"):
        log.warning("cron refresh-prices denied ua=%s", request.headers.get("user-agent", ""))
        return JSONResponse({"detail": "not authenticated"}, status_code=401)
    result = _refresh_prices()
    log.info("cron refresh-prices: %s", result)
    return result
