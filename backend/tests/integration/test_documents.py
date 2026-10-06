"""T8: upload (W2) and list/detail (W7). Doc 10.2 I1-I3, A4, V8 at HTTP level (AM-1, AM-7)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Document, DocumentVersion, ProcessingJob
from app.services import document_service
from app.services.validation import MAX_UPLOAD_BYTES
from app.storage import get_storage
from app.storage.base import StorageError
from app.storage.postgres import PostgresObjectStorage
from tests.conftest import PDF_BYTES


def error(r):
    return r.status_code, r.json()["error"]["code"]


@pytest.fixture
def alice(auth_headers):
    return auth_headers("alice@example.com")


@pytest.fixture
def bob(auth_headers):
    return auth_headers("bob@example.com")


def store_versions(prefix="documents/"):
    return get_storage().list_object_versions(prefix)


# ---- I1: upload then list ----

def test_i1_upload_then_list(client, upload, alice, db):
    r = upload(alice, "report.pdf")
    assert r.status_code == 201
    doc = r.json()
    assert doc["display_name"] == "report.pdf" and doc["status"] == "ACTIVE"
    assert doc["current_version"] == {
        "version_number": 1, "size_bytes": len(PDF_BYTES), "content_type": "application/pdf",
        "storage_class": "STANDARD", "created_at": doc["current_version"]["created_at"],
        "origin": "UPLOAD", "state": "ACTIVE",
    }
    assert doc["version_count"] == 1
    assert doc["processing"] == {"status": "PENDING", "page_count": None, "word_count": None, "stalled": False}
    assert doc["deleted_at"] is None

    listed = client.get("/api/documents", headers=alice).json()
    assert listed["total"] == 1 and listed["page"] == 1 and listed["page_size"] == 25
    assert listed["items"][0] == doc
    assert client.get(f"/api/documents/{doc['id']}", headers=alice).json() == doc


def test_upload_stores_object_in_simulated_s3(client, upload, alice, db):
    doc = upload(alice, "report.pdf").json()
    row = db.get(Document, uuid.UUID(doc["id"]))
    version = db.get(DocumentVersion, row.current_version_id)
    owner_id = row.owner_id
    assert row.s3_key == f"documents/{owner_id}/{row.id}"  # filename never in the key
    head, data = get_storage().get_object(row.s3_key, version.s3_version_id)
    assert data == PDF_BYTES
    assert head.content_type == "application/pdf" and head.storage_class is None
    assert head.metadata == {"cv-doc-id": str(row.id), "cv-owner-id": str(owner_id)}
    assert get_storage().get_object_tagging(row.s3_key) == {"project": "cloudvault", "env": "test"}
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.version_id == version.id))
    assert (job.status, job.document_id, job.deliveries) == ("PENDING", row.id, 0)


def test_client_content_type_and_path_are_ignored(client, alice):
    files = {"file": ("../../etc/notes.txt", b"plain text", "image/png")}
    doc = client.post("/api/documents", headers=alice, files=files).json()
    assert doc["display_name"] == "notes.txt"
    assert doc["current_version"]["content_type"] == "text/plain"


# ---- I2 / I3: duplicates and name clashes ----

def test_i2_same_name_same_content_is_duplicate(client, upload, alice):
    first = upload(alice, "report.pdf").json()
    r = upload(alice, "REPORT.pdf")  # names compare case-insensitively
    assert r.status_code == 200
    assert r.json() == {"duplicate": True, "document": first}
    assert len(store_versions()) == 1
    assert client.get("/api/documents", headers=alice).json()["total"] == 1


def test_i3_same_name_new_content_is_name_exists(client, upload, alice):
    first = upload(alice, "report.pdf").json()
    r = upload(alice, "report.pdf", PDF_BYTES + b"changed")
    assert error(r) == (409, "NAME_EXISTS")
    assert r.json()["error"]["details"] == {"existing_document_id": first["id"]}
    assert len(store_versions()) == 1


def test_same_name_for_different_owners_is_independent(upload, alice, bob):
    assert upload(alice, "report.pdf").status_code == 201
    assert upload(bob, "report.pdf").status_code == 201


def test_unique_index_race_path_still_returns_name_exists(upload, alice, monkeypatch):
    """If the pre-check misses a concurrent create, the partial unique index answers 409."""
    first = upload(alice, "report.pdf").json()
    monkeypatch.setattr(document_service, "_live_document_by_name", _miss_first_lookup())
    r = upload(alice, "report.pdf", PDF_BYTES + b"other")
    assert error(r) == (409, "NAME_EXISTS")
    assert r.json()["error"]["details"] == {"existing_document_id": first["id"]}
    assert len(store_versions()) == 1


def _miss_first_lookup():
    real = document_service._live_document_by_name
    calls = {"n": 0}

    def lookup(db, owner_id, name):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db, owner_id, name)

    return lookup


# ---- validation at the HTTP level (doc 05.3, V8) ----

def test_v8_size_boundary_over_http(upload, alice):
    assert upload(alice, "exact.txt", b"a" * MAX_UPLOAD_BYTES).status_code == 201
    assert error(upload(alice, "over.txt", b"a" * (MAX_UPLOAD_BYTES + 1))) == (413, "FILE_TOO_LARGE")
    assert [v.size_bytes for v in store_versions()] == [MAX_UPLOAD_BYTES]


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("empty.pdf", b"", (400, "EMPTY_FILE")),
        ("x.exe", b"MZ", (415, "UNSUPPORTED_TYPE")),
        ("fake.pdf", b"not a pdf", (415, "UNSUPPORTED_TYPE")),
        ("..", PDF_BYTES, (422, "INVALID_FILENAME")),
    ],
)
def test_validation_failures_store_nothing(upload, alice, db, name, data, expected):
    assert error(upload(alice, name, data)) == expected
    assert db.query(Document).count() == 0 and store_versions() == []


def test_upload_requires_auth_and_multipart(client, upload):
    assert error(upload({})) == (401, "UNAUTHORIZED")


def test_upload_without_file_field(client, alice):
    r = client.post("/api/documents", headers=alice, data={"other": "x"})
    assert error(r) == (422, "VALIDATION_ERROR")


# ---- A4: storage failures leave nothing visible ----

class FailingPutStorage:
    """Delegates to the real simulated store but fails `put_object`."""

    def __init__(self, exc):
        self._inner, self._exc = get_storage(), exc

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def put_object(self, *args, **kwargs):
        raise self._exc


def _failed_rows(db):
    docs = db.scalars(select(Document)).all()
    versions = db.scalars(select(DocumentVersion)).all()
    return [d.status for d in docs], [v.state for v in versions], db.query(ProcessingJob).count()


def test_a4_storage_error_marks_document_failed(app, client, upload, alice, db):
    app.dependency_overrides[get_storage] = lambda: FailingPutStorage(StorageError("injected"))
    r = upload(alice, "report.pdf")
    assert error(r) == (502, "STORAGE_ERROR")
    assert _failed_rows(db) == (["FAILED"], [], 0)  # no version row without a stored version (AM-9)
    assert client.get("/api/documents", headers=alice).json()["total"] == 0
    failed_id = db.scalar(select(Document.id))
    assert error(client.get(f"/api/documents/{failed_id}", headers=alice)) == (404, "NOT_FOUND")
    assert store_versions() == []

    # The name is free again once the store recovers.
    app.dependency_overrides.pop(get_storage)
    assert upload(alice, "report.pdf").status_code == 201


def test_storage_limit_returns_507_and_marks_failed(app, upload, alice, db):
    tiny = PostgresObjectStorage(SessionLocal, "cloudvault-sim", limit_bytes=len(PDF_BYTES) - 1)
    app.dependency_overrides[get_storage] = lambda: tiny
    assert error(upload(alice, "report.pdf")) == (507, "STORAGE_LIMIT_EXCEEDED")
    assert _failed_rows(db) == (["FAILED"], [], 0)  # no version row without a stored version (AM-9)


def test_finalize_failure_discards_stored_version(app, upload, alice, db, monkeypatch):
    def broken_finalize(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(document_service, "_finalize", broken_finalize)
    r = upload(alice, "report.pdf", test_client=TestClient(app, raise_server_exceptions=False))
    assert error(r) == (500, "INTERNAL_ERROR")
    assert _failed_rows(db) == (["FAILED"], [], 0)  # no version row without a stored version (AM-9)
    assert store_versions() == []  # compensating delete of the exact stored version


# ---- list: search, filters, sort, pagination ----

def _seed(upload, headers):
    names = {
        "alpha.pdf": PDF_BYTES,
        "Beta_notes.txt": b"b" * 50,
        "gamma.csv": b"a,b\n" * 10,
        "100%_done.md": b"# done",
    }
    return {name: upload(headers, name, data).json() for name, data in names.items()}


def _names(client, headers, **params):
    body = client.get("/api/documents", headers=headers, params=params).json()
    return [d["display_name"] for d in body["items"]]


def test_list_sort_options(client, upload, alice):
    _seed(upload, alice)
    assert _names(client, alice, sort="name") == ["100%_done.md", "alpha.pdf", "Beta_notes.txt", "gamma.csv"]
    assert _names(client, alice, sort="-name") == ["gamma.csv", "Beta_notes.txt", "alpha.pdf", "100%_done.md"]
    assert _names(client, alice, sort="size") == ["100%_done.md", "alpha.pdf", "gamma.csv", "Beta_notes.txt"]
    assert _names(client, alice)[0] == "100%_done.md"  # default -updated: newest first
    assert _names(client, alice, sort="updated")[0] == "alpha.pdf"


def test_list_search_escapes_like_wildcards(client, upload, alice):
    _seed(upload, alice)
    assert _names(client, alice, q="%") == ["100%_done.md"]
    assert _names(client, alice, q="t_t") == []  # "_" is literal; as a wildcard it would match "txt"
    assert _names(client, alice, q="_notes") == ["Beta_notes.txt"]
    assert _names(client, alice, q="BETA") == ["Beta_notes.txt"]


def test_list_search_matches_processing_excerpt(client, upload, alice, db):
    docs = _seed(upload, alice)
    db.execute(
        text("UPDATE processing_jobs SET status='SUCCEEDED', finished_at=now(), text_excerpt='quarterly budget' "
             "WHERE document_id = :d"),
        {"d": docs["alpha.pdf"]["id"]},
    )
    db.commit()
    assert _names(client, alice, q="Budget") == ["alpha.pdf"]


def test_list_type_and_class_filters(client, upload, alice):
    _seed(upload, alice)
    assert _names(client, alice, type="csv") == ["gamma.csv"]
    assert _names(client, alice, type="docx") == []
    assert len(_names(client, alice, storage_class="STANDARD")) == 4
    assert _names(client, alice, storage_class="GLACIER_IR") == []


def test_list_pagination(client, upload, alice):
    _seed(upload, alice)
    first = client.get("/api/documents", headers=alice, params={"sort": "name", "page_size": 3}).json()
    second = client.get("/api/documents", headers=alice, params={"sort": "name", "page_size": 3, "page": 2}).json()
    assert (first["total"], len(first["items"]), second["total"], len(second["items"])) == (4, 3, 4, 1)
    assert second["items"][0]["display_name"] == "gamma.csv"


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 101}, {"page_size": 0}, {"sort": "owner"}, {"status": "pending"},
     {"type": "exe"}, {"storage_class": "DEEP_ARCHIVE"}, {"q": "x" * 201}],
)
def test_list_rejects_bad_parameters(client, alice, params):
    assert error(client.get("/api/documents", headers=alice, params=params)) == (422, "VALIDATION_ERROR")


def test_list_and_detail_only_show_active_and_deleted(client, upload, alice, db):
    docs = _seed(upload, alice)
    db.execute(text("UPDATE documents SET status='FAILED', current_version_id=NULL WHERE id=:d"),
               {"d": docs["gamma.csv"]["id"]})
    trashed = docs["alpha.pdf"]["id"]
    db.execute(text("UPDATE documents SET status='DELETED', deleted_at=now(), delete_marker_version_id='m' "
                    "WHERE id=:d"), {"d": trashed})
    db.commit()
    assert sorted(_names(client, alice)) == ["100%_done.md", "Beta_notes.txt"]
    assert _names(client, alice, status="deleted") == ["alpha.pdf"]
    assert client.get(f"/api/documents/{trashed}", headers=alice).json()["status"] == "DELETED"
    assert error(client.get(f"/api/documents/{docs['gamma.csv']['id']}", headers=alice)) == (404, "NOT_FOUND")


def test_owner_scoping(client, upload, alice, bob):
    doc = upload(alice, "report.pdf").json()
    assert client.get("/api/documents", headers=bob).json()["total"] == 0
    assert error(client.get(f"/api/documents/{doc['id']}", headers=bob)) == (404, "NOT_FOUND")


def test_detail_rejects_non_uuid_and_unknown_ids(client, alice):
    assert error(client.get("/api/documents/not-a-uuid", headers=alice)) == (422, "VALIDATION_ERROR")
    assert error(client.get(f"/api/documents/{uuid.uuid4()}", headers=alice)) == (404, "NOT_FOUND")


def test_stalled_after_ten_minutes(client, upload, alice, db):
    doc = upload(alice, "report.pdf").json()

    def set_age(minutes):
        db.execute(text("UPDATE processing_jobs SET created_at = :t WHERE document_id = :d"),
                   {"t": datetime.now(UTC) - timedelta(minutes=minutes), "d": doc["id"]})
        db.commit()
        return client.get(f"/api/documents/{doc['id']}", headers=alice).json()["processing"]["stalled"]

    assert set_age(9) is False
    assert set_age(11) is True


# ---- rate limit (doc 09.1: upload 20/min/user) ----

def test_upload_rate_limit_is_per_user(upload, alice, bob):
    codes = [upload(alice, f"file{i}.txt", f"content {i}".encode()).status_code for i in range(20)]
    assert codes == [201] * 20
    assert error(upload(alice, "file20.txt", b"one too many")) == (429, "RATE_LIMITED")
    assert upload(bob, "bob.txt", b"bob is not limited").status_code == 201
