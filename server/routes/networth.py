"""Net worth product routes: items catalogue, snapshots, composition history.

Split out of server/main.py (Slice 3 of the codebase reorg) to match web/src/modules/networth.
server.main stays the composition root and re-exports NwValueIn (tests import it from there).
"""
import datetime as _dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from portfolio import networth as nw

router = APIRouter(prefix="/api/networth")


class NwValueIn(BaseModel):
    code: str | None = None
    item_id: int | None = None
    native_value: float = 0
    currency: str | None = None


class NwSnapshotIn(BaseModel):
    date: _dt.date
    note: str | None = None
    values: list[NwValueIn] = []


@router.get("/items")
def nw_items():
    return nw.catalogue()


@router.get("/snapshots")
def nw_snapshots():
    return nw.list_snapshots()


@router.get("/latest")
def nw_latest():
    return nw.latest()


@router.get("/composition")
def nw_composition():
    """`{bands, series, dropped}` — the composition chart's band-level history, ascending by date.
    Its own path rather than a widened /snapshots: see portfolio.networth.composition."""
    return nw.composition()


@router.get("/snapshots/{snap_id}")
def nw_get(snap_id: int):
    d = nw.get_snapshot(snap_id)
    if d is None:
        raise HTTPException(404, "snapshot not found")
    return d


@router.post("/snapshots")
def nw_create(body: NwSnapshotIn):
    try:
        return nw.create_snapshot(body.date, [v.model_dump() for v in body.values], body.note)
    except nw.SnapshotExists as e:
        raise HTTPException(409, str(e))                    # duplicate date
    except ValueError as e:
        raise HTTPException(400, str(e))                    # missing FX / unknown item


class NwUpdateIn(BaseModel):
    note: str | None = None
    values: list[NwValueIn] = []


@router.patch("/snapshots/{snap_id}")
def nw_update(snap_id: int, body: NwUpdateIn):
    """Edit an existing snapshot's values (fill manual fields after a statement ingest)."""
    try:
        d = nw.update_snapshot(snap_id, [v.model_dump() for v in body.values], body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))                    # bad FX / unknown item
    if d is None:
        raise HTTPException(404, "snapshot not found")
    return d


@router.delete("/snapshots/{snap_id}")
def nw_delete(snap_id: int):
    if not nw.delete_snapshot(snap_id):
        raise HTTPException(404, "snapshot not found")
    return {"ok": True}
