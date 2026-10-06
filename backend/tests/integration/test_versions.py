"""T11: versions list, new version (W5) and restore (W6). Doc 10.2 I4, I5; AM-1, AM-2.

Failure paths check that a failed write never becomes current and leaves no orphan.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.models import Document, DocumentVersion, ProcessingJob
from app.services import version_service
from app.storage import get_storage
from app.storage.base import StorageError
from tests.conftest import PDF_BYTES

V2 = PDF_BYTES + b"% version two\n"


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


def new_version(client, headers, doc_id, data=V2, name="report.pdf"):
    files = {"file": (name, data, "application/octet-stream")}
    return client.post(f"/api/documents/{doc_id}/versions", headers=headers, files=files)


def restore(client, headers, doc_id, n):
    return client.post(f"/api/documents/{doc_id}/versions/{n}/restore", headers=headers)


def fresh_doc(db, doc_id) -> Document:
    db.rollback()
    return db.get(Document, uuid.UUID(doc_id), populate_existing=True)


def db_versions(db, doc_id):
    """(number, state, store id, origin, restored_from, class), oldest first."""
    db.rollback()
    return [
        (v.version_number, v.state, v.s3_version_id, v.origin, v.restored_from_version, v.storage_class)
        for v in db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(doc_id))
            .order_by(DocumentVersion.version_number)
        )
    ]


def store_ids(db, doc_id):
    """Store version ids for the key, newest first."""
    return [e.version_id for e in get_storage().list_object_versions(fresh_doc(db, doc_id).s3_key)]


def current_number(db, doc_id):
    d = fresh_doc(db, doc_id)
    return db.get(DocumentVersion, d.current_version_id).version_number


def jobs(db, doc_id):
    db.rollback()
    return {
        db.get(DocumentVersion, j.version_id).version_number: (j.id, j.status, j.text_excerpt)
        for j in db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == uuid.UUID(doc_id)))
    }


def assert_store_matches_db(db, doc_id):
    """Store order == DB order; the store's latest version is the DB's current version."""
    active = [v for v in db_versions(db, doc_id) if v[1] == "ACTIVE"]
    assert store_ids(db, doc_id) == [v[2] for v in reversed(active)]
    assert current_number(db, doc_id) == active[-1][0]


class StorageWrapper:
    def __init__(self, **overrides):
        self._inner = get_storage()
        for name, fn in overrides.items():
            setattr(self, name, fn)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def raise_db_error(*args, **kwargs):
    raise OperationalError("COMMIT", {}, Exception("database went away"))


def raise_storage_error(*args, **kwargs):
    raise StorageError("injected")


# ---- versions list ----

def test_versions_list_for_new_document(client, alice, doc):
    body = client.get(f"/api/documents/{doc['id']}/versions", headers=alice).json()
    assert len(body["items"]) == 1
    v1 = body["items"][0]
    assert v1 == {
        "version_number": 1, "size_bytes": len(PDF_BYTES), "content_type": "application/pdf",
        "sha256": v1["sha256"], "storage_class": "STANDARD", "origin": "UPLOAD",
        "restored_from_version": None, "state": "ACTIVE", "is_current": True, "created_at": v1["created_at"],
    }


def test_versions_list_scoping(client, alice, bob, doc):
    assert error(client.get(f"/api/documents/{doc['id']}/versions", headers=bob)) == (404, "NOT_FOUND")
    assert error(client.get(f"/api/documents/{uuid.uuid4()}/versions", headers=alice)) == (404, "NOT_FOUND")


def test_versions_list_shows_s3_missing(client, alice, doc, db):
    db.execute(text("UPDATE document_versions SET state='S3_MISSING' WHERE document_id=:d AND version_number=1"),
               {"d": doc["id"]})
    db.commit()
    items = client.get(f"/api/documents/{doc['id']}/versions", headers=alice).json()["items"]
    assert [(i["version_number"], i["state"]) for i in items] == [(1, "S3_MISSING")]


def test_versions_list_available_for_trashed_document(client, alice, doc):
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    assert len(client.get(f"/api/documents/{doc['id']}/versions", headers=alice).json()["items"]) == 1


# ---- I4: new version ----

def test_i4_new_version_becomes_current_and_v1_is_kept(client, alice, doc, db):
    v1_job = jobs(db, doc["id"])[1]
    r = new_version(client, alice, doc["id"], name="anything-else.pdf")
    assert r.status_code == 201
    v2 = r.json()
    assert (v2["version_number"], v2["is_current"], v2["origin"], v2["state"]) == (2, True, "UPLOAD", "ACTIVE")
    assert v2["size_bytes"] == len(V2) and v2["restored_from_version"] is None

    detail = client.get(f"/api/documents/{doc['id']}", headers=alice).json()
    assert detail["display_name"] == "report.pdf"  # the uploaded filename never renames the document
    assert detail["current_version"]["version_number"] == 2 and detail["version_count"] == 2
    listed = client.get(f"/api/documents/{doc['id']}/versions", headers=alice).json()["items"]
    assert [(i["version_number"], i["is_current"]) for i in listed] == [(2, True), (1, False)]

    assert_store_matches_db(db, doc["id"])
    key = fresh_doc(db, doc["id"]).s3_key
    v1_store = db_versions(db, doc["id"])[0][2]
    assert get_storage().get_object(key, v1_store)[1] == PDF_BYTES  # v1 retained
    assert get_storage().get_object(key)[1] == V2
    all_jobs = jobs(db, doc["id"])
    assert all_jobs[1] == v1_job and all_jobs[2][1] == "PENDING"


def test_new_version_with_same_content_as_current_is_duplicate(client, alice, doc, db):
    r = new_version(client, alice, doc["id"], data=PDF_BYTES)
    assert r.status_code == 200 and r.json() == {"duplicate": True}
    assert len(db_versions(db, doc["id"])) == 1 and len(store_ids(db, doc["id"])) == 1


def test_new_version_matching_an_older_version_is_new(client, alice, doc, db):
    new_version(client, alice, doc["id"])
    r = new_version(client, alice, doc["id"], data=PDF_BYTES)  # equals v1, not the current v2
    assert r.status_code == 201 and r.json()["version_number"] == 3
    assert_store_matches_db(db, doc["id"])


def test_new_version_refused_for_trashed_document(client, alice, doc, db):
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    assert error(new_version(client, alice, doc["id"])) == (409, "DOCUMENT_DELETED")
    assert len(db_versions(db, doc["id"])) == 1  # no PENDING or FAILED row was created


def test_new_version_scoping_and_validation(client, alice, bob, doc, db):
    assert error(new_version(client, bob, doc["id"])) == (404, "NOT_FOUND")
    assert error(new_version(client, alice, str(uuid.uuid4()))) == (404, "NOT_FOUND")
    assert error(new_version(client, alice, doc["id"], data=b"")) == (400, "EMPTY_FILE")
    assert error(new_version(client, alice, doc["id"], data=b"x", name="x.exe")) == (415, "UNSUPPORTED_TYPE")
    assert len(db_versions(db, doc["id"])) == 1


def test_upload_rate_limit_is_shared_across_upload_endpoints(client, upload, alice, doc):
    codes = [new_version(client, alice, doc["id"], data=V2 + str(i).encode()).status_code for i in range(19)]
    assert codes == [201] * 19  # plus the initial upload: 20 in this minute
    assert error(upload(alice, "another.pdf", PDF_BYTES + b"z")) == (429, "RATE_LIMITED")
    assert error(new_version(client, alice, doc["id"], data=V2 + b"more")) == (429, "RATE_LIMITED")


# ---- I5: restore ----

def test_i5_restore_creates_new_version_with_old_content(client, alice, doc, db):
    new_version(client, alice, doc["id"])
    r = restore(client, alice, doc["id"], 1)
    assert r.status_code == 201
    v3 = r.json()
    assert (v3["version_number"], v3["origin"], v3["restored_from_version"]) == (3, "RESTORE", 1)
    assert v3["is_current"] is True
    listed = client.get(f"/api/documents/{doc['id']}/versions", headers=alice).json()["items"]
    assert v3["sha256"] == listed[-1]["sha256"]  # same content as v1
    assert get_storage().get_object(fresh_doc(db, doc["id"]).s3_key)[1] == PDF_BYTES
    assert_store_matches_db(db, doc["id"])


def test_restore_gets_a_new_job_and_keeps_history(client, alice, doc, db):
    db.execute(text("UPDATE processing_jobs SET status='SUCCEEDED', finished_at=now(), text_excerpt='old text', "
                    "page_count=1 WHERE document_id=:d"), {"d": doc["id"]})
    db.commit()
    before = jobs(db, doc["id"])
    restore(client, alice, doc["id"], 1)
    after = jobs(db, doc["id"])
    assert after[1] == before[1]  # source job untouched (same id, status, excerpt)
    assert after[2][0] != before[1][0] and after[2][1:] == ("PENDING", None)  # new, separate job


def test_restore_is_not_idempotent(client, alice, doc, db):
    assert restore(client, alice, doc["id"], 1).json()["version_number"] == 2
    assert restore(client, alice, doc["id"], 1).json()["version_number"] == 3
    assert len(jobs(db, doc["id"])) == 3
    assert_store_matches_db(db, doc["id"])


def test_restore_always_produces_standard(client, alice, doc, db):
    """Copy without a class is STANDARD (VERIFIED row 4), even from a STANDARD_IA source."""
    d = fresh_doc(db, doc["id"])
    v1_store = db_versions(db, doc["id"])[0][2]
    db.execute(text("UPDATE sim_object_versions SET storage_class='STANDARD_IA' WHERE version_id=:v"),
               {"v": v1_store})
    db.execute(text("UPDATE document_versions SET storage_class='STANDARD_IA' WHERE document_id=:d"),
               {"d": doc["id"]})
    db.commit()
    v2 = restore(client, alice, doc["id"], 1).json()
    assert v2["storage_class"] == "STANDARD"
    v2_store = db_versions(db, doc["id"])[1][2]
    assert get_storage().head_object(d.s3_key, v2_store).storage_class is None  # STANDARD


def test_restore_errors(client, alice, bob, doc, db):
    assert error(restore(client, bob, doc["id"], 1)) == (404, "NOT_FOUND")
    assert error(restore(client, alice, doc["id"], 9)) == (404, "VERSION_NOT_FOUND")
    assert error(restore(client, alice, doc["id"], 0)) == (422, "VALIDATION_ERROR")
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    assert error(restore(client, alice, doc["id"], 1)) == (409, "DOCUMENT_DELETED")
    assert len(db_versions(db, doc["id"])) == 1


def test_restore_of_version_already_s3_missing_is_410_without_store_call(app, client, alice, doc, db):
    new_version(client, alice, doc["id"])
    db.execute(text("UPDATE document_versions SET state='S3_MISSING' WHERE document_id=:d AND version_number=1"),
               {"d": doc["id"]})
    db.commit()
    app.dependency_overrides[get_storage] = lambda: StorageWrapper(copy_object=raise_storage_error)
    assert error(restore(client, alice, doc["id"], 1)) == (410, "VERSION_EXPIRED")
    assert len(db_versions(db, doc["id"])) == 2


def test_restore_when_store_lost_the_source_marks_it_s3_missing(client, alice, doc, db):
    new_version(client, alice, doc["id"])
    key = fresh_doc(db, doc["id"]).s3_key
    v1_store = db_versions(db, doc["id"])[0][2]
    get_storage().delete_version(key, v1_store)  # e.g. lifecycle expired it
    assert error(restore(client, alice, doc["id"], 1)) == (410, "VERSION_EXPIRED")
    versions = db_versions(db, doc["id"])
    assert [(v[0], v[1]) for v in versions] == [(1, "S3_MISSING"), (2, "ACTIVE")]  # no row for the copy
    assert current_number(db, doc["id"]) == 2
    assert len(store_ids(db, doc["id"])) == 1  # nothing recreated
    listed = client.get(f"/api/documents/{doc['id']}/versions", headers=alice).json()["items"]
    assert [(i["version_number"], i["state"]) for i in listed] == [(2, "ACTIVE"), (1, "S3_MISSING")]
    assert error(restore(client, alice, doc["id"], 1)) == (410, "VERSION_EXPIRED")


# ---- failures: new version ----

def test_store_write_failure_writes_no_version(app, client, alice, doc, db):
    app.dependency_overrides[get_storage] = lambda: StorageWrapper(put_object=raise_storage_error)
    assert error(new_version(client, alice, doc["id"])) == (502, "STORAGE_ERROR")
    assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE")]  # AM-9: no row without a store id
    assert current_number(db, doc["id"]) == 1 and len(jobs(db, doc["id"])) == 1
    assert_store_matches_db(db, doc["id"])

    app.dependency_overrides.pop(get_storage)
    assert new_version(client, alice, doc["id"]).json()["version_number"] == 2  # no gap
    assert_store_matches_db(db, doc["id"])


def _raise_db_error_class(*args, **kwargs):
    raise_db_error()


@pytest.mark.parametrize("step", ["_next_version_number", "ProcessingJob"])
def test_finalize_failure_discards_stored_version(client, alice, doc, db, monkeypatch, step):
    """A failure early (number allocation) or late (job insert) in the finalize rolls it all back."""
    monkeypatch.setattr(version_service, step, _raise_db_error_class)
    assert error(new_version(client, alice, doc["id"])) == (503, "DB_UNAVAILABLE")
    assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE")]
    assert current_number(db, doc["id"]) == 1
    assert len(jobs(db, doc["id"])) == 1
    assert_store_matches_db(db, doc["id"])  # the stored copy was removed


def test_finalize_and_cleanup_failure_keeps_app_state_consistent(app, client, alice, doc, db, monkeypatch):
    """If even the cleanup fails, the app stays on v1; the stray object is reconcile's job (T19)."""
    monkeypatch.setattr(version_service, "_finalize", raise_db_error)
    app.dependency_overrides[get_storage] = lambda: StorageWrapper(delete_version=raise_storage_error)
    assert error(new_version(client, alice, doc["id"])) == (503, "DB_UNAVAILABLE")
    assert current_number(db, doc["id"]) == 1
    assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE")]
    assert len(store_ids(db, doc["id"])) == 2  # one unreferenced stored version left for reconcile


# ---- failures: restore ----

def test_restore_copy_failure(app, client, alice, doc, db):
    app.dependency_overrides[get_storage] = lambda: StorageWrapper(copy_object=raise_storage_error)
    assert error(restore(client, alice, doc["id"], 1)) == (502, "STORAGE_ERROR")
    assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE")]
    assert_store_matches_db(db, doc["id"])


def test_restore_finalize_failure_discards_copy(client, alice, doc, db, monkeypatch):
    monkeypatch.setattr(version_service, "ProcessingJob", _raise_db_error_class)
    assert error(restore(client, alice, doc["id"], 1)) == (503, "DB_UNAVAILABLE")
    assert [(v[0], v[1]) for v in db_versions(db, doc["id"])] == [(1, "ACTIVE")]
    assert len(jobs(db, doc["id"])) == 1
    assert_store_matches_db(db, doc["id"])


# ---- integration with T10 ----

def test_versions_survive_delete_and_undelete(client, alice, doc, db):
    new_version(client, alice, doc["id"])
    restore(client, alice, doc["id"], 1)
    before = db_versions(db, doc["id"])
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    assert client.post(f"/api/documents/{doc['id']}/undelete", headers=alice).status_code == 200
    assert db_versions(db, doc["id"]) == before
    assert_store_matches_db(db, doc["id"])


def test_interrupted_delete_is_recovered_before_new_version(client, alice, doc, db, monkeypatch):
    """A leftover DELETE intent (store has the marker) is finished first, so the upload is refused."""
    from app.services import deletion_service

    def boom(*args, **kwargs):
        raise OperationalError("COMMIT", {}, Exception("x"))

    monkeypatch.setattr(deletion_service, "_finish_soft_delete", boom)
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    monkeypatch.undo()
    assert error(new_version(client, alice, doc["id"])) == (409, "DOCUMENT_DELETED")
    d = fresh_doc(db, doc["id"])
    assert (d.status, d.pending_op) == ("DELETED", None)
    assert len(db_versions(db, doc["id"])) == 1


def test_permanent_delete_removes_all_versions(client, alice, doc, db):
    new_version(client, alice, doc["id"])
    restore(client, alice, doc["id"], 1)
    key = fresh_doc(db, doc["id"]).s3_key
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    assert client.delete(f"/api/documents/{doc['id']}/permanent", headers=alice,
                         params={"confirm": "true"}).status_code == 204
    assert db_versions(db, doc["id"]) == [] and get_storage().list_object_versions(key) == []
