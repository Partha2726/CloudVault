"""T14 concurrency: Apply vs Apply, upload, delete, undelete, refresh; independence across documents.

Every test checks final DB and simulated-store state and that nothing leaks.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.storage import get_storage
from tests.integration.test_document_concurrency import assert_pools_idle
from tests.integration.test_recommendations import (
    BIG,
    assert_applied,
    current_version,
    doc_row,
    one_rec,
    rec_row,
    store_entries,
)
from tests.integration.test_version_concurrency import Gate, wait_blocked

WAIT = 10


def call(app, method, path, headers, **kwargs):
    return getattr(TestClient(app, raise_server_exceptions=False), method)(path, headers=headers, **kwargs)


def apply_req(app, headers, rec_id):
    return call(app, "post", f"/api/recommendations/{rec_id}/apply", headers)


def code(r):
    body = r.json()
    return r.status_code, body.get("status") or body.get("error", {}).get("code")


def test_two_simultaneous_applies(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"]).s3_version_id
    gate = Gate("copy_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(apply_req, app, alice, rec["id"])
        assert gate.entered.wait(WAIT)
        second = pool.submit(apply_req, app, alice, rec["id"])
        wait_blocked(second)
        gate.release.set()
        results = [code(first.result(WAIT)), code(second.result(WAIT))]
    assert results == [(200, "APPLIED"), (200, "APPLIED")]  # the second is the W11 no-op
    assert gate.calls == 1  # exactly one copy
    assert_applied(db, doc["id"], "STANDARD_IA", old)
    assert_pools_idle(db)


def test_apply_then_upload(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    gate = Gate("copy_object")
    app.dependency_overrides[get_storage] = lambda: gate
    files = {"file": ("cold.txt", b"z" * BIG, "application/octet-stream")}
    with ThreadPoolExecutor(2) as pool:
        ap = pool.submit(apply_req, app, alice, rec["id"])
        assert gate.entered.wait(WAIT)
        up = pool.submit(call, app, "post", f"/api/documents/{doc['id']}/versions", alice, files=files)
        wait_blocked(up)
        gate.release.set()
        assert code(ap.result(WAIT)) == (200, "APPLIED")
        assert up.result(WAIT).status_code == 201
    from tests.integration.test_versions import db_versions
    versions = db_versions(db, doc["id"])
    assert [(v[0], v[1], v[5]) for v in versions] == [(1, "ACTIVE", "STANDARD_IA"), (2, "ACTIVE", "STANDARD")]
    entries = store_entries(db, doc["id"])
    assert [e.version_id for e in entries] == [versions[1][2], versions[0][2]]  # v2 newest, then v1's IA copy
    assert [e.storage_class for e in entries] == ["STANDARD", "STANDARD_IA"]
    assert current_version(db, doc["id"]).version_number == 2
    assert_pools_idle(db)


def test_upload_then_apply_is_stale(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    gate = Gate("put_object")
    app.dependency_overrides[get_storage] = lambda: gate
    files = {"file": ("cold.txt", b"z" * BIG, "application/octet-stream")}
    with ThreadPoolExecutor(2) as pool:
        up = pool.submit(call, app, "post", f"/api/documents/{doc['id']}/versions", alice, files=files)
        assert gate.entered.wait(WAIT)
        ap = pool.submit(apply_req, app, alice, rec["id"])
        wait_blocked(ap)
        gate.release.set()
        assert up.result(WAIT).status_code == 201
        assert code(ap.result(WAIT)) == (409, "STALE_RECOMMENDATION")
    assert rec_row(db, rec["id"]).status == "STALE"
    assert all(e.storage_class == "STANDARD" for e in store_entries(db, doc["id"]))
    assert len(store_entries(db, doc["id"])) == 2 and doc_row(db, doc["id"]).pending_op is None
    assert_pools_idle(db)


def test_apply_then_delete(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    gate = Gate("copy_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        ap = pool.submit(apply_req, app, alice, rec["id"])
        assert gate.entered.wait(WAIT)
        rm = pool.submit(call, app, "delete", f"/api/documents/{doc['id']}", alice)
        wait_blocked(rm)
        gate.release.set()
        assert code(ap.result(WAIT)) == (200, "APPLIED")
        assert rm.result(WAIT).status_code == 204
    d, v = doc_row(db, doc["id"]), current_version(db, doc["id"])
    assert (d.status, d.pending_op, v.storage_class) == ("DELETED", None, "STANDARD_IA")
    entries = store_entries(db, doc["id"])
    assert [e.is_delete_marker for e in entries] == [True, False]  # marker over the IA copy; old gone
    assert entries[1].version_id == v.s3_version_id
    assert_pools_idle(db)


def test_delete_then_apply_is_stale(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    gate = Gate("delete_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        rm = pool.submit(call, app, "delete", f"/api/documents/{doc['id']}", alice)
        assert gate.entered.wait(WAIT)
        ap = pool.submit(apply_req, app, alice, rec["id"])
        wait_blocked(ap)
        gate.release.set()
        assert rm.result(WAIT).status_code == 204
        assert code(ap.result(WAIT)) == (409, "STALE_RECOMMENDATION")
    assert [e.storage_class for e in store_entries(db, doc["id"]) if not e.is_delete_marker] == ["STANDARD"]
    assert_pools_idle(db)


def test_undelete_then_apply(app, client, alice, cold, db):
    """A trashed document's open recommendation becomes usable again once it is undeleted."""
    doc = cold()
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"]).s3_version_id
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    gate = Gate("delete_version")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        ud = pool.submit(call, app, "post", f"/api/documents/{doc['id']}/undelete", alice)
        assert gate.entered.wait(WAIT)
        ap = pool.submit(apply_req, app, alice, rec["id"])
        wait_blocked(ap)
        gate.release.set()
        assert ud.result(WAIT).status_code == 200
        assert code(ap.result(WAIT)) == (200, "APPLIED")
    assert doc_row(db, doc["id"]).status == "ACTIVE"
    assert_applied(db, doc["id"], "STANDARD_IA", old)
    assert_pools_idle(db)


def test_refresh_during_apply_leaves_the_applying_document_alone(app, client, alice, cold, db):
    cold()
    rec = one_rec(client, alice)
    gate = Gate("copy_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        ap = pool.submit(apply_req, app, alice, rec["id"])
        assert gate.entered.wait(WAIT)
        fresh = call(app, "post", "/api/recommendations/refresh", alice).json()["items"]
        gate.release.set()
        assert code(ap.result(WAIT)) == (200, "APPLIED")
    assert fresh == []  # the document with an Apply in flight was skipped
    assert rec_row(db, rec["id"]).status == "APPLIED"
    assert_pools_idle(db)


def test_applies_on_different_documents_run_concurrently(app, client, alice, cold, db):
    docs = [cold(f"c{i}.txt", fill=bytes([97 + i])) for i in range(2)]
    items = client.post("/api/recommendations/refresh", headers=alice).json()["items"]
    recs = {r["document_id"]: r for r in items}
    barrier = threading.Barrier(2, timeout=WAIT)  # both copies must be in progress together
    app.dependency_overrides[get_storage] = lambda: Gate("copy_object", barrier=barrier)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda d: code(apply_req(app, alice, recs[d["id"]]["id"])), docs))
    assert results == [(200, "APPLIED"), (200, "APPLIED")]
    for d in docs:
        assert current_version(db, d["id"]).storage_class == "STANDARD_IA"
        assert len(store_entries(db, d["id"])) == 1
    assert_pools_idle(db)
