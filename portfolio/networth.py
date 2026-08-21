"""Net-worth snapshots: dated manual assets/liabilities + frozen live portfolio value.

Metrics (all SGD), with A = sum asset items, L = sum liability items, P = frozen portfolio:
    total_assets             = A + P
    total_liabilities        = L
    liquid_assets            = sum(value_sgd where is_liquid)
    net_worth                = total_assets - total_liabilities
    net_worth_excl_housing   = net_worth - housing_assets + housing_liabilities
    net_worth_excl_hou_cpf   = net_worth_excl_housing - cpf_assets

fx + value_sgd + portfolio_value_sgd are frozen at capture so history stays stable, as is the
portfolio's funding-bucket split (portfolio_{cash,cpf,srs}_sgd) — nothing draws that yet, but a
split can only ever be recorded live, so a snapshot taken without one can never grow one.

Bands (`band()`) are the other half: derived from the catalogue flags on every read, never stored.
`composition()` stacks them into the band-level history the composition chart draws — the only
place in this app where that history exists — and its cumulative edges are three of the six
metrics above, to the cent.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db import session_scope
from .models import FxRate, NwItem, NwSnapshot, NwValue

# Catalogue codes auto-pulled from broker/bank statements (see scripts/snapshot_from_statements.py).
# Everything else is manual: entered in-app or carried forward. Single source of truth so the UI
# can flag which fields still need manual input and the ingest script stays in sync.
AUTO_CODES = {"tiger_usd", "tiger_sgd", "tiger_hkd", "tiger_vault", "dbs_multiplier", "srs"}

# The four bands a catalogue item can fall into. NOT a stacking order — the composition chart's
# bottom→top order is the chart's, and it also carries a fifth, `portfolio`, which is no catalogue
# item at all (it is read off the snapshot's frozen portfolio scalar). This is only the set
# `band()` may return, so a caller can assert coverage without restating the precedence.
BANDS = ("housing", "cpf", "cash", "srs")

# THE COMPOSITION CHART'S BOTTOM->TOP STACKING ORDER. A LITERAL ORDER, NOT A SORT — and not a
# reordering of BANDS above, which is a *set* of what band() may return and carries no order at
# all. Three of this stack's four cumulative edges are summary tiles to the cent:
#
#     cash + portfolio           == net_worth_excl_housing_cpf
#     cash + portfolio + cpf     == net_worth_excl_housing
#     ... + housing              == net_worth
#
# Reorder this tuple and two of those three stop equalling anything, with no error anywhere —
# every band still sums to the same total, so only the boundaries move. That is the whole reason
# the order lives here as data rather than falling out of a sort.
STACK_ORDER = ("cash", "portfolio", "cpf", "housing")

# Bands drawn folded into another band, applied once here so no consumer has to. `srs` rides with
# `cash` because SRS is contributed cash under a withdrawal lock and is 1/44th of the cash band —
# its own area would be sub-pixel. ONE ENTRY AND ONE LINE TO REVERSE, deliberately: the day SRS is
# worth its own band, empty this map and add "srs" to STACK_ORDER beside "cash".
#
# THE FOLD HAPPENS HERE, NOT AT RENDER, so `srs` never reaches the wire — which is why
# web/src/palette.js's BAND_COLOURS carries four keys and no `srs`, and why the chip drawn for
# `cash` reads "Cash & SRS". A consumer that folded again would double-count it.
FOLDED_BANDS = {"srs": "cash"}

# The funding buckets a portfolio position can be pooled under (account.funding_bucket). Named
# here because a snapshot freezes one portfolio_*_sgd column per bucket — add a bucket and the
# snapshot needs a column, so the two lists have to be changed together.
FUNDING_BUCKETS = ("cash", "cpf", "srs")

# What `nw_value.source` may say — what the *write path* knew, never what it inferred:
#   statement    — a statement reported this figure
#   carried      — no statement covered it, so the prior snapshot's figure was carried forward
#   default_zero — nobody supplied it, so BR2's zeroing rule fabricated the $0
# NULL is the fourth and commonest state and is not a gap: it means the caller asserted nothing.
# The snapshot form deliberately writes NULL rather than deriving `carried`, because a user who
# reads the HDB valuation, confirms it has not moved and leaves the field alone has *measured*
# it — a column that said `carried` there would be worse than no column.
VALUE_SOURCES = ("statement", "carried", "default_zero")


def band(it: NwItem) -> str:
    """Which band of the composition a catalogue item belongs to, by precedence:
    `is_housing` → housing, `is_cpf` → cpf, `is_liquid` → cash, else srs.

    Derived, never stored. A `band` column would be a fourth grouping free to disagree with the
    three flags it is derived from, and this is deliberately not a SQL `CASE` ladder or a
    frontend switch either: the catalogue endpoint is active-only while the composition walks
    every value unfiltered, so a second copy would silently drop a deactivated item's history
    out of whichever edge it belonged to.

    Raises on a **non-housing liability**. Three of the composition's cumulative edges equal a
    summary tile to the cent only because every liability in the catalogue is a housing
    liability — netted into the Housing band, they cancel there and nowhere else. A car loan or
    a carried card balance would sit in an asset band as a negative and break that identity
    without changing a single number's sign, so it fails here instead of drawing wrong."""
    if it.is_housing and it.is_cpf:
        raise ValueError(
            f"catalogue item has conflicting band flags: {it.code!r} ({it.label!r}). "
            "An item cannot be both is_housing and is_cpf — each item belongs to exactly one band.")
    if it.kind == "liability" and not it.is_housing:
        raise ValueError(
            f"non-housing liability in the net-worth catalogue: {it.code!r} ({it.label!r}). "
            "The composition chart's band edges assume every liability is a housing liability "
            "(netted into Housing). Give it is_housing, or extend the banding first.")
    if it.is_housing:
        return "housing"
    if it.is_cpf:
        return "cpf"
    if it.is_liquid:
        return "cash"
    return "srs"


def live_portfolio_by_bucket(s: Session) -> dict[str, Decimal]:
    """Current live investment-portfolio market value in SGD (open positions), split by the
    funding bucket each position is pooled under. Summed, it is the same figure /api/overview
    reports as market_value_sgd.

    The split is the primitive and the total is derived from it, rather than the two being
    computed side by side: `compute()` is a fold over the whole securities ledger, so this walks
    it once, and a snapshot's three frozen buckets can never fail to add up to the total frozen
    beside them."""
    from .performance import compute
    out = {b: 0.0 for b in FUNDING_BUCKETS}
    for r in compute(s):
        if r["units"] <= 1e-6:
            continue
        if r["bucket"] not in out:
            # Silently dropping it would understate the portfolio by exactly that bucket, and
            # the total is the number every net-worth metric is built on.
            raise ValueError(f"position {r['ticker']} is in unknown funding bucket "
                             f"{r['bucket']!r}; expected one of {FUNDING_BUCKETS}")
        out[r["bucket"]] += r["mv_sgd"]
    return {b: Decimal(str(round(v, 4))) for b, v in out.items()}


def fx_row_for(s: Session, ccy: str, on_date: dt.date) -> FxRate | None:
    """The fx_rate row a freeze at `on_date` reads from — newest with date <= on_date, or None.

    The freeze rule itself, held once. `rate_for` wraps it for the "what rate" question and
    raises on None (BR4); scripts/promote_networth_snapshots.py needs the *row* — to carry it
    into a store that has no rate that early — and needs to report a miss across every currency
    rather than abort on the first, so it takes the None. Two callers, one definition of which
    row wins; a second copy would be free to drift from this one."""
    return s.execute(select(FxRate).where(FxRate.currency == ccy, FxRate.date <= on_date)
                     .order_by(FxRate.date.desc()).limit(1)).scalar_one_or_none()


def rate_for(s: Session, ccy: str, on_date: dt.date) -> Decimal:
    """Frozen FX: 1 for SGD; else latest fx_rate.rate_to_sgd with date <= on_date.
    Raises ValueError when no rate exists (BR4 — no silent fallback)."""
    if ccy == "SGD":
        return Decimal(1)
    row = fx_row_for(s, ccy, on_date)
    if row is None:
        raise ValueError(f"no FX rate for {ccy} on or before {on_date}")
    return Decimal(str(row.rate_to_sgd))


def _active_items(s: Session) -> tuple[dict, dict]:
    """Active catalogue keyed by code, plus an id index, for resolving supplied entries."""
    items = {i.code: i for i in s.scalars(select(NwItem).where(NwItem.active)).all()}
    return items, {i.id: i for i in items.values()}


def _resolve_item(items: dict, by_id: dict, v: dict) -> NwItem:
    """Match a {code|item_id, ...} entry to its catalogue item; raise ValueError on unknown."""
    it = by_id.get(v.get("item_id")) or items.get(v.get("code"))
    if it is None:
        raise ValueError(f"unknown item: {v.get('code') or v.get('item_id')}")
    return it


def _frozen_value(s: Session, it: NwItem, v: dict, on_date: dt.date) -> tuple:
    """(native, currency, rate) for a supplied entry (or {}), FX frozen at on_date."""
    native = Decimal(str(v.get("native_value", 0) or 0))
    ccy = (v.get("currency") or it.currency_default or "SGD").upper()
    return native, ccy, rate_for(s, ccy, on_date)


def _check_source(source: str | None) -> str | None:
    """A source is a claim about provenance, so an unrecognised one is a caller bug, not a
    free-text note. Checked in Python rather than by a CHECK constraint because the column must
    stay nullable for every row written before this existed."""
    if source is not None and source not in VALUE_SOURCES:
        raise ValueError(f"unknown nw_value.source {source!r}; expected one of {VALUE_SOURCES} "
                         "or None")
    return source


def _write_value(s: Session, snap_id: int, it: NwItem, native, ccy, rate, existing=None,
                 source: str | None = None) -> None:
    """Insert a NwValue for `it` (value_sgd = native*rate), or update its existing row in place.
    `existing` is an item_id -> NwValue index; None means always insert.

    `source` is assigned on both paths, never merged: re-writing a value replaces what the write
    path knows about it. That is what clears a stale `default_zero` when a dropped item is
    finally filled in — leave the old stamp and the item stays in the composition's `dropped`
    list forever, long after someone supplied the number."""
    source = _check_source(source)
    row = existing.get(it.id) if existing else None
    if row is None:
        s.add(NwValue(snapshot_id=snap_id, item_id=it.id, native_value=native,
                      currency=ccy, rate_to_sgd=rate, value_sgd=native * rate, source=source))
    else:
        row.native_value, row.currency = native, ccy
        row.rate_to_sgd, row.value_sgd = rate, native * rate
        row.source = source


def catalogue(s: Session | None = None) -> list[dict]:
    with session_scope(s) as s:
        items = s.scalars(select(NwItem).where(NwItem.active).order_by(NwItem.sort_order)).all()
        return [_item_dict(i) for i in items]


def _item_dict(i: NwItem) -> dict:
    return {
        "id": i.id, "code": i.code, "label": i.label, "kind": i.kind,
        "currency_default": i.currency_default, "is_liquid": i.is_liquid,
        "is_housing": i.is_housing, "is_cpf": i.is_cpf, "band": band(i),
        "sort_order": i.sort_order, "is_manual": i.code not in AUTO_CODES,
    }


def _cents(x) -> float:
    """Round an exact-decimal accumulator to cents, for the wire.

    One function rather than two identical lambdas because `metrics()` and `composition()` have
    to agree *to the bit*: the composition's cumulative edges are asserted equal to three of the
    metrics with `==`, not `assertAlmostEqual`, and two roundings that merely look the same are
    exactly how such an identity comes apart later."""
    return round(float(x), 2)


def _eager_values():
    """Load every snapshot's values and their catalogue items up front — a constant 3 queries.

    Both list builders here walk `v.item` for every value of every snapshot, which lazily is
    1 + N + one-per-item: 1 + 5 + 14 on today's history, and the N grows with every snapshot
    captured. selectinload turns it into three: the snapshots, their values in one IN, and the
    items in one more. Constant in N is the point — the chart's cost must not grow with the
    history it draws."""
    return selectinload(NwSnapshot.values).selectinload(NwValue.item)


def metrics(snap: NwSnapshot) -> dict:
    """Compute the six net-worth figures from a snapshot's frozen line values."""
    A = L = liquid = hou_a = hou_l = cpf_a = Decimal(0)
    for v in snap.values:
        it = v.item
        sgd = v.value_sgd or Decimal(0)
        if it.kind == "asset":
            A += sgd
            if it.is_housing:
                hou_a += sgd
            if it.is_cpf:
                cpf_a += sgd
        else:  # liability
            L += sgd
            if it.is_housing:
                hou_l += sgd
        if it.is_liquid:
            liquid += sgd
    P = snap.portfolio_value_sgd or Decimal(0)
    total_assets = A + P
    net_worth = total_assets - L
    excl_housing = net_worth - hou_a + hou_l
    excl_housing_cpf = excl_housing - cpf_a
    f = _cents
    return {
        "id": snap.id,
        "date": snap.date,
        "note": snap.note,
        "portfolio_value_sgd": f(P),
        "total_assets": f(total_assets),
        "total_liabilities": f(L),
        "liquid_assets": f(liquid),
        "net_worth": f(net_worth),
        "net_worth_excl_housing": f(excl_housing),
        "net_worth_excl_housing_cpf": f(excl_housing_cpf),
    }


def _value_dict(v: NwValue) -> dict:
    return {
        "item_id": v.item_id, "code": v.item.code, "label": v.item.label,
        "kind": v.item.kind, "native_value": float(v.native_value or 0),
        "currency": v.currency, "rate_to_sgd": float(v.rate_to_sgd or 1),
        "value_sgd": round(float(v.value_sgd or 0), 2),
        "is_manual": v.item.code not in AUTO_CODES,
    }


def snapshot_detail(snap: NwSnapshot) -> dict:
    return {**metrics(snap), "values": [_value_dict(v) for v in
                                        sorted(snap.values, key=lambda v: v.item.sort_order)]}


def list_snapshots(s: Session | None = None) -> list[dict]:
    with session_scope(s) as s:
        snaps = s.scalars(select(NwSnapshot).options(_eager_values())
                          .order_by(NwSnapshot.date.desc())).all()
        return [metrics(sn) for sn in snaps]


def _stack(snap: NwSnapshot) -> tuple[dict[str, Decimal], list[tuple[str, str]]]:
    """One snapshot's band totals in EXACT decimal, plus the (band, code) pairs the write path
    admits it fabricated. No rounding happens here — see `_series_row` for why.

    SIGNED AND NETTED ON THE WAY OUT. A liability is subtracted inside its own band, so Housing
    arrives as equity and is negative if equity ever is; nothing downstream applies a sign. Same
    principle as the spending module's negate-once-server-side, at the opposite polarity: this
    chart genuinely stacks both ways and the sign is information, not presentation.

    `band()` is called per value and raises on a non-housing liability, which is the guard that
    keeps the edge identity true — every liability cancelling inside Housing is the only reason
    three of these edges equal a tile.

    Every value, unfiltered by `active`: a deactivated item still holds history, and dropping it
    would silently shorten whichever edge it belonged to. This is why the banding is here and not
    in the catalogue endpoint (active-only) or in the frontend (which only ever sees that).
    """
    acc: dict[str, Decimal] = {}
    fabricated: list[tuple[str, str]] = []
    for v in snap.values:
        b = band(v.item)
        b = FOLDED_BANDS.get(b, b)
        sgd = v.value_sgd or Decimal(0)
        acc[b] = acc.get(b, Decimal(0)) + (sgd if v.item.kind == "asset" else -sgd)
        if v.source == "default_zero":
            fabricated.append((b, v.item.code))
    # The synthetic band: no catalogue item can produce it (`band()` never returns "portfolio"),
    # so it is read straight off the snapshot's frozen scalar. The funding-bucket columns beside
    # that scalar stay out of the payload — they are NULL on every snapshot taken before they
    # existed, and a null is exactly what every-key-on-every-row forbids while a 0 would be a lie.
    acc["portfolio"] = snap.portfolio_value_sgd or Decimal(0)
    return acc, fabricated


def _series_row(snap: NwSnapshot, acc: dict[str, Decimal]) -> dict:
    """One point of the series: `{date, <band>: float, ...}`, every band keyed.

    THE BANDS ARE THE DELTAS BETWEEN THE *ROUNDED* CUMULATIVE EDGES — never the edges as sums of
    rounded bands. Accumulate exact, round the edge, emit the difference. That makes the identity
    with the summary tiles true by arithmetic instead of by luck: measured on the live history,
    round-then-sum agrees with sum-then-round by 0.0011 of a cent on one snapshot, i.e. by
    coincidence, and the sub-cent residual lands in `cash` — 44x the size of the `srs` folded into
    it, so nothing about the picture would ever have shown it drifting.

    ISO date strings stay on the wire. The frontend parses to epoch ms once at render, which keeps
    this the only net-worth payload a human can read without a converter.
    """
    row = {"date": snap.date.isoformat()}
    edge = Decimal(0)
    below = 0.0
    for b in STACK_ORDER:
        # Zero-fill. It cannot fire today — every snapshot carries one value per catalogue item
        # and the catalogue covers every band, so every band is present on every point by
        # construction. It ships anyway because the band count is scheduled to change the day the
        # Portfolio split lands, and a band that appears mid-series (absent from every earlier
        # row) is precisely the gap a stacked chart reads one dataKey straight through.
        edge += acc.get(b, Decimal(0))
        cumulative = _cents(edge)
        row[b] = round(cumulative - below, 2)
        below = cumulative
    return row


def composition(s: Session | None = None) -> dict:
    """`{bands, series, dropped}` — the band-level history the composition chart draws, and the
    only surface in this app where band-level history exists at all.

    Its own endpoint rather than a widened snapshots list or a `?detail=` variant: `metrics()` is
    shared by /latest and /snapshots/{id}, so widening it would push a band series into two
    payloads where it means nothing; the orderings are opposite (the history table wants
    newest-first, a time axis wants ascending); and once the two-line chart retires the snapshots
    endpoint has exactly one consumer, which wants the six metrics.

    Shaped like the spending trends payload — one key per band on every row — because recharts
    reads one `dataKey` across the whole series. `dropped` is a sibling of `series`, never a flag
    inside a row: a row that mixes numbers with anything else is how a non-dataKey ends up handed
    to a `dataKey`.
    """
    with session_scope(s) as s:
        snaps = s.scalars(select(NwSnapshot).options(_eager_values())
                          .order_by(NwSnapshot.date)).all()
        series, dropped = [], []
        for snap in snaps:
            acc, fabricated = _stack(snap)
            series.append(_series_row(snap, acc))
            by_band: dict[str, list[str]] = {}
            for b, code in fabricated:
                by_band.setdefault(b, []).append(code)
            # Populated from the write path's own provenance (`nw_value.source`), not from the
            # shape of the payload: a fabricated $0 and a real $0 are the same number, and only
            # the row that wrote it knows which it was.
            dropped += [{"date": snap.date.isoformat(), "band": b, "codes": sorted(by_band[b])}
                        for b in STACK_ORDER if b in by_band]
        return {"bands": list(STACK_ORDER), "series": series, "dropped": dropped}


def get_snapshot(snap_id: int, s: Session | None = None) -> dict | None:
    with session_scope(s) as s:
        snap = s.get(NwSnapshot, snap_id)
        return snapshot_detail(snap) if snap else None


def latest(s: Session | None = None) -> dict | None:
    with session_scope(s) as s:
        snap = s.scalars(select(NwSnapshot).order_by(NwSnapshot.date.desc()).limit(1)).first()
        return snapshot_detail(snap) if snap else None


def create_snapshot(date: dt.date, values: list[dict], note: str | None = None,
                    s: Session | None = None) -> dict:
    """Create a dated snapshot. `values` = [{code|item_id, native_value, currency?}].
    Missing catalogue items default to 0 (BR2). Duplicate date rejected (BR1)."""
    with session_scope(s) as s:
        if s.scalar(select(NwSnapshot).where(NwSnapshot.date == date)):
            raise ValueError(f"snapshot for {date} already exists")
        items, by_id = _active_items(s)
        if not items:
            # One NwValue is written per catalogue item below, so an empty catalogue produced a
            # snapshot with zero values: metrics all zero, breakdown blank, and no error anywhere.
            # Refuse it. An empty net worth is a seeding failure, not a reading.
            raise ValueError("net-worth catalogue is empty — run scripts/seed_networth.py")
        supplied = {_resolve_item(items, by_id, v).code: v for v in values}

        # Frozen beside the total, not instead of it: nothing draws the buckets yet — the
        # Portfolio band stays one opaque band until they have history — but a bucket split can
        # only ever be recorded live, so a snapshot captured before they existed can never be
        # reconstructed. Existing snapshots keep NULL rather than being backfilled with a guess.
        buckets = live_portfolio_by_bucket(s)
        snap = NwSnapshot(date=date, note=note,
                          portfolio_value_sgd=sum(buckets.values(), Decimal(0)),
                          portfolio_cash_sgd=buckets["cash"],
                          portfolio_cpf_sgd=buckets["cpf"],
                          portfolio_srs_sgd=buckets["srs"])
        s.add(snap)
        s.flush()
        for code, it in items.items():
            v = supplied.get(code)
            native, ccy, rate = _frozen_value(s, it, v or {}, date)
            # An omitted item is BR2's zeroing rule fabricating the $0 itself, so the row says
            # so — that stamp is describing what this line just did, not asserting a provenance
            # it cannot know. A *supplied* value carries only what its caller claims (the
            # statement ingest names one; the form and the API name nothing).
            _write_value(s, snap.id, it, native, ccy, rate,
                         source="default_zero" if v is None else v.get("source"))
        s.commit()
        s.refresh(snap)
        return snapshot_detail(snap)


def update_snapshot(snap_id: int, values: list[dict], note: str | None = None,
                    s: Session | None = None) -> dict | None:
    """Edit an existing snapshot in place — the path for filling manual fields (CPF, HDB,
    loan, POSB, IBKR ...) after a statement ingest, without a duplicate-date conflict.

    Only supplied items are changed; their FX rate is re-frozen at the snapshot's OWN date
    (history stays stable) and value_sgd recomputed. Items not supplied and the frozen
    portfolio_value_sgd are left untouched. Returns the detail, or None if the id is unknown."""
    with session_scope(s) as s:
        snap = s.get(NwSnapshot, snap_id)
        if snap is None:
            return None
        items, by_id = _active_items(s)
        existing = {v.item_id: v for v in snap.values}
        for v in values:
            it = _resolve_item(items, by_id, v)
            native, ccy, rate = _frozen_value(s, it, v, snap.date)
            _write_value(s, snap.id, it, native, ccy, rate, existing,   # insert if added after snapshot
                         source=v.get("source"))
        if note is not None:
            snap.note = note
        s.commit()
        s.refresh(snap)
        return snapshot_detail(snap)


def delete_snapshot(snap_id: int, s: Session | None = None) -> bool:
    with session_scope(s) as s:
        snap = s.get(NwSnapshot, snap_id)
        if snap is None:
            return False
        s.delete(snap)
        s.commit()
        return True
