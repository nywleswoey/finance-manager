"""Net-worth snapshots: dated manual assets/liabilities + frozen live portfolio value.

Metrics (all SGD), with A = sum asset items, L = sum liability items, P = frozen portfolio:
    total_assets             = A + P
    total_liabilities        = L
    liquid_assets            = sum(value_sgd where is_liquid)
    net_worth                = total_assets - total_liabilities
    net_worth_excl_housing   = net_worth - housing_assets + housing_liabilities
    net_worth_excl_hou_cpf   = net_worth_excl_housing - cpf_assets

fx + value_sgd + portfolio_value_sgd are frozen at capture so history stays stable.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import session_scope
from .models import FxRate, NwItem, NwSnapshot, NwValue

# Catalogue codes auto-pulled from broker/bank statements (see scripts/snapshot_from_statements.py).
# Everything else is manual: entered in-app or carried forward. Single source of truth so the UI
# can flag which fields still need manual input and the ingest script stays in sync.
AUTO_CODES = {"tiger_usd", "tiger_sgd", "tiger_hkd", "tiger_vault", "dbs_multiplier", "srs"}


def live_portfolio_sgd(s: Session) -> Decimal:
    """Current live investment-portfolio market value in SGD (open positions),
    the same figure /api/overview reports as market_value_sgd."""
    from .performance import compute
    rows = compute(s)
    total = sum((r["mv_sgd"] for r in rows if r["units"] > 1e-6), 0.0)
    return Decimal(str(round(total, 4)))


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


def _write_value(s: Session, snap_id: int, it: NwItem, native, ccy, rate, existing=None) -> None:
    """Insert a NwValue for `it` (value_sgd = native*rate), or update its existing row in place.
    `existing` is an item_id -> NwValue index; None means always insert."""
    row = existing.get(it.id) if existing else None
    if row is None:
        s.add(NwValue(snapshot_id=snap_id, item_id=it.id, native_value=native,
                      currency=ccy, rate_to_sgd=rate, value_sgd=native * rate))
    else:
        row.native_value, row.currency = native, ccy
        row.rate_to_sgd, row.value_sgd = rate, native * rate


def catalogue(s: Session | None = None) -> list[dict]:
    with session_scope(s) as s:
        items = s.scalars(select(NwItem).where(NwItem.active).order_by(NwItem.sort_order)).all()
        return [_item_dict(i) for i in items]


def _item_dict(i: NwItem) -> dict:
    return {
        "id": i.id, "code": i.code, "label": i.label, "kind": i.kind,
        "currency_default": i.currency_default, "is_liquid": i.is_liquid,
        "is_housing": i.is_housing, "is_cpf": i.is_cpf, "sort_order": i.sort_order,
        "is_manual": i.code not in AUTO_CODES,
    }


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
    f = lambda x: round(float(x), 2)
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
        snaps = s.scalars(select(NwSnapshot).order_by(NwSnapshot.date.desc())).all()
        return [metrics(sn) for sn in snaps]


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

        snap = NwSnapshot(date=date, note=note, portfolio_value_sgd=live_portfolio_sgd(s))
        s.add(snap)
        s.flush()
        for code, it in items.items():
            native, ccy, rate = _frozen_value(s, it, supplied.get(code, {}), date)
            _write_value(s, snap.id, it, native, ccy, rate)
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
            _write_value(s, snap.id, it, native, ccy, rate, existing)   # insert if added after snapshot
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
