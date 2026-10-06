"""T10: soft delete, undelete, permanent delete (doc 02.5, 05.5; AM-1, AM-4).

Doc 10.2 I6, I7, I8 and C2, plus idempotency, every failure point, and retries after
partial failure. Final states are checked in the database and the simulated store.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.models import AccessLog, Document, DocumentVersion, ProcessingJob
from app.services import deletion_service
from app.storage import get_storage
from app.storage.base import DeleteResult, StorageError
from tests.conftest import PDF_BYTES
from tests.integration.test_document_concurrency import assert_pools_idle

WAIT = 10


def error(r):
    return r.status_code, r.json()["error"]["code"]


@pytest.fixture
def alice(auth_headers):
    return auth_headers("alice@example.com")


@pytest.fixture
def bob(auth_headers):
    return auth_headers("bob@example.com")


@pytest.fixture
def doc(upload, alice):
    return upload(alice, "report.pdf").json()


def row(db, doc_id) -> Document:
    db.rollback()
    return db.get(Document, uuid.UUID(doc_id), populate_existing=True)


def entries(db, doc_id):
    """Simulated-store versions and markers for the document's key, newest first."""
    return get_storage().list_object_versions(row(db, doc_id).s3_key)


def markers(db, doc_id):
    return [e for e in entries(db, doc_id) if e.is_delete_marker]


def version_rows(db, doc_id):
    db.rollback()
    return [(v.version_number, v.state, v.s3_version_id) for v in db.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(doc_id))
        .order_by(DocumentVersion.version_number)
    )]


def delete(client, headers, doc_id):
    return client.delete(f"/api/documents/{doc_id}", headers=headers)


def undelete(client, headers, doc_id):
    return client.post(f"/api/documents/{doc_id}/undelete", headers=headers)


def purge(client, headers, doc_id, confirm="true"):
    return client.delete(f"/api/documents/{doc_id}/permanent", headers=headers, params={"confirm": confirm})


class StorageWrapper:
    """The real simulated store with selected methods replaced."""

    def __init__(self, **overrides):
        self._inner = get_storage()
        for name, fn in overrides.items():
            setattr(self, name, fn)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def fail_once(monkeypatch, name):
    """Make deletion_service.<name> raise a database error on its first call only."""
    real = getattr(deletion_service, name)
    calls = {"n": 0}

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("COMMIT", {}, Exception("database went away"))
        return real(*args, **kwargs)

    monkeypatch.setattr(deletion_service, name, wrapper)


# ---- I6: soft delete ----

def test_i6_soft_delete_hides_document_and_adds_marker(client, alice, doc, db):
    before_versions = version_rows(db, doc["id"])
    assert delete(client, alice, doc["id"]).status_code == 204

    r = row(db, doc["id"])
    assert (r.status, r.pending_op, r.pending_op_at) == ("DELETED", None, None)
    assert r.deleted_at is not None
    store = entries(db, doc["id"])
    assert [e.is_delete_marker for e in store] == [True, False]
    assert store[0].version_id == r.delete_marker_version_id and store[0].is_latest
    # Data intact: the version is still readable by id; application version rows unchanged.
    assert get_storage().get_object(r.s3_key, store[1].version_id)[1] == PDF_BYTES
    assert version_rows(db, doc["id"]) == before_versions

    assert client.get("/api/documents", headers=alice).json()["total"] == 0
    trash = client.get("/api/documents", headers=alice, params={"status": "deleted"}).json()
    assert [d["id"] for d in trash["items"]] == [doc["id"]]
    detail = client.get(f"/api/documents/{doc['id']}", headers=alice).json()
    assert detail["status"] == "DELETED" and detail["deleted_at"] is not None


def test_soft_delete_is_idempotent(client, alice, doc, db):
    assert delete(client, alice, doc["id"]).status_code == 204
    marker = row(db, doc["id"]).delete_marker_version_id
    assert delete(client, alice, doc["id"]).status_code == 204
    assert [m.version_id for m in markers(db, doc["id"])] == [marker]


def test_delete_scoping_and_validation(client, alice, bob, doc, db):
    assert error(delete(client, bob, doc["id"])) == (404, "NOT_FOUND")
    assert error(delete(client, alice, str(uuid.uuid4()))) == (404, "NOT_FOUND")
    assert error(client.delete("/api/documents/not-a-uuid", headers=alice)) == (422, "VALIDATION_ERROR")
    assert error(client.delete(f"/api/documents/{doc['id']}")) == (401, "UNAUTHORIZED")
    assert row(db, doc["id"]).status == "ACTIVE" and markers(db, doc["id"]) == []


# ---- I7: undelete ----

def test_i7_undelete_removes_marker_and_restores_current_version(client, alice, doc, db):
    before_versions = version_rows(db, doc["id"])
    delete(client, alice, doc["id"])
    r = undelete(client, alice, doc["id"])
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ACTIVE" and body["deleted_at"] is None and body["id"] == doc["id"]
    assert body["current_version"] == doc["current_version"]

    d = row(db, doc["id"])
    assert (d.status, d.delete_marker_version_id, d.deleted_at, d.pending_op) == ("ACTIVE", None, None, None)
    store = entries(db, doc["id"])
    assert [e.is_delete_marker for e in store] == [False] and store[0].is_latest
    assert version_rows(db, doc["id"]) == before_versions
    assert get_storage().get_object(d.s3_key)[1] == PDF_BYTES  # current again in the store
    assert client.get(f"/api/documents/{doc['id']}/download", headers=alice).status_code == 200


def test_second_undelete_is_not_deleted_and_changes_nothing(client, alice, doc, db):
    delete(client, alice, doc["id"])
    assert undelete(client, alice, doc["id"]).status_code == 200
    before = entries(db, doc["id"])
    assert error(undelete(client, alice, doc["id"])) == (409, "NOT_DELETED")
    assert entries(db, doc["id"]) == before


def test_undelete_scoping(client, alice, bob, doc):
    delete(client, alice, doc["id"])
    assert error(undelete(client, bob, doc["id"])) == (404, "NOT_FOUND")


def test_undelete_when_name_now_taken(client, upload, alice, doc, db):
    delete(client, alice, doc["id"])
    newcomer = upload(alice, "REPORT.pdf", PDF_BYTES + b"new").json()
    r = undelete(client, alice, doc["id"])
    assert error(r) == (409, "NAME_EXISTS")
    assert r.json()["error"]["details"] == {"existing_document_id": newcomer["id"]}
    d = row(db, doc["id"])
    assert d.status == "DELETED" and d.pending_op is None
    assert [m.version_id for m in markers(db, doc["id"])] == [d.delete_marker_version_id]


def test_undelete_name_race_puts_object_back_in_trash(client, upload, alice, doc, db, monkeypatch):
    """The name check passes, a same-name upload lands, the finalize hits the unique index."""
    delete(client, alice, doc["id"])
    old_marker = row(db, doc["id"]).delete_marker_version_id
    upload(alice, "report.pdf", PDF_BYTES + b"new")
    real = deletion_service._name_holder
    calls = {"n": 0}

    def miss_first(db_, d):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db_, d)

    monkeypatch.setattr(deletion_service, "_name_holder", miss_first)
    assert error(undelete(client, alice, doc["id"])) == (409, "NAME_EXISTS")
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("DELETED", None)
    store = entries(db, doc["id"])
    assert [e.is_delete_marker for e in store] == [True, False]  # old marker removed, new one added
    assert store[0].version_id == d.delete_marker_version_id != old_marker


# ---- I8: permanent delete ----

def test_i8_permanent_delete_removes_everything(client, alice, doc, db):
    client.get(f"/api/documents/{doc['id']}/download", headers=alice)  # an access-log row
    key = row(db, doc["id"]).s3_key
    delete(client, alice, doc["id"])
    assert purge(client, alice, doc["id"]).status_code == 204

    db.rollback()
    doc_uuid = uuid.UUID(doc["id"])
    for model, column in [(Document, Document.id), (DocumentVersion, DocumentVersion.document_id),
                          (ProcessingJob, ProcessingJob.document_id), (AccessLog, AccessLog.document_id)]:
        assert db.scalar(select(func.count()).select_from(model).where(column == doc_uuid)) == 0
    assert get_storage().list_object_versions(key) == []  # no versions, no markers
    assert error(purge(client, alice, doc["id"])) == (404, "NOT_FOUND")  # repeat after success
    assert error(undelete(client, alice, doc["id"])) == (404, "NOT_FOUND")


def test_permanent_delete_keeps_other_documents(client, upload, alice, doc, db):
    other = upload(alice, "other.pdf", PDF_BYTES + b"x").json()
    delete(client, alice, doc["id"])
    purge(client, alice, doc["id"])
    assert row(db, other["id"]).status == "ACTIVE"
    assert len(entries(db, other["id"])) == 1


@pytest.mark.parametrize("confirm", [None, "false", "no"])
def test_permanent_delete_requires_confirm(client, alice, doc, db, confirm):
    delete(client, alice, doc["id"])
    params = {} if confirm is None else {"confirm": confirm}
    r = client.delete(f"/api/documents/{doc['id']}/permanent", headers=alice, params=params)
    assert error(r) == (422, "VALIDATION_ERROR")
    assert row(db, doc["id"]).status == "DELETED" and len(entries(db, doc["id"])) == 2


def test_permanent_delete_of_active_document_is_refused(client, alice, doc, db):
    assert error(purge(client, alice, doc["id"])) == (409, "NOT_DELETED")
    assert row(db, doc["id"]).status == "ACTIVE" and len(entries(db, doc["id"])) == 1


def test_permanent_delete_scoping(client, alice, bob, doc, db):
    delete(client, alice, doc["id"])
    assert error(purge(client, bob, doc["id"])) == (404, "NOT_FOUND")
    assert row(db, doc["id"]).status == "DELETED"


# ---- failure paths: soft delete ----

def test_soft_delete_store_failure_changes_nothing(app, client, alice, doc, db):
    def broken(key):
        raise StorageError("injected")

    app.dependency_overrides[get_storage] = lambda: StorageWrapper(delete_object=broken)
    assert error(delete(client, alice, doc["id"])) == (502, "STORAGE_ERROR")
    d = row(db, doc["id"])
    assert (d.status, d.pending_op, d.pending_op_at) == ("ACTIVE", None, None)
    assert markers(db, doc["id"]) == []


def test_soft_delete_finalize_failure_rolls_forward_on_retry(client, alice, doc, db, monkeypatch):
    fail_once(monkeypatch, "_finish_soft_delete")
    assert error(delete(client, alice, doc["id"])) == (503, "DB_UNAVAILABLE")
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("ACTIVE", "DELETE")  # store has the marker; DB not yet
    marker = markers(db, doc["id"])[0].version_id

    assert delete(client, alice, doc["id"]).status_code == 204  # retry: recovery finishes the delete
    d = row(db, doc["id"])
    assert (d.status, d.delete_marker_version_id, d.pending_op) == ("DELETED", marker, None)
    assert [m.version_id for m in markers(db, doc["id"])] == [marker]  # never a second marker


def test_interrupted_delete_then_undelete(client, alice, doc, db, monkeypatch):
    fail_once(monkeypatch, "_finish_soft_delete")
    delete(client, alice, doc["id"])
    assert undelete(client, alice, doc["id"]).status_code == 200
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("ACTIVE", None)
    assert markers(db, doc["id"]) == []


def test_stale_delete_intent_without_store_change_is_dropped(client, alice, doc, db):
    """pending_op left behind although the store never changed (e.g. crash before the call)."""
    d = row(db, doc["id"])
    d.pending_op, d.pending_op_at = "DELETE", d.created_at
    db.commit()
    assert delete(client, alice, doc["id"]).status_code == 204
    assert len(markers(db, doc["id"])) == 1 and row(db, doc["id"]).pending_op is None


def test_reads_are_unaffected_by_pending_intent(client, alice, doc, db, monkeypatch):
    fail_once(monkeypatch, "_finish_soft_delete")
    delete(client, alice, doc["id"])
    assert client.get(f"/api/documents/{doc['id']}", headers=alice).json()["status"] == "ACTIVE"


# ---- failure paths: undelete ----

def test_undelete_store_failure_changes_nothing(app, client, alice, doc, db):
    delete(client, alice, doc["id"])

    def broken(key, version_id):
        raise StorageError("injected")

    app.dependency_overrides[get_storage] = lambda: StorageWrapper(delete_version=broken)
    assert error(undelete(client, alice, doc["id"])) == (502, "STORAGE_ERROR")
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("DELETED", None)
    assert [m.version_id for m in markers(db, doc["id"])] == [d.delete_marker_version_id]


def test_undelete_finalize_failure_completes_on_retry(client, alice, doc, db, monkeypatch):
    delete(client, alice, doc["id"])
    fail_once(monkeypatch, "_finish_undelete")
    assert error(undelete(client, alice, doc["id"])) == (503, "DB_UNAVAILABLE")
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("DELETED", "UNDELETE")
    assert markers(db, doc["id"]) == []  # the store already reflects the undelete

    r = undelete(client, alice, doc["id"])  # retry reports the completed undelete
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    assert row(db, doc["id"]).pending_op is None


# ---- failure paths: permanent delete ----

def test_permanent_delete_partial_store_failure_is_resumable(app, client, alice, doc, db):
    delete(client, alice, doc["id"])
    key = row(db, doc["id"]).s3_key

    def partial(k):
        return [DeleteResult(version_id=e.version_id, deleted=False, error="InternalError")
                for e in get_storage().list_object_versions(k)]

    app.dependency_overrides[get_storage] = lambda: StorageWrapper(delete_all_versions=partial)
    assert error(purge(client, alice, doc["id"])) == (502, "STORAGE_ERROR")
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("DELETED", "PURGE")
    assert error(undelete(client, alice, doc["id"])) == (409, "DOCUMENT_DELETED")  # never undo half a purge
    assert delete(client, alice, doc["id"]).status_code == 204  # still in the trash: idempotent

    app.dependency_overrides.pop(get_storage)
    assert purge(client, alice, doc["id"]).status_code == 204
    assert row(db, doc["id"]) is None and get_storage().list_object_versions(key) == []


def test_permanent_delete_store_exception_keeps_document(app, client, alice, doc, db):
    delete(client, alice, doc["id"])

    def broken(k):
        raise StorageError("injected")

    app.dependency_overrides[get_storage] = lambda: StorageWrapper(delete_all_versions=broken)
    assert error(purge(client, alice, doc["id"])) == (502, "STORAGE_ERROR")
    assert row(db, doc["id"]).pending_op == "PURGE" and len(entries(db, doc["id"])) == 2


def test_permanent_delete_row_failure_after_store_purge_is_resumable(client, alice, doc, db, monkeypatch):
    delete(client, alice, doc["id"])
    key = row(db, doc["id"]).s3_key
    fail_once(monkeypatch, "_delete_rows")
    assert error(purge(client, alice, doc["id"])) == (503, "DB_UNAVAILABLE")
    assert row(db, doc["id"]).status == "DELETED"
    assert get_storage().list_object_versions(key) == []  # store already empty

    assert purge(client, alice, doc["id"]).status_code == 204  # repeat removes the rows
    assert row(db, doc["id"]) is None
    assert version_rows(db, doc["id"]) == []


def test_unfinished_apply_intent_is_recovered_before_delete(client, alice, doc, db):
    """APPLY intent with no copy in the store (T14 recovery state A) is dropped, then the delete runs."""
    d = row(db, doc["id"])
    d.pending_op, d.pending_op_at = "APPLY", d.created_at
    db.commit()
    assert delete(client, alice, doc["id"]).status_code == 204
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("DELETED", None)
    assert len(markers(db, doc["id"])) == 1


# ---- C2 and other concurrency ----

class GatedDeleteStorage(StorageWrapper):
    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = 0

    def delete_object(self, key):
        self.calls += 1
        self.entered.set()
        self.release.wait(WAIT)
        return self._inner.delete_object(key)


def call(app, method, path, headers, **kwargs):
    return getattr(TestClient(app, raise_server_exceptions=False), method)(path, headers=headers, **kwargs)


def test_c2_competing_deletes_create_exactly_one_marker(app, alice, doc, db):
    gated = GatedDeleteStorage()
    app.dependency_overrides[get_storage] = lambda: gated
    path = f"/api/documents/{doc['id']}"
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(call, app, "delete", path, alice)
        assert gated.entered.wait(WAIT)  # first holds the document lock inside the store call
        second = pool.submit(call, app, "delete", path, alice)
        threading.Event().wait(0.3)
        assert not second.done(), "second delete ran while the first held the document lock"
        gated.release.set()
        results = [first.result(WAIT), second.result(WAIT)]

    assert [r.status_code for r in results] == [204, 204]
    assert gated.calls == 1  # the second delete saw DELETED and never called the store
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("DELETED", None)
    store = entries(db, doc["id"])
    assert [e.is_delete_marker for e in store] == [True, False]  # exactly one marker
    assert store[0].version_id == d.delete_marker_version_id
    assert [v[1] for v in version_rows(db, doc["id"])] == ["ACTIVE"]
    assert_pools_idle(db)


def test_competing_undeletes(app, client, alice, doc, db):
    delete(client, alice, doc["id"])
    path = f"/api/documents/{doc['id']}/undelete"
    with ThreadPoolExecutor(2) as pool:
        codes = sorted(r.status_code for r in pool.map(lambda _: call(app, "post", path, alice), range(2)))
    assert codes == [200, 409]
    d = row(db, doc["id"])
    assert (d.status, d.pending_op) == ("ACTIVE", None) and markers(db, doc["id"]) == []
    assert_pools_idle(db)


def test_competing_delete_and_permanent_delete(app, client, alice, doc, db):
    """Run together on a trashed document: either order ends with nothing left."""
    delete(client, alice, doc["id"])
    key = row(db, doc["id"]).s3_key
    with ThreadPoolExecutor(2) as pool:
        soft = pool.submit(call, app, "delete", f"/api/documents/{doc['id']}", alice)
        hard = pool.submit(call, app, "delete", f"/api/documents/{doc['id']}/permanent", alice,
                           params={"confirm": "true"})
        results = (soft.result(WAIT), hard.result(WAIT))
    assert results[1].status_code == 204
    assert results[0].status_code in (204, 404)
    assert row(db, doc["id"]) is None and get_storage().list_object_versions(key) == []
    assert_pools_idle(db)


def test_repeated_delete_undelete_cycles_keep_history_clean(client, alice, doc, db):
    before = version_rows(db, doc["id"])
    for _ in range(10):
        assert delete(client, alice, doc["id"]).status_code == 204
        assert undelete(client, alice, doc["id"]).status_code == 200
    assert version_rows(db, doc["id"]) == before
    assert [e.is_delete_marker for e in entries(db, doc["id"])] == [False]
    assert_pools_idle(db)
