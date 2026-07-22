"""money.rate_to_sgd / to_sgd — the one native->SGD conversion policy.

The whole point of the module is the miss-policy: a foreign currency with no rate in the
latest-rate map must fail loud, not silently convert at 1.0. The old `fx.get(ccy, 1.0)`
idiom collapsed "SGD, legitimately 1:1" and "a foreign rate we're missing" into the same
1.0, overstating the holding — a missing HKD rate at 1.0 is ~6x too high.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_money.py -q
"""
import pytest

from portfolio.money import rate_to_sgd, to_sgd

FX = {"USD": 1.35, "HKD": 0.17}


def test_sgd_is_identity_and_never_needs_a_rate():
    # SGD is intentionally absent from the fx_rate table, so it never appears in the map.
    assert rate_to_sgd("SGD", {}) == 1.0
    assert rate_to_sgd("SGD", FX) == 1.0


def test_none_currency_is_treated_as_sgd():
    assert rate_to_sgd(None, {}) == 1.0


def test_present_foreign_currency_uses_its_rate():
    assert rate_to_sgd("USD", FX) == 1.35
    assert rate_to_sgd("HKD", FX) == 0.17


def test_missing_foreign_rate_fails_loud_not_silently_one():
    # the bug guard: fx.get(ccy, 1.0) would have returned 1.0 here and overstated the holding.
    with pytest.raises(ValueError):
        rate_to_sgd("HKD", {"USD": 1.35})
    with pytest.raises(ValueError):
        rate_to_sgd("JPY", {})


def test_to_sgd_converts_value():
    assert to_sgd(100, "USD", FX) == 135.0
    assert to_sgd(100, "SGD", FX) == 100.0


def test_to_sgd_passes_none_through():
    assert to_sgd(None, "USD", FX) is None


def test_to_sgd_missing_foreign_rate_raises():
    with pytest.raises(ValueError):
        to_sgd(100, "HKD", {})
