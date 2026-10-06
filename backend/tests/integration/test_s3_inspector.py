"""T12: S3 Inspector, GET /api/documents/{id}/s3-info (doc 05.4, W8; AM-7)."""

import hashlib
import uuid

import pytest
from sqlalchemy import select, text

from app.models import Document, DocumentVersion
from app.storage import get_storage
from tests.conftest import PDF_BYTES

V2 = PDF_BYTES + b"% two\n"


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


def info(client, headers, doc_id, **params):
    return client.get(f"/api/documents/{doc_id}/s3-info", headers=headers, params=params)


def doc_row(db, doc_id) -> Document:
    db.rollback()
    return db.get(Document, uuid.UUID(doc_id), populate_existing=True)


def version_row(db, doc_id, n) -> DocumentVersion:
    db.rollback()
    return db.scalar(select(DocumentVersion).where(
        DocumentVersion.document_id == uuid.UUID(doc_id), DocumentVersion.version_number == n))


def add_class_version(db, doc_id, n, storage_class):
    """A version in a non-STANDARD class, created the way Apply will (simulated copy with a class)."""
    d = doc_row(db, doc_id)
    source = version_row(db, doc_id, 1)
    copied = get_storage().copy_object(d.s3_key, source.s3_version_id, storage_class=storage_class)
    db.add(DocumentVersion(document_id=d.id, version_number=n, s3_version_id=copied.version_id,
                           size_bytes=source.size_bytes, content_type=source.content_type,
                           sha256=source.sha256, storage_class=storage_class, state="ACTIVE"))
    db.commit()
    return copied.version_id


class NoDataReads:
    """Real store, but reading object bytes fails the test."""

    def __init__(self):
        self._inner = get_storage()

    def __getattr__(self, name):
        if name in ("get_object", "copy_object"):
            raise AssertionError(f"inspector called storage.{name}")
        return getattr(self._inner, name)


# ---- shape and fields ----

def test_current_version_full_shape(client, alice, doc, db):
    r = info(client, alice, doc["id"])
    assert r.status_code == 200
    body = r.json()
    d, v = doc_row(db, doc["id"]), version_row(db, doc["id"], 1)
    assert body == {
        "bucket": "cloudvault-sim",
        "key": f"documents/{d.owner_id}/{d.id}",
        "version_id": v.s3_version_id,
        "etag": f'"{hashlib.md5(PDF_BYTES).hexdigest()}"',
        "content_length": len(PDF_BYTES),
        "content_type": "application/pdf",
        "last_modified": body["last_modified"],
        "storage_class": "STANDARD",
        "metadata": {"cv-doc-id": str(d.id), "cv-owner-id": str(d.owner_id)},
        "tags": {"project": "cloudvault", "env": "test"},
        "source": "simulated-s3",
    }
    assert body["last_modified"].endswith(("Z", "+00:00"))


def test_standard_class_is_shown_although_head_omits_it(client, alice, doc, db):
    d, v = doc_row(db, doc["id"]), version_row(db, doc["id"], 1)
    assert get_storage().head_object(d.s3_key, v.s3_version_id).storage_class is None
    assert info(client, alice, doc["id"]).json()["storage_class"] == "STANDARD"


@pytest.mark.parametrize("storage_class", ["STANDARD_IA", "GLACIER_IR"])
def test_non_standard_classes(client, alice, doc, db, storage_class):
    store_id = add_class_version(db, doc["id"], 2, storage_class)
    body = info(client, alice, doc["id"], version=2).json()
    assert (body["storage_class"], body["version_id"]) == (storage_class, store_id)
    assert info(client, alice, doc["id"], version=1).json()["storage_class"] == "STANDARD"


def test_explicit_historical_version(client, alice, doc, db):
    files = {"file": ("report.pdf", V2, "application/octet-stream")}
    client.post(f"/api/documents/{doc['id']}/versions", headers=alice, files=files)
    v1, v2 = version_row(db, doc["id"], 1), version_row(db, doc["id"], 2)
    old = info(client, alice, doc["id"], version=1).json()
    current = info(client, alice, doc["id"]).json()
    assert (old["version_id"], old["content_length"]) == (v1.s3_version_id, len(PDF_BYTES))
    assert (current["version_id"], current["content_length"]) == (v2.s3_version_id, len(V2))
    assert old["etag"] == f'"{hashlib.md5(PDF_BYTES).hexdigest()}"' != current["etag"]


def test_response_has_exactly_the_doc_05_4_fields(client, alice, doc):
    assert set(info(client, alice, doc["id"]).json()) == {
        "bucket", "key", "version_id", "etag", "content_length", "content_type", "last_modified",
        "storage_class", "metadata", "tags", "source",
    }


def test_restored_version_metadata_and_tags_are_copied(client, alice, doc):
    client.post(f"/api/documents/{doc['id']}/versions/1/restore", headers=alice)
    v1, v2 = info(client, alice, doc["id"], version=1).json(), info(client, alice, doc["id"], version=2).json()
    assert v2["metadata"] == v1["metadata"] and v2["tags"] == v1["tags"]
    assert v2["etag"] == v1["etag"] and v2["version_id"] != v1["version_id"]


def test_trashed_document_can_be_inspected(client, alice, doc):
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    r = info(client, alice, doc["id"])
    assert r.status_code == 200 and r.json()["source"] == "simulated-s3"


def test_empty_metadata_is_returned_as_is(client, alice, doc, db):
    """Doc 09.2: missing metadata is shown as such; the DB stays authoritative."""
    v = version_row(db, doc["id"], 1)
    db.execute(text("UPDATE sim_object_versions SET metadata='{}'::jsonb WHERE version_id=:v"),
               {"v": v.s3_version_id})
    db.commit()
    assert info(client, alice, doc["id"]).json()["metadata"] == {}


def test_inspector_never_reads_object_bytes(app, client, alice, doc):
    app.dependency_overrides[get_storage] = lambda: NoDataReads()
    assert info(client, alice, doc["id"]).status_code == 200
    assert info(client, alice, doc["id"], version=1).status_code == 200


# ---- errors ----

def test_nonexistent_version_is_404(client, alice, doc):
    assert error(info(client, alice, doc["id"], version=5)) == (404, "VERSION_NOT_FOUND")
    assert error(info(client, alice, doc["id"], version=0)) == (422, "VALIDATION_ERROR")


@pytest.mark.parametrize("status", ["PENDING", "FAILED"])
def test_unfinished_documents_are_404(client, alice, doc, db, status):
    """AM-9: an unfinished upload is a PENDING/FAILED document with no version row; it is 404."""
    d = doc_row(db, doc["id"])
    unfinished = Document(owner_id=d.owner_id, display_name=f"{status}.pdf", s3_key=f"documents/x/{status}",
                          status=status)
    db.add(unfinished)
    db.commit()
    assert error(info(client, alice, str(unfinished.id))) == (404, "NOT_FOUND")


def test_version_already_s3_missing_is_410_without_store_call(app, client, alice, doc, db):
    db.execute(text("UPDATE document_versions SET state='S3_MISSING' WHERE document_id=:d"), {"d": doc["id"]})
    db.commit()

    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError(f"storage.{name} called for an S3_MISSING version")

    app.dependency_overrides[get_storage] = lambda: NoCalls()
    assert error(info(client, alice, doc["id"])) == (410, "VERSION_EXPIRED")


def test_version_missing_from_store_is_marked_and_410(client, alice, doc, db):
    d, v = doc_row(db, doc["id"]), version_row(db, doc["id"], 1)
    get_storage().delete_version(d.s3_key, v.s3_version_id)  # e.g. expired by lifecycle
    assert error(info(client, alice, doc["id"])) == (410, "VERSION_EXPIRED")
    assert version_row(db, doc["id"], 1).state == "S3_MISSING"
    assert get_storage().list_object_versions(d.s3_key) == []  # nothing recreated


def test_owner_scoping(client, alice, bob, doc):
    assert error(info(client, bob, doc["id"])) == (404, "NOT_FOUND")
    assert error(info(client, alice, str(uuid.uuid4()))) == (404, "NOT_FOUND")
    assert error(client.get(f"/api/documents/{doc['id']}/s3-info")) == (401, "UNAUTHORIZED")
    assert error(client.get("/api/documents/not-a-uuid/s3-info", headers=alice)) == (422, "VALIDATION_ERROR")
