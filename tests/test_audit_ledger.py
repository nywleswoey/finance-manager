"""scripts/audit_ledger.py — the tier-3 runner's own rules, gated without a book.

The runner reads the live ledger and is deliberately outside CI (#143 Testing Decisions, tier 3).
What CAN be gated is the seam between its two output classes: an invariant that fails is real
news and must turn the run red; a reading that disagrees with the spec is a fact about one book
and must never do so. So every book here is fabricated, and **no figure below is a live-book
literal** — the settled table the readings compare against is passed in, not imported.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_audit_ledger.py -q
"""
import datetime as dt

from scripts import audit_ledger as al

D = dt.date


def _part(units_in, costed, free=0.0, unknown=0.0):
    pct = round(unknown / units_in, 4) if units_in else 0.0
    return {"units_in": units_in, "costed": costed, "free": free, "unknown": unknown,
            "unknown_pct": pct}


def _row(ticker="AAA", bucket="cash", **over):
    """One `fold_positions` row, carrying only the keys the runner reads."""
    r = dict(ticker=ticker, bucket=bucket, accounts=["FSM"], name=ticker, market="SG",
             asset_type="stock", currency="SGD", units=10.0, price=1.0, avg_cost=1.0,
             cost_basis_native=10.0, cost_basis_sgd=10.0, mv_native=10.0, mv_sgd=10.0,
             realised_pl_sgd=0.0, unrealised_pl_sgd=0.0, stock_pl_sgd=0.0, income_sgd=0.0,
             income_native=0.0, options_pl_sgd=None, net_pl_sgd=0.0, net_verdict="hero",
             return_pct=0.0, return_verdict="ok", peak_car_sgd=10.0, return_span_days=365,
             cost_partition=_part(10, 10), invested_sgd=10.0, invested_native=10.0,
             fees_sgd=0.0, cost_known=True)
    r.update(over)
    return r


def _book(**over):
    """A clean book: every invariant passes on it, so each test breaks exactly one thing."""
    b = dict(
        rows=[_row()],
        corporate_actions=[("OLD", "NEW", "split"), ("OLD", "SIB", "distribution"),
                           ("X", "Y", "rename")],
        actions={"txn": ["buy", "sell", "stock dividend"], "cdp_cost_lot": ["transfer out"]},
        stock_dividends=[{"ticker": "AAA", "trade_date": D(2020, 1, 1), "qty_signed": 0.0}],
        fold_warnings=[],
        cost_lot_tickers={"AAA"},
        cdp_txn_tickers={"AAA"},
        car={"AAA": {"peak_car_sgd": 10.0, "peak_car_date": D(2020, 1, 1),
                     "return_span_days": 365, "held": True}},
        performance={"market": {"SG": {"net_pl_sgd": 0.0}}},
        orphan_options={},
    )
    b.update(over)
    return al.Book(**b)


def _failures(book, name):
    inv = next(i for i in al.INVARIANTS if i.name == name)
    return inv.check(book)


# -- the two classes -------------------------------------------------------------------------

def test_a_clean_book_passes_every_invariant():
    lines, ok = al.audit(_book(), settled=al.Settled())
    assert ok, "\n".join(lines)
    assert all(not i.check(_book()) for i in al.INVARIANTS)


def test_the_header_names_both_classes():
    doc = al.__doc__.lower()
    assert "invariants" in doc and "fail" in doc
    assert "readings" in doc and "never assert" in doc
    assert "outside ci" in doc


def test_one_failing_invariant_turns_the_run_red_and_says_which():
    book = _book(stock_dividends=[{"ticker": "AAA", "trade_date": D(2020, 1, 1),
                                   "qty_signed": 5.0}])
    lines, ok = al.audit(book, settled=al.Settled())
    assert not ok
    text = "\n".join(lines)
    assert "FAIL" in text and "stock dividend" in text


def test_a_reading_that_disagrees_with_the_spec_never_turns_the_run_red():
    """The whole point of the second class: a book that gained a trade must not go red."""
    settled = al.Settled(
        peak_car=[("AAA", 999.0, D(1999, 1, 1), 9.9, "closed")],
        caveat=[("ZZZ", 0.5)],
        partition={"units_in": 1, "costed": 1, "free": 0, "unknown": 0},
        cost_known_false=["QQQ"],
        residual=(123.0, 0.01),
    )
    lines, ok = al.audit(_book(), settled=settled)
    assert ok
    assert "≠" in "\n".join(lines)


# -- invariants, each broken on its own ------------------------------------------------------

def test_partition_that_does_not_sum_to_units_in_fails():
    book = _book(rows=[_row(cost_partition=_part(10, 6, free=1, unknown=2))])
    assert _failures(book, "partition sums to units in") == [
        "cash/AAA: costed 6 + free 1 + unknown 2 = 9 ≠ units_in 10"]


def test_partition_tolerates_float_noise_at_the_fold_rounding():
    book = _book(rows=[_row(cost_partition=_part(0.3, 0.1, free=0.2 + 1e-12))])
    assert _failures(book, "partition sums to units in") == []


def test_exactly_one_multi_successor_corporate_action():
    none = _book(corporate_actions=[("OLD", "NEW", "split")])
    assert _failures(none, "exactly one multi-successor corporate action") == [
        "0 from_tickers have more than one corporate_action row, expected exactly 1: []"]
    two = _book(corporate_actions=[("A", "B", "split"), ("A", "C", "distribution"),
                                   ("P", "Q", "split"), ("P", "R", "distribution")])
    assert _failures(two, "exactly one multi-successor corporate action") == [
        "2 from_tickers have more than one corporate_action row, expected exactly 1: "
        "['A', 'P']"]


def test_transfer_out_with_a_space_outside_the_cost_lot_table_fails():
    book = _book(actions={"txn": ["buy", " Transfer Out "], "cdp_cost_lot": ["transfer out"]})
    assert _failures(book, "`transfer out` only in cdp_cost_lot") == [
        "txn carries 1 `transfer out` row(s)"]
    # the underscore spelling is a different string, handled by the fold's own sets
    ok = _book(actions={"txn": ["transfer_out", "sell/transfer_out"], "cdp_cost_lot": []})
    assert _failures(ok, "`transfer out` only in cdp_cost_lot") == []


def test_any_warning_from_the_fold_fails():
    book = _book(fold_warnings=["unclassified txn action(s) ['spinoff'] — treated as zero-cash"])
    assert _failures(book, "the fold emits no unclassified action") == [
        "unclassified txn action(s) ['spinoff'] — treated as zero-cash"]


def test_a_stock_dividend_that_delivers_units_fails():
    book = _book(stock_dividends=[
        {"ticker": "AAA", "trade_date": D(2020, 1, 1), "qty_signed": 0.0},
        {"ticker": "BBB", "trade_date": D(2021, 2, 3), "qty_signed": -4.0}])
    assert _failures(book, "every stock dividend carries zero quantity") == [
        "BBB 2021-02-03: stock dividend qty_signed -4.0"]


def test_cost_lots_on_a_ticker_with_no_cdp_rows_fail():
    """#146: a cost lot attaches to the cash leg by ticker, so one with no CDP txn rows behind
    it is counted a second time beside the broker's own record of the same buy."""
    book = _book(rows=[_row("AAA"), _row("H78X")], cost_lot_tickers={"AAA", "H78X"},
                 cdp_txn_tickers={"AAA"})
    assert _failures(book, "cost lots only on tickers CDP holds") == [
        "H78X has cdp_cost_lot rows and no CDP txn rows — its cost is attached twice (#146)"]


def test_cost_lots_with_no_cash_leg_to_attach_to_are_not_counted_at_all():
    """`cdp_cost()`'s result lands only on an existing cash leg, so a lot for a ticker the book
    holds no cash leg of — or a blank row with no ticker — double-counts nothing."""
    book = _book(rows=[_row("AAA"), _row("CPFONLY", bucket="cpf")],
                 cost_lot_tickers={"AAA", "CPFONLY", "SOLDBEFORE", ""}, cdp_txn_tickers={"AAA"})
    assert _failures(book, "cost lots only on tickers CDP holds") == []


# -- readings: printed from the book, compared to what the spec settled ----------------------

def _text(book, settled):
    return "\n".join(al.audit(book, settled=settled)[0])


def _line(book, settled, needle):
    """The one printed reading line naming `needle`, stripped — its mark is its first glyph."""
    return next(ln.strip() for ln in al.audit(book, settled=settled)[0] if needle in ln)


def test_peak_car_reading_prints_the_figure_its_date_and_span_beside_the_spec():
    book = _book(car={"AAA": {"peak_car_sgd": 1234.5, "peak_car_date": D(2021, 6, 1),
                              "return_span_days": 730, "held": False}})
    same = _line(book, al.Settled(peak_car=[("AAA", 1234.5, D(2021, 6, 1), 2.0, "closed")]),
                 " AAA ")
    assert same.startswith("=")
    assert "1,234.50" in same and "2021-06-01" in same and "2.0y" in same and "closed" in same
    moved = _line(book, al.Settled(peak_car=[("AAA", 1234.51, D(2021, 6, 1), 2.0, "closed")]),
                  " AAA ")
    assert moved.startswith("≠")


def test_a_settled_ticker_missing_from_the_book_is_printed_not_raised():
    text = _text(_book(), al.Settled(peak_car=[("GONE", 1.0, D(2020, 1, 1), 1.0, "open")]))
    assert "GONE" in text and "not in this book" in text


def test_caveat_reading_is_whole_ticker_from_summed_counts():
    rows = [_row("QQQ", "cash", cost_partition=_part(100, 60, unknown=40)),
            _row("QQQ", "cpf", cost_partition=_part(100, 100)),
            _row("FREE", cost_partition=_part(5, 0, free=5))]
    assert al.caveat_set(rows) == [("QQQ", 0.2, 40.0, 200.0)]


def test_partition_totals_sum_every_position():
    rows = [_row("A", cost_partition=_part(10, 7, free=1, unknown=2)),
            _row("B", cost_partition=_part(5, 5))]
    assert al.partition_totals(rows) == {"units_in": 15, "costed": 12, "free": 1, "unknown": 2}


def test_cost_known_false_set_marks_emptied_predecessors():
    rows = [_row("REF", cost_known=False, cost_partition=_part(50, 0, unknown=50)),
            _row("OLD", cost_known=False, units=0.0, invested_native=0.0)]
    got = al.cost_known_false(rows, [("OLD", "NEW", "split")])
    assert got == [("OLD", True), ("REF", False)]


def test_the_performance_identity_names_its_residual():
    """Σ group Net = Σ ticker Net + Σ orphan option underlyings + rounding, per dimension."""
    rows = [_row("A", net_pl_sgd=100.0), _row("B", net_pl_sgd=50.0)]
    book = _book(rows=rows, orphan_options={"ORPH": 7.0},
                 performance={"market": {"SG": {"net_pl_sgd": 150.0}, "US": {"net_pl_sgd": 7.01}},
                              "bucket": {"cash": {"net_pl_sgd": 157.0}}})
    got = al.performance_identity(book)
    assert got == {"market": (157.01, 150.0, 7.0, 0.01), "bucket": (157.0, 150.0, 7.0, 0.0)}
