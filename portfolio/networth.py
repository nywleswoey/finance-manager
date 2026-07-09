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

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import NwItem, NwSnapshot, NwValue

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


def rate_for(s: Session, ccy: str, on_date: dt.date) -> Decimal:
    """Frozen FX: 1 for SGD; else latest fx_rate.rate_to_sgd with date <= on_date.
    Raises ValueError when no rate exists (BR4 — no silent fallback)."""
    if ccy == "SGD":
        return Decimal(1)
    r = s.execute(text(
        "SELECT rate_to_sgd FROM fx_rate WHERE currency = :c AND date <= :d "
        "ORDER BY date DESC LIMIT 1"), {"c": ccy, "d": on_date}).scalar()
    if r is None:
        raise ValueError(f"no FX rate for {ccy} on or before {on_date}")
    return Decimal(str(r))


def catalogue(s: Session | None = None) -> list[dict]:
    own = s is None
    s = s or SessionLocal()
    try:
        items = s.scalars(select(NwItem).where(NwItem.active).order_by(NwItem.sort_order)).all()
        return [_item_dict(i) for i in items]
    finally:
        if own:
            s.close()


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
    own = s is None
    s = s or SessionLocal()
    try:
        snaps = s.scalars(select(NwSnapshot).order_by(NwSnapshot.date.desc())).all()
        return [metrics(sn) for sn in snaps]
    finally:
        if own:
            s.close()


def get_snapshot(snap_id: int, s: Session | None = None) -> dict | None:
    own = s is None
    s = s or SessionLocal()
    try:
        snap = s.get(NwSnapshot, snap_id)
        return snapshot_detail(snap) if snap else None
    finally:
        if own:
            s.close()


def latest(s: Session | None = None) -> dict | None:
    own = s is None
    s = s or SessionLocal()
    try:
        snap = s.scalars(select(NwSnapshot).order_by(NwSnapshot.date.desc()).limit(1)).first()
        return snapshot_detail(snap) if snap else None
    finally:
        if own:
            s.close()


def create_snapshot(date: dt.date, values: list[dict], note: str | None = None,
                    s: Session | None = None) -> dict:
    """Create a dated snapshot. `values` = [{code|item_id, native_value, currency?}].
    Missing catalogue items default to 0 (BR2). Duplicate date rejected (BR1)."""
    own = s is None
    s = s or SessionLocal()
    try:
        if s.scalar(select(NwSnapshot).where(NwSnapshot.date == date)):
            raise ValueError(f"snapshot for {date} already exists")
        items = {i.code: i for i in s.scalars(select(NwItem).where(NwItem.active)).all()}
        by_id = {i.id: i for i in items.values()}
        supplied = {}
        for v in values:
            it = by_id.get(v.get("item_id")) or items.get(v.get("code"))
            if it is None:
                raise ValueError(f"unknown item: {v.get('code') or v.get('item_id')}")
            supplied[it.code] = v

        snap = NwSnapshot(date=date, note=note, portfolio_value_sgd=live_portfolio_sgd(s))
        s.add(snap)
        s.flush()
        for code, it in items.items():
            v = supplied.get(code, {})
            native = Decimal(str(v.get("native_value", 0) or 0))
            ccy = (v.get("currency") or it.currency_default or "SGD").upper()
            rate = rate_for(s, ccy, date)
            s.add(NwValue(snapshot_id=snap.id, item_id=it.id, native_value=native,
                          currency=ccy, rate_to_sgd=rate, value_sgd=(native * rate)))
        s.commit()
        s.refresh(snap)
        return snapshot_detail(snap)
    finally:
        if own:
            s.close()


def update_snapshot(snap_id: int, values: list[dict], note: str | None = None,
                    s: Session | None = None) -> dict | None:
    """Edit an existing snapshot in place — the path for filling manual fields (CPF, HDB,
    loan, POSB, IBKR ...) after a statement ingest, without a duplicate-date conflict.

    Only supplied items are changed; their FX rate is re-frozen at the snapshot's OWN date
    (history stays stable) and value_sgd recomputed. Items not supplied and the frozen
    portfolio_value_sgd are left untouched. Returns the detail, or None if the id is unknown."""
    own = s is None
    s = s or SessionLocal()
    try:
        snap = s.get(NwSnapshot, snap_id)
        if snap is None:
            return None
        items = {i.code: i for i in s.scalars(select(NwItem).where(NwItem.active)).all()}
        by_id = {i.id: i for i in items.values()}
        existing = {v.item_id: v for v in snap.values}
        for v in values:
            it = by_id.get(v.get("item_id")) or items.get(v.get("code"))
            if it is None:
                raise ValueError(f"unknown item: {v.get('code') or v.get('item_id')}")
            native = Decimal(str(v.get("native_value", 0) or 0))
            ccy = (v.get("currency") or it.currency_default or "SGD").upper()
            rate = rate_for(s, ccy, snap.date)
            row = existing.get(it.id)
            if row is None:                                 # item added after this snapshot
                s.add(NwValue(snapshot_id=snap.id, item_id=it.id, native_value=native,
                              currency=ccy, rate_to_sgd=rate, value_sgd=(native * rate)))
            else:
                row.native_value, row.currency = native, ccy
                row.rate_to_sgd, row.value_sgd = rate, native * rate
        if note is not None:
            snap.note = note
        s.commit()
        s.refresh(snap)
        return snapshot_detail(snap)
    finally:
        if own:
            s.close()


def delete_snapshot(snap_id: int, s: Session | None = None) -> bool:
    own = s is None
    s = s or SessionLocal()
    try:
        snap = s.get(NwSnapshot, snap_id)
        if snap is None:
            return False
        s.delete(snap)
        s.commit()
        return True
    finally:
        if own:
            s.close()
