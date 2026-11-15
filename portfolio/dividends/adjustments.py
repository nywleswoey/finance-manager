"""The persisted capital-return component (`dividend_adjustment`): a recurring non-ordinary per-
unit amount the statements fold into the same summed rate as the ordinary dividend. CRUD plus
`apply_capital_return`, which nets it out of a rate for the dates it is active."""
from sqlalchemy import text

from ..db import fetch_dicts, session_scope
from ..nullable import num


def capital_return_adjustments(s=None):
    """Every dividend_adjustment, newest start_date first, with the security's ticker/name
    joined in for the Dividends tab's list."""
    with session_scope(s) as s:
        rows = fetch_dicts(s,
            "SELECT da.id, da.security_id, sec.canonical_ticker ticker, sec.name, "
            "da.amount_per_unit, da.currency, da.start_date, da.end_date, da.note "
            "FROM dividend_adjustment da JOIN security sec ON sec.id = da.security_id "
            "ORDER BY da.start_date DESC, da.id DESC")
    return [{**r, "amount_per_unit": num(r["amount_per_unit"])} for r in rows]


def add_capital_return_adjustment(security_id, amount_per_unit, currency, start_date,
                                  end_date=None, note=None, s=None):
    """Persist a capital-return (or other recurring non-ordinary component) deduction — see
    DividendAdjustment for why this can only be declared, not derived."""
    with session_scope(s) as s:
        s.execute(text(
            "INSERT INTO dividend_adjustment (security_id, amount_per_unit, currency, "
            "start_date, end_date, note) VALUES (:sid, :amt, :ccy, :start, :end, :note)"),
            {"sid": security_id, "amt": amount_per_unit, "ccy": currency,
             "start": start_date, "end": end_date, "note": note})
        s.commit()


def remove_capital_return_adjustment(adjustment_id, s=None):
    with session_scope(s) as s:
        s.execute(text("DELETE FROM dividend_adjustment WHERE id = :id"), {"id": adjustment_id})
        s.commit()


def _active_adjustment(adjustments, date):
    """The dividend_adjustment covering `date` (its ex_date, else pay_date) — the one with the
    latest start_date <= date whose end_date (if any) hasn't passed — or None. Picking the
    latest start_date lets a new adjustment row for a rate change take over from `start_date`
    without touching the old one's history."""
    if date is None:
        return None
    candidates = [a for a in adjustments
                 if a["start_date"] <= date and (a["end_date"] is None or date <= a["end_date"])]
    return max(candidates, key=lambda a: a["start_date"]) if candidates else None


def apply_capital_return(rate, currency, date, adjustments):
    """`rate` minus the adjustment active on `date`, clamped at zero — never a negative
    "regular" dividend. Returns `(net_rate, adjustment_or_None, clamped: bool)`; `clamped` lets
    a caller surface "the deduction is larger than this payment" rather than silently losing the
    difference. An adjustment in a different currency than the payment never applies — there is
    nothing to subtract 1:1 across currencies here."""
    adj = _active_adjustment(adjustments, date)
    if adj is None or adj["currency"] != currency:
        return rate, None, False
    net = rate - float(adj["amount_per_unit"])
    clamped = net < 0
    return (0.0 if clamped else net), adj, clamped


def _capital_return_component(components, adj, currency):
    """The one of `components` (the payment's own cached SGX line items, already `{amount_per_unit,
    currency}`) that IS the active capital-return adjustment `adj` - same amount and currency,
    within the usual 1e-9 tolerance - or None when `adj` is inactive, in a different currency, or
    matches no cached component (SGX reported the payment as a single combined line - nothing to
    attribute the deduction to specifically, see `_net_distributions`)."""
    if adj is None or adj["currency"] != currency:
        return None
    amt = float(adj["amount_per_unit"])
    for c in components:
        if c["currency"] == currency and abs(c["amount_per_unit"] - amt) < 1e-9:
            return c
    return None
