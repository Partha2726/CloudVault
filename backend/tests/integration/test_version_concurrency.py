"""T11 concurrency: C1 competing uploads, independence across documents, interleaving with
delete and restore, failures during contention, and no connection/lock leaks.

Every test checks final DB and store state, not only status codes.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import DocumentVersion, ProcessingJob
from app.storage import get_storage
from app.storage.base import StorageError
from tests.conftest import PDF_BYTES
from tests.integration.test_document_concurrency import assert_pools_idle
from tests.integration.test_versions import (
    assert_store_matches_db,
    current_number,
    db_versions,
    fresh_doc,
    store_ids,
)

WAIT = 10


@pytest.fixture
def alice(auth_headers):
    return auth_headers("alice@example.com")


@pytest.fixture
def doc(upload, alice):
    return upload(alice, "report.pdf").json()


class Gate:
    """Wraps the real store; the first call to `method` waits for `release` (optionally failing)."""

    def __init__(self, method, fail_first=False, barrier=None):
        self._inner = get_storage()
        self._method, self._fail_first, self._barrier = method, fail_first, barrier
        self.entered, self.release = threading.Event(), threading.Event()
        self._lock, self.calls = threading.Lock(), 0

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name != self._method:
            return target

        def gated(*args, **kwargs):
            with self._lock:
                self.calls += 1
                first = self.calls == 1
            if self._barrier is not None:
                self._barrier.wait()
            elif first:
                self.entered.set()
                self.release.wait(WAIT)
                if self._fail_first:
                    raise StorageError("injected failure in the first writer")
            return target(*args, **kwargs)

        return gated


def call(app, method, path, headers, **kwargs):
    return getattr(TestClient(app, raise_server_exceptions=False), method)(path, headers=headers, **kwargs)


def version_upload(app, headers, doc_id, data):
    files = {"file": ("report.pdf", data, "application/octet-stream")}
    return call(app, "post", f"/api/documents/{doc_id}/versions", headers, files=files)


def wait_blocked(future):
    """The request must still be waiting (on the document lock) after a short pause."""
    threading.Event().wait(0.3)
    assert not future.done(), "request proceeded while another operation held the document lock"


def jobs_per_version(db, doc_id):
    db.rollback()
    rows = db.execute(
        select(DocumentVersion.version_number, ProcessingJob.status)
        .join(ProcessingJob, ProcessingJob.version_id == DocumentVersion.id)
        .where(DocumentVersion.document_id == fresh_doc(db, doc_id).id)
        .order_by(DocumentVersion.version_number)
    ).all()
    return [tuple(r) for r in rows]


# ---- 1. C1: two competing uploads to the same document ----

def test_c1_competing_uploads_serialize_into_n_and_n_plus_1(app, alice, doc, db):
    gate = Gate("put_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(version_upload, app, alice, doc["id"], PDF_BYTES + b"A")
        assert gate.entered.wait(WAIT)
        second = pool.submit(version_upload, app, alice, doc["id"], PDF_BYTES + b"B")
        wait_blocked(second)
        # Neither writer has a version row while the first is inside storage (AM-9).
        assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE")]
        gate.release.set()
        r1, r2 = first.result(WAIT), second.result(WAIT)

    assert (r1.status_code, r2.status_code) == (201, 201)
    assert (r1.json()["version_number"], r2.json()["version_number"]) == (2, 3)
    versions = db_versions(db, doc["id"])
    assert [(v[0], v[1]) for v in versions] == [(1, "ACTIVE"), (2, "ACTIVE"), (3, "ACTIVE")]
    assert_store_matches_db(db, doc["id"])  # store order == DB order; latest == current
    key = fresh_doc(db, doc["id"]).s3_key
    assert get_storage().get_object(key)[1] == PDF_BYTES + b"B"
    assert current_number(db, doc["id"]) == 3
    assert jobs_per_version(db, doc["id"]) == [(1, "PENDING"), (2, "PENDING"), (3, "PENDING")]
    assert_pools_idle(db)


def test_many_concurrent_uploads_to_one_document(app, alice, doc, db):
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(
            lambda i: version_upload(app, alice, doc["id"], PDF_BYTES + bytes([65 + i])), range(6)
        ))
    assert sorted(r.status_code for r in results) == [201] * 6
    assert sorted(r.json()["version_number"] for r in results) == [2, 3, 4, 5, 6, 7]
    assert [v[0] for v in db_versions(db, doc["id"])] == list(range(1, 8))  # contiguous, no gaps
    assert_store_matches_db(db, doc["id"])
    assert len(jobs_per_version(db, doc["id"])) == 7
    assert_pools_idle(db)


# ---- 2. different documents stay concurrent ----

def test_uploads_to_different_documents_run_concurrently(app, upload, alice, db):
    docs = [upload(alice, f"doc{i}.pdf", PDF_BYTES + bytes([i])).json() for i in range(3)]
    barrier = threading.Barrier(3, timeout=WAIT)  # all three must be inside storage at once
    app.dependency_overrides[get_storage] = lambda: Gate("put_object", barrier=barrier)
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(lambda d: version_upload(app, alice, d["id"], PDF_BYTES + b"v2"), docs))
    assert [r.status_code for r in results] == [201, 201, 201]
    for d in docs:
        assert_store_matches_db(db, d["id"])
    assert_pools_idle(db)


# ---- 3. competing upload and document state transition ----

def test_upload_then_delete(app, alice, doc, db):
    gate = Gate("put_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        up = pool.submit(version_upload, app, alice, doc["id"], PDF_BYTES + b"A")
        assert gate.entered.wait(WAIT)
        rm = pool.submit(call, app, "delete", f"/api/documents/{doc['id']}", alice)
        wait_blocked(rm)
        gate.release.set()
        assert (up.result(WAIT).status_code, rm.result(WAIT).status_code) == (201, 204)

    d = fresh_doc(db, doc["id"])
    assert d.status == "DELETED" and current_number(db, doc["id"]) == 2
    entries = get_storage().list_object_versions(d.s3_key)
    assert [e.is_delete_marker for e in entries] == [True, False, False]  # marker on top of v2
    assert entries[0].version_id == d.delete_marker_version_id
    assert [e.version_id for e in entries[1:]] == [v[2] for v in reversed(db_versions(db, doc["id"]))]
    assert_pools_idle(db)


def test_delete_then_upload(app, alice, doc, db):
    gate = Gate("delete_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        rm = pool.submit(call, app, "delete", f"/api/documents/{doc['id']}", alice)
        assert gate.entered.wait(WAIT)
        up = pool.submit(version_upload, app, alice, doc["id"], PDF_BYTES + b"A")
        wait_blocked(up)
        gate.release.set()
        assert rm.result(WAIT).status_code == 204
        r = up.result(WAIT)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "DOCUMENT_DELETED")
    assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE")]  # no row for the refused upload
    assert len(store_ids(db, doc["id"])) == 2  # v1 + marker
    assert_pools_idle(db)


# ---- 4. restore under concurrent modification ----

def test_restore_and_upload_compete(app, alice, doc, db):
    gate = Gate("copy_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        rs = pool.submit(call, app, "post", f"/api/documents/{doc['id']}/versions/1/restore", alice)
        assert gate.entered.wait(WAIT)
        up = pool.submit(version_upload, app, alice, doc["id"], PDF_BYTES + b"A")
        wait_blocked(up)
        gate.release.set()
        r_restore, r_upload = rs.result(WAIT), up.result(WAIT)

    assert (r_restore.json()["version_number"], r_upload.json()["version_number"]) == (2, 3)
    versions = db_versions(db, doc["id"])
    assert [(v[0], v[3], v[4]) for v in versions] == [(1, "UPLOAD", None), (2, "RESTORE", 1), (3, "UPLOAD", None)]
    assert_store_matches_db(db, doc["id"])
    assert jobs_per_version(db, doc["id"]) == [(1, "PENDING"), (2, "PENDING"), (3, "PENDING")]
    assert_pools_idle(db)


def test_restore_and_delete_compete(app, alice, doc, db):
    gate = Gate("copy_object")
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        rs = pool.submit(call, app, "post", f"/api/documents/{doc['id']}/versions/1/restore", alice)
        assert gate.entered.wait(WAIT)
        rm = pool.submit(call, app, "delete", f"/api/documents/{doc['id']}", alice)
        wait_blocked(rm)
        gate.release.set()
        assert (rs.result(WAIT).status_code, rm.result(WAIT).status_code) == (201, 204)

    d = fresh_doc(db, doc["id"])
    assert d.status == "DELETED" and current_number(db, doc["id"]) == 2
    entries = get_storage().list_object_versions(d.s3_key)
    assert [e.is_delete_marker for e in entries] == [True, False, False]
    assert entries[1].version_id == db_versions(db, doc["id"])[1][2]  # marker sits on the restored version
    assert_pools_idle(db)


def test_competing_restores(app, alice, doc, db):
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(
            lambda _: call(app, "post", f"/api/documents/{doc['id']}/versions/1/restore", alice), range(3)
        ))
    assert sorted(r.json()["version_number"] for r in results) == [2, 3, 4]
    assert_store_matches_db(db, doc["id"])
    assert [j[1] for j in jobs_per_version(db, doc["id"])] == ["PENDING"] * 4
    assert_pools_idle(db)


# ---- 5. failure during a competing upload ----

def test_failed_first_writer_does_not_disturb_the_second(app, alice, doc, db):
    gate = Gate("put_object", fail_first=True)
    app.dependency_overrides[get_storage] = lambda: gate
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(version_upload, app, alice, doc["id"], PDF_BYTES + b"A")
        assert gate.entered.wait(WAIT)
        second = pool.submit(version_upload, app, alice, doc["id"], PDF_BYTES + b"B")
        wait_blocked(second)
        gate.release.set()
        r1, r2 = first.result(WAIT), second.result(WAIT)

    assert (r1.status_code, r1.json()["error"]["code"]) == (502, "STORAGE_ERROR")
    assert (r2.status_code, r2.json()["version_number"]) == (201, 2)  # no row, no gap (AM-9)
    assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE"), (2, "ACTIVE")]
    assert_store_matches_db(db, doc["id"])  # store holds v1 and v2 only, v2 latest and current
    assert jobs_per_version(db, doc["id"]) == [(1, "PENDING"), (2, "PENDING")]
    assert_pools_idle(db)
