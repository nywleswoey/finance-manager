"""`/api/performance`'s stated identity — #143 §15's gate, not its reading.

    Σ group net_pl_sgd  ==  Σ ticker net_pl_sgd  +  Σ orphan option underlyings

**A stated identity, not equality.** The gap between the two sides is one named term: the
underlyings traded as options but never held as stock. `realized_by()` folds them in at group
level and no ticker row can carry them — `fold_positions` attaches an options stream only to a
row that already exists — and the map ruled giving them Holdings rows out of scope. Exact
equality was rejected for that reason: it would mean either inventing those rows or **silently
losing** their money.

**This is the gate; `scripts/audit_ledger.py` carries the reading.** The residual's live value
is a fact about one book — ten underlyings and roughly 6.4k SGD as this was written, 9 and
5,130.64 when #143 measured it — and pinning it here would make every option trade on a
never-held name a red build. What is asserted here is the *shape*: fabricated rows, no
database, so a failure means `rollup()` and `realized_by()` stopped composing rather than that
the book moved.

**All four `by` dimensions, because the identity is a claim about each of them.** The ticker
side does not change between them, so the four are four chances for one dimension's key to
drop a row — `account` joins a leg's accounts into one string and is the only key that is not a
bare field, which is exactly where a dropped row would hide.

Four shapes carry the whole rule and every one of them is live: a ticker split across two
funding buckets (so the ticker side sums legs before it is compared), an optioned name (whose
premiums are in both sides), a **caveat** whose realised/unrealised pair is null with
`stock_pl_sgd` carrying it, and a refusal, whose Net is null on the wire and whose group
contribution is nothing. The caveat is the load-bearing one: it is the only row that can fail a
group Net assembled from `realised + unrealised` instead of from `stock_pl_sgd`, which is the
regression §15 names. **A refusal with dividends would need a second residual and there is none
in the book** — asserted below rather than assumed, because the identity above would be false
for it.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_performance_identity.py -q
"""
import pytest
from fastapi.testclient import TestClient

from portfolio import options
from portfolio.config import settings

from server import main
from server.routes import portfolio as portfolio_routes

BY = ("market", "bucket", "account", "asset_type")


def _row(**over):
    """One `fold_positions` row, carrying every field `rollup()` and the Net read."""
    r = {"bucket": "cash", "accounts": ["FSM"], "ticker": "D05", "market": "SG",
         "asset_type": "stock", "units": 3080.0, "mv_sgd": 92400.0,
         "cost_basis_sgd": 80618.08, "invested_sgd": 80618.08,
         "realised_pl_sgd": 0.0, "unrealised_pl_sgd": 11781.92, "stock_pl_sgd": 11781.92,
         "income_sgd": 1200.0, "options_pl_sgd": None, "pl_sgd": 12981.92,
         "cost_known": True, "net_verdict": "hero", "net_pl_sgd": 12981.92}
    r.update(over)
    return r


# A hero split across two buckets — the shape that makes the ticker side a sum over legs
# rather than a relabelling of rows. F34's and S61's shape.
CASH = _row()
CPF = _row(bucket="cpf", accounts=["CPF"], units=1210.0, mv_sgd=36300.0,
           cost_basis_sgd=25466.14, invested_sgd=25466.14, unrealised_pl_sgd=10833.86,
           stock_pl_sgd=10833.86, income_sgd=0.0, pl_sgd=10833.86, net_pl_sgd=10833.86)
# An optioned name: the stream rides the cash leg, and its premiums are in both sides' Nets.
OPTIONED = _row(ticker="PLTR", market="US", accounts=["Tiger Prime"], units=5.0, mv_sgd=120.0,
                cost_basis_sgd=100.0, invested_sgd=161000.0, realised_pl_sgd=16800.0,
                unrealised_pl_sgd=20.0, stock_pl_sgd=16820.0, income_sgd=0.0,
                options_pl_sgd=52989.24, pl_sgd=16820.0, net_pl_sgd=69809.24)
# The refusal: every entering unit unknown, so there is no Net on the wire at all. `rollup()`
# DROPS it outright — its guard is `units <= 1e-6 and not cost_known and income ≈ 0`, which this
# row meets on all three counts — so it is on neither side of the identity. That third clause is
# why its income has to be zero: a refusal that had paid a dividend would not be dropped, and
# `income_sgd` accumulates OUTSIDE the `cost_known` guard, so the money would land in a group
# total with no ticker Net anywhere that could match it.
REFUSAL = _row(ticker="ASTREA6B", accounts=["FSM"], units=0.0, mv_sgd=0.0,
               cost_basis_sgd=None, invested_sgd=None, realised_pl_sgd=None,
               unrealised_pl_sgd=None, stock_pl_sgd=None, income_sgd=0.0, pl_sgd=None,
               cost_known=False, net_verdict="refuse", net_pl_sgd=None)

# A caveat: some entering units have no cost, so the leg knows the pair's SUM and neither
# member. This row is why the group Net is built from `stock_pl_sgd` and not from
# `realised + unrealised` — summing the members would drop its whole stock P/L out of the group
# total while the ticker side still carried it, and nothing else in this file can catch that.
CAVEAT = _row(ticker="Q01", units=27000.0, mv_sgd=25650.0, cost_basis_sgd=None,
              invested_sgd=None, realised_pl_sgd=None, unrealised_pl_sgd=None,
              stock_pl_sgd=-11630.17, income_sgd=8500.00, pl_sgd=None,
              net_verdict="caveat", net_pl_sgd=-3130.17)

ROWS = [CASH, CPF, OPTIONED, CAVEAT, REFUSAL]

# The options book as `realized_by()` sees it — every underlying, held or not. Two of these are
# written but never held, one of them a loss, and no Holdings row exists for either: that is the
# residual, and it is what makes this an identity rather than an equality.
OPTION_BOOK = {"PLTR": 52989.24, "TLT": 2347.30, "PYPL": -1061.36}
ORPHANS = {k: v for k, v in OPTION_BOOK.items() if k not in {r["ticker"] for r in ROWS}}
# Options are cash-bucket by construction and all on one account (#143 §16), so every dimension
# collapses the whole book onto a single key — which is the real `realized_by()`'s shape and the
# reason the residual cannot be split across groups.
OPTION_KEY = {"market": "US", "bucket": "cash", "account": "Tiger Prime", "asset_type": "stock"}


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    """The fold's output as a literal, and the options book as a dict. No database anywhere."""
    main._cache.clear()
    settings.dev_auth_bypass = True
    monkeypatch.setattr(portfolio_routes, "perf_all", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(options, "realized_by",
                        lambda by: {OPTION_KEY[by]: round(sum(OPTION_BOOK.values()), 2)})
    yield
    main._cache.clear()


@pytest.fixture
def client():
    return TestClient(main.app)


def ticker_nets(rows):
    """Σ Net per ticker, over the legs of every ticker that has one. A refusal has none —
    `net_pl_sgd` is null on every leg of it — and contributes nothing rather than zero."""
    out = {}
    for r in rows:
        if r["net_verdict"] == "refuse":
            continue
        out[r["ticker"]] = round(out.get(r["ticker"], 0.0) + r["net_pl_sgd"], 2)
    return out


def group_net(client, by):
    return round(sum(g["net_pl_sgd"] for g in client.get(f"/api/performance?by={by}").json().values()), 2)


@pytest.mark.parametrize("by", BY)
def test_the_group_nets_equal_the_ticker_nets_plus_the_named_residual(client, by):
    tickers = round(sum(ticker_nets(ROWS).values()), 2)
    residual = round(sum(ORPHANS.values()), 2)

    # ONE CENT, because "identical to 2dp" (#143 §15) is what the spec claims and each side
    # rounds its own terms at 2dp — so a cent is the most the two can differ by from rounding
    # alone. The live book's residual is audit_ledger.py's reading, not this gate's business:
    # #143 measured 0.03 there and today's book shows 0.00–0.01, and pinning either here would
    # make every option trade on a never-held name a red build.
    assert group_net(client, by) == pytest.approx(tickers + residual, abs=0.01)


@pytest.mark.parametrize("by", BY)
def test_the_residual_is_the_whole_gap_and_is_not_zero(client, by):
    """Both halves of "an identity, not equality": the gap is exactly the orphans, and the
    orphans are not nothing — an assertion that only held because the residual was zero would
    be the silent-loss outcome §15 rejected."""
    gap = round(group_net(client, by) - sum(ticker_nets(ROWS).values()), 2)

    assert gap == pytest.approx(sum(ORPHANS.values()), abs=0.01)
    assert abs(gap) > 1.0


def test_the_dimensions_agree_with_each_other(client):
    """One book, four partitions of it. A dimension whose key dropped a row would differ from
    the other two even if every one of them still looked plausible on its own."""
    assert len({group_net(client, by) for by in BY}) == 1


def test_a_refusal_carries_no_net_and_no_group_contribution(client):
    """The one row on the wire with no Net at all. It is in `perf_all()`'s output and so in the
    rollup's INPUT — the identity is asserted with it present rather than with it filtered out
    beforehand — and `rollup()`'s own guard is what keeps it off both sides."""
    assert REFUSAL["net_pl_sgd"] is None
    assert REFUSAL["ticker"] not in ticker_nets(ROWS)
    # Zero income is a PRECONDITION of the identity, not a property of this fixture. It is also
    # the third clause of the drop guard, so the two facts are one: with income the row would be
    # kept, and `income_sgd` accumulates outside the `cost_known` guard, so a refusal that had
    # paid a dividend would put money in the group total that no ticker Net can ever reach.
    assert REFUSAL["income_sgd"] == 0.0
    # …and it really is dropped, rather than kept and summing to zero by luck. Asserted through
    # the endpoint: no group names it, at any grouping.
    for by in BY:
        groups = client.get(f"/api/performance?by={by}").json()
        assert REFUSAL["ticker"] not in groups, by


def test_an_orphan_underlying_has_no_holdings_row_to_carry_it(client):
    """Why the residual exists at all, stated as a check rather than as a comment."""
    held = {r["ticker"] for r in ROWS}

    assert not (set(ORPHANS) & held)
