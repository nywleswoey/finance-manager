"""The spending, recurring and classify handlers map each domain outcome to its HTTP status.

test_route_mounting.py proves the router is reachable and test_spending_access.py the 403 gate;
neither says what a handler answers when the domain refuses. Here: a blank recurring name is
400, a bad condition set / unknown category pair / unknown reorder id is 400, and deleting a rule
that still owns classified spends is 409 (`RuleInUse`, deactivate instead) while an unknown rule
is 404. `RuleInUse` is not a ValueError, so a handler that dropped its own `except` would turn
that 409 into a 500 — pinned below. Each success path also asserts the stub got the parsed
arguments, so a handler that stops forwarding a field fails here.

No DB: the handlers import their domain function inside the body, so each stub is set on the
defining module (`portfolio.recurring`, `portfolio.classify`, `portfolio.spending`) and is the
one the handler picks up at call time.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_spending_handlers.py -q

The client is conftest's `owner_client`: through the real cookie gate as OWNER, who is on
SPENDING_EMAILS. The bypass `client` would also get through (can_view_spending returns True
under the dev bypass), but the owner cookie exercises the capability check these paths
actually sit behind in production and does not depend on VERCEL being unset.
"""
from portfolio import classify, recurring
from portfolio import spending as sp

COND = {"field": "merchant", "operator": "contains", "value": "GRAB"}


def _raise(exc):
    def stub(*a, **k):
        raise exc
    return stub


def _record(ret):
    """A stub that records its call (args, kwargs) and returns `ret`."""
    calls = []

    def stub(*a, **k):
        calls.append((a, k))
        return ret
    stub.calls = calls
    return stub


def _never():
    return _raise(AssertionError("handler must not reach the domain"))


# ---------------- plain reads (portfolio.spending) ----------------
def test_summary_forwards_the_from_to_aliases(owner_client, monkeypatch):
    stub = _record({"total": 1})
    monkeypatch.setattr(sp, "summary", stub)
    r = owner_client.get("/api/spending/summary?from=2026-01-01&to=2026-06-30")
    assert r.status_code == 200
    assert r.json() == {"total": 1}
    assert stub.calls == [(("2026-01-01", "2026-06-30"), {})]


def test_transactions_forwards_every_filter(owner_client, monkeypatch):
    stub = _record([])
    monkeypatch.setattr(sp, "transactions", stub)
    owner_client.get("/api/spending/transactions")
    owner_client.get("/api/spending/transactions?from=2026-01-01&to=2026-02-01&group=Food"
                     "&subcategory=Dining&source=dbs&include_excluded=true&limit=10")
    assert stub.calls == [
        ((None, None, None, None, None, False, 500), {}),          # defaults
        (("2026-01-01", "2026-02-01", "Food", "Dining", "dbs", True, 10), {}),
    ]


# ---------------- recurring ----------------
def test_recurring_list_passes_through(owner_client, monkeypatch):
    monkeypatch.setattr(recurring, "list_recurring", lambda: [{"id": 1}])
    assert owner_client.get("/api/spending/recurring").json() == [{"id": 1}]


def test_recurring_add_forwards_stripped_name_and_fields(owner_client, monkeypatch):
    stub = _record(11)
    monkeypatch.setattr(recurring, "add", stub)
    r = owner_client.post("/api/spending/recurring", json={
        "name": "  Netflix  ", "merchant_match": "NETFLIX", "cadence": "yearly",
        "expected_amount": 19.98, "expected_day": 3, "notes": "hd"})
    assert r.status_code == 200
    assert r.json() == {"id": 11}
    assert stub.calls == [(("Netflix", "NETFLIX", "yearly", 19.98, 3, "hd"), {})]


def test_recurring_add_blank_name_is_400(owner_client, monkeypatch):
    monkeypatch.setattr(recurring, "add", _never())
    for name in ("", "   "):
        r = owner_client.post("/api/spending/recurring", json={"name": name})
        assert r.status_code == 400, name
        assert r.json()["detail"] == "name is required"


def test_recurring_delete_is_always_ok(owner_client, monkeypatch):
    # no existence check: the domain DELETE is a no-op on an unknown id and the handler says ok
    stub = _record(None)
    monkeypatch.setattr(recurring, "delete", stub)
    r = owner_client.delete("/api/spending/recurring/42")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert stub.calls == [((42,), {})]


def test_recurring_dismiss_forwards_stripped_merchant(owner_client, monkeypatch):
    stub = _record(None)
    monkeypatch.setattr(recurring, "dismiss", stub)
    r = owner_client.post("/api/spending/recurring/dismiss", json={"merchant": " SPOTIFY "})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert stub.calls == [(("SPOTIFY",), {})]


def test_recurring_dismiss_merchant_is_bounded(owner_client, monkeypatch):
    stub = _record(None)
    monkeypatch.setattr(recurring, "dismiss", stub)
    for merchant in ("", "x" * 129):
        r = owner_client.post("/api/spending/recurring/dismiss", json={"merchant": merchant})
        assert r.status_code == 422, len(merchant)
    assert stub.calls == []
    assert owner_client.post("/api/spending/recurring/dismiss",
                             json={"merchant": "x" * 128}).status_code == 200


# ---------------- classify: create / manual / unclassify ----------------
def test_rule_create_forwards_parsed_body(owner_client, monkeypatch):
    stub = _record({"id": 3, "classified": 2})
    monkeypatch.setattr(classify, "create_rule", stub)
    r = owner_client.post("/api/spending/classify/rules", json={
        "nl_text": "  grab rides are transport  ",
        "conditions": [COND, {"field": "amount", "operator": "between",
                              "value_min": 5, "value_max": 50}],
        "category": "Transport", "subcategory": "Ride-hailing"})
    assert r.status_code == 200
    assert r.json() == {"id": 3, "classified": 2}
    # nl_text stripped; each condition dumped with its None fields dropped
    assert stub.calls == [(("grab rides are transport",
                            [COND, {"field": "amount", "operator": "between",
                                    "value_min": 5.0, "value_max": 50.0}],
                            "Transport", "Ride-hailing"), {})]


def test_rule_create_value_error_is_400(owner_client, monkeypatch):
    monkeypatch.setattr(classify, "create_rule", _raise(ValueError("unknown category pair")))
    r = owner_client.post("/api/spending/classify/rules", json={
        "nl_text": "x", "conditions": [COND], "category": "A", "subcategory": "B"})
    assert r.status_code == 400
    assert r.json()["detail"] == "unknown category pair"


def test_rule_create_conditions_are_bounded_1_to_10(owner_client, monkeypatch):
    monkeypatch.setattr(classify, "create_rule", _never())
    base = {"nl_text": "x", "category": "A", "subcategory": "B"}
    for conds in ([], [COND] * 11):
        r = owner_client.post("/api/spending/classify/rules", json={**base, "conditions": conds})
        assert r.status_code == 422, len(conds)


def test_manual_forwards_and_value_error_is_400(owner_client, monkeypatch):
    stub = _record({"updated": 2})
    monkeypatch.setattr(classify, "manual_classify", stub)
    body = {"spend_ids": [1, 2], "category": "Food", "subcategory": "Dining"}
    r = owner_client.post("/api/spending/classify/manual", json=body)
    assert r.status_code == 200
    assert r.json() == {"updated": 2}
    assert stub.calls == [(([1, 2], "Food", "Dining"), {})]

    monkeypatch.setattr(classify, "manual_classify", _raise(ValueError("unknown category pair")))
    r = owner_client.post("/api/spending/classify/manual", json=body)
    assert r.status_code == 400
    assert r.json()["detail"] == "unknown category pair"


def test_manual_spend_ids_are_bounded_1_to_1000(owner_client, monkeypatch):
    monkeypatch.setattr(classify, "manual_classify", _never())
    for ids in ([], list(range(1001))):
        r = owner_client.post("/api/spending/classify/manual", json={
            "spend_ids": ids, "category": "Food", "subcategory": "Dining"})
        assert r.status_code == 422, len(ids)


def test_unclassify_forwards_ids(owner_client, monkeypatch):
    stub = _record({"updated": 3})
    monkeypatch.setattr(classify, "unclassify", stub)
    r = owner_client.post("/api/spending/classify/unclassify", json={"spend_ids": [4, 5, 6]})
    assert r.status_code == 200
    assert stub.calls == [(([4, 5, 6],), {})]


# ---------------- classify: rule lifecycle ----------------
def test_reorder_forwards_and_unknown_id_is_400(owner_client, monkeypatch):
    stub = _record({"reordered": 3})
    monkeypatch.setattr(classify, "reorder", stub)
    r = owner_client.post("/api/spending/classify/rules/reorder", json={"ordered_ids": [3, 1, 2]})
    assert r.status_code == 200
    assert stub.calls == [(([3, 1, 2],), {})]

    monkeypatch.setattr(classify, "reorder", _raise(ValueError("unknown rule id(s): [9]")))
    r = owner_client.post("/api/spending/classify/rules/reorder", json={"ordered_ids": [9]})
    assert r.status_code == 400


def test_edit_preview_and_edit_forward_kwargs(owner_client, monkeypatch):
    for path, name, method in (("/api/spending/classify/rules/8/preview", "edit_preview", "post"),
                               ("/api/spending/classify/rules/8", "edit_rule", "put")):
        stub = _record({"ok": name})
        monkeypatch.setattr(classify, name, stub)
        send = getattr(owner_client, method)
        # an omitted field reaches the domain as None ("leave unchanged"), conditions included
        assert send(path, json={"nl_text": "new"}).status_code == 200
        assert send(path, json={"conditions": [COND], "category": "A",
                                "subcategory": "B"}).json() == {"ok": name}
        assert stub.calls == [
            ((8,), {"conditions": None, "category": None, "subcategory": None,
                    "nl_text": "new"}),
            ((8,), {"conditions": [COND], "category": "A", "subcategory": "B",
                    "nl_text": None}),
        ], name


def test_edit_preview_and_edit_value_error_is_400(owner_client, monkeypatch):
    # Inconsistency, pinned as-is: an unknown rule is 400 here (every ValueError is), but 404
    # on activate / deactivate / delete below.
    for path, name, method in (("/api/spending/classify/rules/8/preview", "edit_preview", "post"),
                               ("/api/spending/classify/rules/8", "edit_rule", "put")):
        monkeypatch.setattr(classify, name, _raise(ValueError("unknown rule 8")))
        r = getattr(owner_client, method)(path, json={})
        assert r.status_code == 400, name
        assert r.json()["detail"] == "unknown rule 8"


def test_edit_conditions_capped_at_10(owner_client, monkeypatch):
    monkeypatch.setattr(classify, "edit_rule", _never())
    r = owner_client.put("/api/spending/classify/rules/8", json={"conditions": [COND] * 11})
    assert r.status_code == 422


def test_activate_and_deactivate_forward_the_flag(owner_client, monkeypatch):
    stub = _record({"id": 8})
    monkeypatch.setattr(classify, "set_active", stub)
    assert owner_client.post("/api/spending/classify/rules/8/deactivate").status_code == 200
    assert owner_client.post("/api/spending/classify/rules/8/activate").status_code == 200
    assert stub.calls == [((8, False), {}), ((8, True), {})]


def test_activate_and_deactivate_unknown_rule_is_404(owner_client, monkeypatch):
    monkeypatch.setattr(classify, "set_active", _raise(ValueError("unknown rule 8")))
    for verb in ("activate", "deactivate"):
        r = owner_client.post(f"/api/spending/classify/rules/8/{verb}")
        assert r.status_code == 404, verb
        assert r.json()["detail"] == "unknown rule 8"


def test_delete_rule_ok(owner_client, monkeypatch):
    stub = _record({"deleted": 8})
    monkeypatch.setattr(classify, "delete_rule", stub)
    r = owner_client.delete("/api/spending/classify/rules/8")
    assert r.status_code == 200
    assert r.json() == {"deleted": 8}
    assert stub.calls == [((8,), {})]


def test_delete_rule_in_use_is_409(owner_client, monkeypatch):
    # RuleInUse is its own Exception, not a ValueError: only the handler's dedicated except
    # keeps this from being a 500 (or, were it a ValueError, a 404)
    assert not issubclass(classify.RuleInUse, ValueError)
    msg = "rule 8 has 3 classified spend(s); deactivate instead"
    monkeypatch.setattr(classify, "delete_rule", _raise(classify.RuleInUse(msg)))
    r = owner_client.delete("/api/spending/classify/rules/8")
    assert r.status_code == 409
    assert r.json()["detail"] == msg


def test_delete_unknown_rule_is_404(owner_client, monkeypatch):
    monkeypatch.setattr(classify, "delete_rule", _raise(ValueError("unknown rule 8")))
    r = owner_client.delete("/api/spending/classify/rules/8")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown rule 8"
