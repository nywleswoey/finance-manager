"""The persisted per-payment Normal/Special split (`dividend_flag_override`) and SGX component
identification: `add_flag_override`, `identify_components`, and `split_components` (which
payments still need a manual pick)."""
from sqlalchemy import text

from ..db import fetch_dicts, session_scope
from ..nullable import num
from .adjustments import _active_adjustment, _capital_return_component
from .distributions import SAME_DISTRIBUTION_DAYS, distinct_distributions


def _payment(security_id, ex_date, pay_date, s):
    """The one distribution at (security_id, ex_date, pay_date) - an EXACT match, not
    `_match_override()`'s re-ingest-tolerant one: the caller already has this key from a
    distribution `yields()` just listed, so there is no drift to allow for. None when no such
    distribution is found (a stale key - nothing to validate a split against)."""
    row = fetch_dicts(s, "SELECT canonical_ticker FROM security WHERE id = :sid", {"sid": security_id})
    ticker = row[0]["canonical_ticker"] if row else None
    if ticker is None:
        return None
    for d in distinct_distributions(ticker, s):
        if ex_date is not None:
            if d["ex_date"] == ex_date:
                return d
        elif d["ex_date"] is None and d["pay_date"] == pay_date:
            return d
    return None


def add_flag_override(security_id, ex_date, pay_date, special_per_unit=0, s=None, labels=()):
    """Record a per-payment split: `special_per_unit` is the user-declared special portion of
    the payment's combined per-unit rate, in the payment's own currency - 0 (the default) is the
    original "mark as regular" case, where the whole payment is regular. Persisted so it survives
    a re-ingest and `yields()` never auto-flags the payment and counts only the regular part
    (rate minus special_per_unit) toward trailing/forward DPS - see DividendFlagOverride and
    `_net_distributions()`. Keyed like `_distributions()` groups a distribution: ex_date when
    present, else pay_date (matched by `_match_override()`).

    `labels` is the per-component Normal/Special identification behind the split
    (`identify_components`, `{amount_per_unit, currency, label}` each) - empty for a typed split.
    Whatever labels the split carried before are replaced, so typing a new special portion over
    an identified one turns it back into a typed split.

    Upsert, not insert-or-skip: calling this again on an already-split payment UPDATEs its
    special_per_unit (the Dividends tab's Edit) rather than adding a second row - the existing
    row is found by `_match_override()`, the same rule `yields()` attaches it by, and its key is
    refreshed to the payment's current (ex_date, pay_date); the same value
    twice is a true no-op (same single row either way) - this is what keeps the original
    "marking an already-marked payment again is a no-op" behaviour working unchanged.

    Raises ValueError when special_per_unit is negative, exceeds the payment's own combined rate
    (`_payment`, allowing float rounding noise), or matches no known distribution at all -
    never persisting a split nothing can apply to."""
    special_per_unit = float(special_per_unit or 0)
    if special_per_unit < 0:
        raise ValueError("special portion cannot be negative")
    with session_scope(s) as s:
        d = _payment(security_id, ex_date, pay_date, s)
        if d is None:
            raise ValueError("no matching dividend payment for that ex_date/pay_date")
        if special_per_unit > d["rate"] + 1e-9:
            raise ValueError(
                f"special portion {special_per_unit} exceeds the payment's rate {d['rate']}")
        existing = _match_override(fetch_dicts(s,
            "SELECT id, ex_date, pay_date FROM dividend_flag_override WHERE security_id = :sid",
            {"sid": security_id}), d)
        params = {"sid": security_id, "ex": d["ex_date"], "pay": d["pay_date"],
                  "sp": special_per_unit}
        if existing:
            override_id = existing["id"]
            s.execute(text("UPDATE dividend_flag_override SET ex_date = :ex, pay_date = :pay, "
                           "special_per_unit = :sp, source = 'user' WHERE id = :id"),
                      {**params, "id": override_id})
        else:
            override_id = s.execute(text(
                "INSERT INTO dividend_flag_override (security_id, ex_date, pay_date, "
                "special_per_unit) VALUES (:sid, :ex, :pay, :sp) RETURNING id"), params).scalar_one()
        s.execute(text("DELETE FROM dividend_flag_override_component WHERE override_id = :id"),
                  {"id": override_id})
        for c in labels:
            s.execute(text(
                "INSERT INTO dividend_flag_override_component (override_id, amount_per_unit, "
                "currency, label) VALUES (:id, :amt, :ccy, :label)"),
                {"id": override_id, "amt": c["amount_per_unit"], "ccy": c["currency"],
                 "label": c["label"]})
        s.commit()


def remove_flag_override(override_id, s=None):
    """Clear a payment's split entirely (Unmark/Clear) - both the original zero-special "mark as
    regular" case and a true split end the same way, a plain delete."""
    with session_scope(s) as s:
        s.execute(text("DELETE FROM dividend_flag_override WHERE id = :id"), {"id": override_id})
        s.commit()


def identify_components(security_id, ex_date, pay_date, special_amounts, s=None):
    """Resolve a multi-component payment's Normal/Special labelling (the Dividends tab's
    "awaiting identification" list, see `yields()`) into a `dividend_flag_override` split:
    `special_amounts` is the per-unit rate of every cached `dividend_announcement_component`
    the captain marked Special - every OTHER listed component for that payment is implicitly
    Normal. Their summed total becomes the payment's recorded special portion via
    `add_flag_override` (source='user'), together with each listed component's own label
    (DividendFlagOverrideComponent), so `_net_distributions` knows exactly which components
    the special portion already removed. The component matching the payment's active
    capital-return setting (`_capital_return_component`) is never listed or labelled - it is
    capital return automatically. The Dividends tab asks for every listed component's label in
    one atomic submission rather than caching a partial answer that could go stale under a
    corrected SGX announcement.

    Raises ValueError when the payment has fewer than two cached components left to label once
    any capital-return one is set aside (nothing to identify - `yields()` never lists one here),
    any component is declared in a currency other than the payment's own (a special portion must
    be in the payment's currency - `yields()` never lists such a payment either), or
    `special_amounts` contains a rate that doesn't match any listed component (stale UI state -
    the components list changed under the caller; re-fetch and retry)."""
    with session_scope(s) as s:
        comps = split_components(security_id, ex_date, pay_date, s)
        d = _payment(security_id, ex_date, pay_date, s)
        if d is None:
            raise ValueError("no matching dividend payment for that ex_date/pay_date")
        if any(c["currency"] != d["currency"] for c in comps):
            raise ValueError(
                f"components are not all declared in the payment's currency {d['currency']}")
        adjustments = [{**a, "amount_per_unit": num(a["amount_per_unit"])} for a in fetch_dicts(s,
            "SELECT amount_per_unit, currency, start_date, end_date FROM dividend_adjustment "
            "WHERE security_id = :sid", {"sid": security_id})]
        cr_comp = _capital_return_component(
            comps, _active_adjustment(adjustments, d["ex_date"] or d["pay_date"]), d["currency"])
        remaining = [c for c in comps if c is not cr_comp]
        if len(remaining) < 2:
            raise ValueError("payment has fewer than two declared components - nothing to identify")
        specials = []
        for amt in special_amounts:
            amt = float(amt)
            match = next((c for c in remaining if abs(c["amount_per_unit"] - amt) < 1e-6), None)
            if match is None:
                raise ValueError(f"{amt} does not match a cached component for this payment")
            remaining.remove(match)
            specials.append(match)
        labels = ([{**c, "label": "special"} for c in specials] +
                  [{**c, "label": "normal"} for c in remaining])
        add_flag_override(security_id, ex_date, pay_date,
                          special_per_unit=round(sum(c["amount_per_unit"] for c in specials), 6),
                          s=s, labels=labels)


def split_components(security_id, ex_date, pay_date=None, s=None):
    """Cached SGX per-component rates for one payment (`dividend_announcement_component`, filled
    by ingestion.dividend_announcements) - for the Dividends tab's split-entry UI to offer the
    user a button per declared line-item rate instead of typing one by hand. When the payment
    itself has no ex_date (SBS Transit's 2026-08-28 payment is the real case - the statement
    carried none), `pay_date` is matched against `dividend_announcement`'s own pay_date within
    SAME_DISTRIBUTION_DAYS to recover the ex_date components are keyed by, the same tolerance
    `_match_override` already allows an ex-date-less override. Empty when nothing is cached: a
    non-SG/non-SGX-matched security, no match at all, or SGX reported only one line item - the
    UI falls back to free typing either way, this is a convenience, never a requirement."""
    with session_scope(s) as s:
        if ex_date is None:
            if pay_date is None:
                return []
            match = fetch_dicts(s,
                "SELECT ex_date FROM dividend_announcement WHERE security_id = :sid "
                "AND ABS(pay_date - :pay) <= :window ORDER BY ABS(pay_date - :pay) LIMIT 1",
                {"sid": security_id, "pay": pay_date, "window": SAME_DISTRIBUTION_DAYS})
            if not match:
                return []
            ex_date = match[0]["ex_date"]
        rows = fetch_dicts(s,
            "SELECT amount_per_unit, currency FROM dividend_announcement_component "
            "WHERE security_id = :sid AND ex_date = :ex ORDER BY amount_per_unit",
            {"sid": security_id, "ex": ex_date})
    return [{"amount_per_unit": num(r["amount_per_unit"]), "currency": r["currency"]} for r in rows]


def _components_for(sid, ex_date, pay_date, components_by_sec, announced_by_sec):
    """`dividend_announcement_component` rows cached for one payment - the same lookup
    `split_components()` does (own ex_date, else its announcement matched within
    SAME_DISTRIBUTION_DAYS of pay_date), against already-prefetched data rather than a query
    per distribution - `yields()`'s batch path, over every held security's full history."""
    if ex_date is None:
        if pay_date is None:
            return []
        candidates = [a for a in announced_by_sec.get(sid, [])
                     if abs((a["pay_date"] - pay_date).days) <= SAME_DISTRIBUTION_DAYS]
        if not candidates:
            return []
        ex_date = min(candidates, key=lambda a: abs((a["pay_date"] - pay_date).days))["ex_date"]
    return [c for c in components_by_sec.get(sid, []) if c["ex_date"] == ex_date]


def _match_override(overrides, d):
    """The dividend_flag_override row (id/ex_date/pay_date/special_per_unit) applying to
    distribution `d`, else None. Matched the way `_distributions()` tells one distribution from
    another: an override with an ex_date on that ex_date, one without on a pay_date within
    SAME_DISTRIBUTION_DAYS - so marking a payment before a later ingest supplies its ex_date (or
    another account's earlier pay_date) still holds."""
    for o in overrides:
        if o["ex_date"] is not None and o["ex_date"] == d["ex_date"]:
            return o
    for o in overrides:
        if o["ex_date"] is None \
                and abs((o["pay_date"] - d["pay_date"]).days) <= SAME_DISTRIBUTION_DAYS:
            return o
    return None
