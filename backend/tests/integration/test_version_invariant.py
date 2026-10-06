"""AM-9: every document_versions row has the simulated store's version id.

A version row is inserted only after the store write succeeded, in the same transaction
that makes it current and adds its PENDING job. These tests check the schema, look at the
database from inside every store write that creates a version (upload, new version,
restore, Apply), and follow a restore through the processing worker.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Document, DocumentVersion, ProcessingJob
from app.processing.worker import ProcessingWorker
from app.storage import get_storage
from tests.conftest import PDF_BYTES


@pytest.fixture
def alice(auth_headers):
    return auth_headers("alice@example.com")


def db_snapshot():
    """Version rows as (document_id, number, store id), read on a separate connection."""
    with SessionLocal() as s:
        return [tuple(r) for r in s.execute(select(
            DocumentVersion.document_id, DocumentVersion.version_number, DocumentVersion.s3_version_id
        ).order_by(DocumentVersion.document_id, DocumentVersion.version_number))]


class Observer:
    """Delegates to the real store; records the database state seen inside each write."""

    def __init__(self):
        self._inner = get_storage()
        self.seen = {}

    def put_object(self, *args, **kwargs):
        self.seen.setdefault("put_object", []).append(db_snapshot())
        return self._inner.put_object(*args, **kwargs)

    def copy_object(self, *args, **kwargs):
        self.seen.setdefault("copy_object", []).append(db_snapshot())
        return self._inner.copy_object(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_schema_column_is_not_null(db):
    nullable = db.scalar(text(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'document_versions' AND column_name = 's3_version_id'"
    ))
    assert nullable == "NO"
    states = db.scalar(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_versions_state'"
    ))
    assert "ACTIVE" in states and "S3_MISSING" in states and "PENDING" not in states and "FAILED" not in states


def test_no_version_row_exists_during_any_store_write(app, client, alice, db):
    observer = Observer()
    app.dependency_overrides[get_storage] = lambda: observer

    doc = client.post("/api/documents", headers=alice,
                      files={"file": ("a.pdf", PDF_BYTES, "application/octet-stream")}).json()
    assert observer.seen["put_object"][0] == []  # the PENDING document exists, no version row yet
    doc_id = uuid.UUID(doc["id"])

    r = client.post(f"/api/documents/{doc_id}/versions", headers=alice,
                    files={"file": ("a.pdf", PDF_BYTES + b"v2", "application/octet-stream")})
    assert r.status_code == 201
    assert [n for d, n, _ in observer.seen["put_object"][1] if d == doc_id] == [1]

    r = client.post(f"/api/documents/{doc_id}/versions/1/restore", headers=alice)
    assert r.status_code == 201
    assert [n for d, n, _ in observer.seen["copy_object"][0] if d == doc_id] == [1, 2]

    after = db_snapshot()
    assert [n for d, n, _ in after if d == doc_id] == [1, 2, 3]
    stored = {e.version_id for e in get_storage().list_object_versions("documents/")}
    assert all(sid is not None and sid in stored for _, _, sid in after)


def test_apply_keeps_the_row_and_swaps_its_store_id(client, alice, db):
    doc = client.post("/api/documents", headers=alice,
                      files={"file": ("a.pdf", PDF_BYTES, "application/octet-stream")}).json()
    d = db.get(Document, uuid.UUID(doc["id"]))
    v = db.get(DocumentVersion, d.current_version_id)
    old_store_id = v.s3_version_id
    # Make the version qualify for R2 (old, never accessed) and big enough for the engine.
    long_ago = datetime.now(UTC) - timedelta(days=200)
    db.execute(text("UPDATE document_versions SET created_at=:t, storage_class_changed_at=:t, size_bytes=200000 "
                    "WHERE id=:v"), {"t": long_ago, "v": v.id})
    db.commit()
    recs = client.post("/api/recommendations/refresh", headers=alice).json()["items"]
    assert len(recs) == 1
    assert client.post(f"/api/recommendations/{recs[0]['id']}/apply", headers=alice).status_code == 200

    db.rollback()
    rows = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d.id)
                      .execution_options(populate_existing=True)).all()
    assert len(rows) == 1 and rows[0].id == v.id and rows[0].version_number == 1
    assert rows[0].s3_version_id not in (None, old_store_id)
    assert [e.version_id for e in get_storage().list_object_versions(d.s3_key)] == [rows[0].s3_version_id]


def test_restore_gets_a_new_pending_job_that_the_worker_processes(client, alice, db):
    """AM-2: the restored version's own job starts PENDING; the source job is never copied or touched."""
    doc = client.post("/api/documents", headers=alice,
                      files={"file": ("notes.txt", b"alpha beta gamma", "application/octet-stream")}).json()
    worker = ProcessingWorker(SessionLocal, get_storage())
    assert worker.run_once().result == "SUCCEEDED"  # v1
    client.post(f"/api/documents/{doc['id']}/versions", headers=alice,
                files={"file": ("notes.txt", b"delta", "application/octet-stream")})
    assert worker.run_once().result == "SUCCEEDED"  # v2

    def jobs():
        db.rollback()
        return {
            n: (j.id, j.status, j.word_count, j.finished_at)
            for n, j in db.execute(
                select(DocumentVersion.version_number, ProcessingJob)
                .join(ProcessingJob, ProcessingJob.version_id == DocumentVersion.id)
                .where(DocumentVersion.document_id == uuid.UUID(doc["id"]))
            ).all()
        }

    before = jobs()
    r = client.post(f"/api/documents/{doc['id']}/versions/1/restore", headers=alice)
    assert r.status_code == 201 and r.json()["version_number"] == 3
    restored = jobs()
    assert restored[3][1:] == ("PENDING", None, None)  # nothing inherited from v1
    assert restored[1] == before[1] and restored[2] == before[2]  # history untouched

    assert worker.run_once().result == "SUCCEEDED"
    done = jobs()
    assert done[3][0] == restored[3][0]  # same job row, now finished
    assert done[3][1:3] == ("SUCCEEDED", 3)
