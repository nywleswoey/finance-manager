"""The net-worth handlers map each domain outcome to its HTTP status, and forward their bodies.

test_route_mounting.py proves the router is reachable and test_auth.py the gate; neither says
what a handler answers when the domain refuses. That mapping is the whole of these handlers:
a missing snapshot is 404, a duplicate date 409, a bad FX pair or unknown item 400. Swap two
of those and the UI shows the wrong message (or retries a conflict) with every other test green.

No DB: every `portfolio.networth` call is stubbed on the module (the router reads it through
the `nw` alias at call time), and each stub records what it was handed.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_networth_handlers.py -q

The client is conftest's `client` (gate bypassed): these paths sit behind authentication only,
which the mounting and auth tests already cover through the real cookie.
"""
import datetime as dt

from portfolio import networth as nw

# model_dump() of one NwValueIn: every field, defaults included, is what the domain receives
VALUE = {"code": "CPF_OA", "item_id": None, "native_value": 1200.5, "currency": "SGD"}


def _raise(exc):
    def stub(*a, **k):
        raise exc
    return stub


# ---- pass-through reads ----
def test_reads_pass_the_domain_result_through(client, monkeypatch):
    monkeypatch.setattr(nw, "catalogue", lambda: [{"code": "CPF_OA"}])
    monkeypatch.setattr(nw, "list_snapshots", lambda: [{"id": 1}, {"id": 2}])
    monkeypatch.setattr(nw, "composition", lambda: {"bands": [], "series": [], "dropped": []})
    assert client.get("/api/networth/items").json() == [{"code": "CPF_OA"}]
    assert client.get("/api/networth/snapshots").json() == [{"id": 1}, {"id": 2}]
    assert client.get("/api/networth/composition").json() == \
        {"bands": [], "series": [], "dropped": []}


# ---- GET /snapshots/{id} ----
def test_get_snapshot_found(client, monkeypatch):
    seen = []
    monkeypatch.setattr(nw, "get_snapshot", lambda sid: seen.append(sid) or {"id": sid})
    r = client.get("/api/networth/snapshots/7")
    assert r.status_code == 200
    assert r.json() == {"id": 7}
    assert seen == [7]                       # path param parsed to int


def test_get_snapshot_missing_is_404(client, monkeypatch):
    monkeypatch.setattr(nw, "get_snapshot", lambda sid: None)
    r = client.get("/api/networth/snapshots/7")
    assert r.status_code == 404
    assert r.json()["detail"] == "snapshot not found"


def test_get_snapshot_non_int_id_is_422(client, monkeypatch):
    monkeypatch.setattr(nw, "get_snapshot", _raise(AssertionError("handler must not run")))
    assert client.get("/api/networth/snapshots/abc").status_code == 422


# ---- POST /snapshots ----
def test_create_forwards_date_values_and_note(client, monkeypatch):
    seen = []
    monkeypatch.setattr(nw, "create_snapshot",
                        lambda date, values, note: seen.append((date, values, note)) or {"id": 9})
    r = client.post("/api/networth/snapshots", json={
        "date": "2026-09-30", "note": "Q3",
        "values": [{"code": "CPF_OA", "native_value": 1200.5, "currency": "SGD"}]})
    assert r.status_code == 200
    assert r.json() == {"id": 9}
    assert seen == [(dt.date(2026, 9, 30), [VALUE], "Q3")]


def test_create_defaults_to_no_values_and_no_note(client, monkeypatch):
    seen = []
    monkeypatch.setattr(nw, "create_snapshot",
                        lambda date, values, note: seen.append((date, values, note)) or {})
    assert client.post("/api/networth/snapshots", json={"date": "2026-09-30"}).status_code == 200
    assert seen == [(dt.date(2026, 9, 30), [], None)]


def test_create_duplicate_date_is_409(client, monkeypatch):
    # the domain's own exception type is the signal, not its message
    monkeypatch.setattr(nw, "create_snapshot",
                        _raise(nw.SnapshotExists("snapshot for 2026-09-30 already exists")))
    r = client.post("/api/networth/snapshots", json={"date": "2026-09-30"})
    assert r.status_code == 409
    assert r.json()["detail"] == "snapshot for 2026-09-30 already exists"


def test_create_other_value_error_is_400(client, monkeypatch):
    monkeypatch.setattr(nw, "create_snapshot", _raise(ValueError("no FX rate for USD")))
    r = client.post("/api/networth/snapshots", json={"date": "2026-09-30"})
    assert r.status_code == 400
    assert r.json()["detail"] == "no FX rate for USD"


def test_create_body_validation_is_422(client, monkeypatch):
    # NwSnapshotIn has no bounds; what it does refuse is a missing/unparseable date or a
    # non-numeric value. The handler never runs.
    monkeypatch.setattr(nw, "create_snapshot", _raise(AssertionError("handler must not run")))
    for body in ({}, {"date": "not-a-date"},
                 {"date": "2026-09-30", "values": [{"native_value": "lots"}]}):
        assert client.post("/api/networth/snapshots", json=body).status_code == 422, body


# ---- PATCH /snapshots/{id} ----
def test_update_forwards_id_values_and_note(client, monkeypatch):
    seen = []
    monkeypatch.setattr(nw, "update_snapshot",
                        lambda sid, values, note: seen.append((sid, values, note)) or {"id": sid})
    r = client.patch("/api/networth/snapshots/4", json={
        "note": "filled", "values": [{"code": "CPF_OA", "native_value": 1200.5,
                                      "currency": "SGD"}]})
    assert r.status_code == 200
    assert r.json() == {"id": 4}
    assert seen == [(4, [VALUE], "filled")]


def test_update_value_error_is_400(client, monkeypatch):
    monkeypatch.setattr(nw, "update_snapshot", _raise(ValueError("unknown item 'NOPE'")))
    r = client.patch("/api/networth/snapshots/4", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "unknown item 'NOPE'"


def test_update_value_error_saying_already_exists_is_still_400(client, monkeypatch):
    # update has no duplicate-date case to map to 409
    monkeypatch.setattr(nw, "update_snapshot", _raise(ValueError("x already exists")))
    assert client.patch("/api/networth/snapshots/4", json={}).status_code == 400


def test_update_missing_is_404(client, monkeypatch):
    monkeypatch.setattr(nw, "update_snapshot", lambda sid, values, note: None)
    r = client.patch("/api/networth/snapshots/4", json={})
    assert r.status_code == 404
    assert r.json()["detail"] == "snapshot not found"


# ---- DELETE /snapshots/{id} ----
def test_delete_ok(client, monkeypatch):
    seen = []
    monkeypatch.setattr(nw, "delete_snapshot", lambda sid: seen.append(sid) or True)
    r = client.delete("/api/networth/snapshots/5")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert seen == [5]


def test_delete_missing_is_404(client, monkeypatch):
    monkeypatch.setattr(nw, "delete_snapshot", lambda sid: False)
    r = client.delete("/api/networth/snapshots/5")
    assert r.status_code == 404
    assert r.json()["detail"] == "snapshot not found"
