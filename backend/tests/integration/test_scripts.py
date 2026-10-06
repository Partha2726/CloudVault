"""T19: reconcile, lifecycle and seed_demo scripts (doc 09.3, 02.2, 07.7; AM-1, AM-4, AM-7)."""

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Document, DocumentVersion, User
from app.scripts import lifecycle, reconcile, seed_demo
from app.services import recommendation_service
from app.storage import build_key, get_storage
from app.storage.postgres import PostgresObjectStorage
from tests.conftest import PDF_BYTES

LATER = timedelta(hours=2)


def now():
    return datetime.now(UTC)


def run(fix=False, at=None):
    return reconcile.reconcile(SessionLocal, get_storage(), fix=fix, now=at or now() + LATER)


def doc_row(db, doc_id):
    db.rollback()
    return db.get(Document, uuid.UUID(str(doc_id)), populate_existing=True)


def crashed_upload(db, owner_id, name, data, *, stored: bool):
    """The state an upload leaves when the process dies after transaction 1 (and optionally after the PUT).

    AM-9: transaction 1 writes only the PENDING document; no version row exists yet.
    """
    doc_id = uuid.uuid4()
    key = build_key(owner_id, doc_id)
    sha = hashlib.sha256(data).hexdigest()
    db.add(Document(id=doc_id, owner_id=owner_id, display_name=name, s3_key=key, status="PENDING"))
    db.commit()
    if stored:
        get_storage().put_object(key, data, content_type="application/pdf",
                                 metadata={"cv-doc-id": str(doc_id), "cv-owner-id": str(owner_id)},
                                 checksum_sha256=base64.b64encode(bytes.fromhex(sha)).decode())
    return doc_id


def owner_id(db, email="alice@example.com"):
    db.rollback()
    return db.scalar(select(User.id).where(User.email == email))


# ---- reconcile: clean state ----

def test_clean_state_reports_nothing(client, upload, alice):
    upload(alice, "a.pdf")
    report = run(fix=True)
    assert report.clean, report.lines()


# ---- reconcile: stale PENDING uploads (the T8 crash window) ----

def test_t8_crash_without_stored_object_frees_the_name(client, upload, alice, db):
    stuck = crashed_upload(db, owner_id(db), "report.pdf", PDF_BYTES, stored=False)
    r = upload(alice, "report.pdf", PDF_BYTES + b"new")
    assert r.status_code == 409  # the PENDING document still reserves the name

    report = run(fix=True)
    assert len(report.failed_uploads) == 1
    d = doc_row(db, stuck)
    assert d.status == "FAILED"
    assert db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == stuck)) is None
    assert upload(alice, "report.pdf", PDF_BYTES + b"new").status_code == 201  # same-name upload now succeeds


def test_t8_crash_after_put_is_failed_and_orphan_removed(client, upload, alice, db):
    """AM-9: the stored object of an unfinished upload is never adopted; it is an orphan (doc 09.3)."""
    stuck = crashed_upload(db, owner_id(db), "report.pdf", PDF_BYTES, stored=True)
    key = doc_row(db, stuck).s3_key
    report = run(fix=True)
    assert len(report.failed_uploads) == 1 and len(report.deleted_unreferenced) == 1
    assert doc_row(db, stuck).status == "FAILED"
    assert db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == stuck)) is None
    assert get_storage().list_object_versions(key) == []
    assert client.get("/api/documents", headers=alice).json()["total"] == 0
    assert run(fix=True).clean


def test_young_pending_upload_is_left_alone(client, alice, db):
    stuck = crashed_upload(db, owner_id(db), "report.pdf", PDF_BYTES, stored=False)
    report = reconcile.reconcile(SessionLocal, get_storage(), fix=True, now=now() + timedelta(minutes=30))
    assert report.failed_uploads == [] and doc_row(db, stuck).status == "PENDING"


def test_crashed_new_version_is_discarded(client, upload, alice, db):
    """A new-version store write without its finalize leaves no row; reconcile removes the orphan."""
    d = upload(alice, "a.pdf").json()
    doc = doc_row(db, d["id"])
    v1_store_id = db.get(DocumentVersion, doc.current_version_id).s3_version_id
    v2_bytes = PDF_BYTES + b"v2"
    get_storage().put_object(doc.s3_key, v2_bytes, content_type="application/pdf",
                             metadata={"cv-doc-id": d["id"]},
                             checksum_sha256=base64.b64encode(hashlib.sha256(v2_bytes).digest()).decode())
    report = run(fix=True)
    assert len(report.deleted_unreferenced) == 1
    doc = doc_row(db, d["id"])
    assert db.get(DocumentVersion, doc.current_version_id).version_number == 1
    assert client.get(f"/api/documents/{d['id']}", headers=alice).json()["version_count"] == 1
    assert [e.version_id for e in get_storage().list_object_versions(doc.s3_key)] == [v1_store_id]


def test_report_only_changes_nothing(client, alice, db):
    stuck = crashed_upload(db, owner_id(db), "report.pdf", PDF_BYTES, stored=False)
    report = run(fix=False)
    assert report.failed_uploads and doc_row(db, stuck).status == "PENDING"


# ---- reconcile: stale pending_op ----

def test_stale_delete_intent_is_recovered(client, upload, alice, db):
    d = upload(alice, "a.pdf").json()
    doc = doc_row(db, d["id"])
    get_storage().delete_object(doc.s3_key)  # the store got the marker, the DB never did
    doc.pending_op, doc.pending_op_at = "DELETE", now()
    db.commit()
    report = run(fix=True)
    assert len(report.recovered_ops) == 1
    doc = doc_row(db, d["id"])
    assert (doc.status, doc.pending_op) == ("DELETED", None)


# ---- reconcile: unreferenced, missing, hidden ----

def test_unreferenced_versions_reported_and_old_ones_deleted(client, upload, alice, db):
    d = upload(alice, "a.pdf").json()
    key = doc_row(db, d["id"]).s3_key
    stray = get_storage().put_object(key, PDF_BYTES + b"stray", content_type="application/pdf").version_id
    young = run(fix=True, at=now() + timedelta(minutes=10))
    assert len(young.unreferenced) == 1 and young.deleted_unreferenced == []
    old = run(fix=True)
    assert len(old.deleted_unreferenced) == 1
    assert stray not in [e.version_id for e in get_storage().list_object_versions(key)]
    assert len(get_storage().list_object_versions(key)) == 1  # the referenced version stays


def test_active_version_missing_from_store_is_marked(client, upload, alice, db):
    d = upload(alice, "a.pdf").json()
    doc = doc_row(db, d["id"])
    v = db.get(DocumentVersion, doc.current_version_id)
    get_storage().delete_version(doc.s3_key, v.s3_version_id)
    report = run(fix=True)
    assert len(report.marked_missing) == 1
    db.rollback()
    assert db.get(DocumentVersion, v.id, populate_existing=True).state == "S3_MISSING"


def test_active_document_hidden_by_marker_is_reported_only(client, upload, alice, db):
    d = upload(alice, "a.pdf").json()
    doc = doc_row(db, d["id"])
    get_storage().delete_object(doc.s3_key)
    report = run(fix=True)
    assert len(report.marker_on_active) == 1
    assert doc_row(db, d["id"]).status == "ACTIVE"


def test_reconcile_cli(client, upload, alice, capsys):
    upload(alice, "a.pdf")
    assert reconcile.main([]) == 0
    assert "clean" in capsys.readouterr().out


# ---- lifecycle ----

KEY = "documents/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002"


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def timed(db):
    clock = Clock(now() - timedelta(days=400))
    return clock, PostgresObjectStorage(SessionLocal, "cloudvault-sim", 10**9, clock=clock)


def put(store, data):
    return store.put_object(KEY, data, content_type="text/plain").version_id


def test_noncurrent_version_expires_90_days_after_being_superseded(timed):
    clock, store = timed
    v1 = put(store, b"one")
    clock.t += timedelta(days=200)  # v1 superseded 200 days after creation
    v2 = put(store, b"two")
    superseded = clock.t
    assert lifecycle.apply_lifecycle(store, now=superseded + timedelta(days=89)).expired_versions == []
    report = lifecycle.apply_lifecycle(store, now=superseded + timedelta(days=90))
    assert len(report.expired_versions) == 1
    assert [e.version_id for e in store.list_object_versions(KEY)] == [v2]  # current never touched
    assert v1 not in [e.version_id for e in store.list_object_versions(KEY)]


def test_age_counts_from_supersession_not_creation(timed):
    clock, store = timed
    put(store, b"very old")
    clock.t += timedelta(days=380)  # created 380 days ago but superseded only 20 days ago
    put(store, b"new")
    assert lifecycle.apply_lifecycle(store, now=clock.t + timedelta(days=20)).expired_versions == []


def test_trashed_object_expires_then_its_marker_is_removed(timed):
    clock, store = timed
    put(store, b"data")
    clock.t += timedelta(days=10)
    store.delete_object(KEY)  # soft delete: v1 noncurrent from here
    report = lifecycle.apply_lifecycle(store, now=clock.t + timedelta(days=91))
    assert len(report.expired_versions) == 1 and len(report.removed_markers) == 1
    assert store.list_object_versions(KEY) == []


def test_dry_run_changes_nothing(timed):
    clock, store = timed
    put(store, b"one")
    clock.t += timedelta(days=1)
    put(store, b"two")
    report = lifecycle.apply_lifecycle(store, now=clock.t + timedelta(days=100), dry_run=True)
    assert len(report.expired_versions) == 1 and len(store.list_object_versions(KEY)) == 2


def test_lifecycle_expiry_surfaces_as_s3_missing_in_the_app(client, upload, alice, db):
    d = upload(alice, "a.pdf").json()
    files = {"file": ("a.pdf", PDF_BYTES + b"v2", "application/octet-stream")}
    client.post(f"/api/documents/{d['id']}/versions", headers=alice, files=files)
    lifecycle.apply_lifecycle(get_storage(), now=now() + timedelta(days=91))
    run(fix=True)  # reconcile marks the expired v1
    items = client.get(f"/api/documents/{d['id']}/versions", headers=alice).json()["items"]
    assert [(i["version_number"], i["state"]) for i in items] == [(2, "ACTIVE"), (1, "S3_MISSING")]
    r = client.get(f"/api/documents/{d['id']}/download", headers=alice, params={"version": 1})
    assert (r.status_code, r.json()["error"]["code"]) == (410, "VERSION_EXPIRED")


def test_lifecycle_cli(capsys, db):
    assert lifecycle.main(["--dry-run"]) == 0
    assert "dry run" in capsys.readouterr().out


# ---- seed_demo ----

def test_seed_produces_all_three_rules(db):
    result = seed_demo.seed(SessionLocal, get_storage(), email="seed@example.com", password="seed-password-1")
    user_id = owner_id(db, "seed@example.com")
    with SessionLocal() as s:
        recs = recommendation_service.refresh(s, user_id).items
    assert {r.rule_id for r in recs} == {"R1_PROMOTE", "R2_TO_GIR", "R3_TO_IA"}
    assert {r.display_name: r.recommended_class for r in recs} == {
        "Annual report 2023 (sample).pdf": "GLACIER_IR",
        "Meeting minutes Q1 (sample).txt": "STANDARD_IA",
        "Archive index (sample).csv": "STANDARD",
    }
    db.rollback()
    sizes = db.scalars(select(DocumentVersion.size_bytes)
                       .join(Document, Document.id == DocumentVersion.document_id)
                       .where(Document.owner_id == user_id)).all()
    assert all(128 * 1024 <= s <= 10 * 1024 * 1024 for s in sizes)  # AM-4
    assert len(result.documents) == 5


def test_seed_backdates_store_and_db_consistently(db):
    result = seed_demo.seed(SessionLocal, get_storage(), email="seed@example.com", password="seed-password-1")
    doc = doc_row(db, result.documents["Annual report 2023 (sample).pdf"])
    v = db.get(DocumentVersion, doc.current_version_id)
    stored = db.execute(text("SELECT last_modified FROM sim_object_versions WHERE version_id=:v"),
                        {"v": v.s3_version_id}).scalar_one()
    assert stored == v.created_at and (now() - v.created_at).days >= 149
    ia = doc_row(db, result.documents["Archive index (sample).csv"])
    head = get_storage().head_object(ia.s3_key)
    assert head.storage_class == "STANDARD_IA" and len(get_storage().list_object_versions(ia.s3_key)) == 1


def test_seed_refuses_to_duplicate_and_resets_on_request(db):
    seed_demo.seed(SessionLocal, get_storage(), email="seed@example.com", password="seed-password-1")
    with pytest.raises(SystemExit):
        seed_demo.seed(SessionLocal, get_storage(), email="seed@example.com", password="seed-password-1")
    again = seed_demo.seed(SessionLocal, get_storage(), email="seed@example.com", password="seed-password-1",
                           reset=True)
    db.rollback()
    assert db.query(Document).filter(Document.owner_id == owner_id(db, "seed@example.com")).count() == 5
    assert len(again.documents) == 5
    assert reconcile.reconcile(SessionLocal, get_storage(), fix=False, now=now() + LATER).unreferenced == []
