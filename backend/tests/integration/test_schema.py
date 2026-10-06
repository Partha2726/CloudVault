"""T3: schema shape and constraints (doc 04 + AM-1 in docs/15-amendments.md)."""

import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db import Base, engine
from app.models import AccessLog, Document, DocumentVersion, ProcessingJob, StorageRecommendation, User
from app.storage import models as _storage_models  # noqa: F401  (registers sim tables)
from tests.conftest import alembic_config

SHA = "a" * 64
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_user(db, email="u@example.com"):
    user = User(email=email, password_hash="x")
    db.add(user)
    db.flush()
    return user


def make_doc(db, owner, name="report.pdf", status="PENDING"):
    doc_id = uuid.uuid4()
    doc = Document(
        id=doc_id, owner_id=owner.id, display_name=name, status=status, s3_key=f"documents/{owner.id}/{doc_id}"
    )
    db.add(doc)
    db.flush()
    return doc


def make_version(db, doc, n=1, state="ACTIVE", s3_version_id="v-1", size_bytes=10, **kw):
    v = DocumentVersion(
        document_id=doc.id, version_number=n, s3_version_id=s3_version_id, size_bytes=size_bytes,
        content_type="application/pdf", sha256=kw.pop("sha256", SHA), state=state, **kw,
    )
    db.add(v)
    db.flush()
    return v


def make_active_doc(db, owner, name="report.pdf"):
    """Upload end state: PENDING document finalized to ACTIVE with its v1 as current version (AM-1, AM-9, W2)."""
    doc = make_doc(db, owner, name)
    v = make_version(db, doc)
    doc.status, doc.current_version_id = "ACTIVE", v.id
    db.flush()
    return doc, v


def make_rec(version, status="OPEN", **kw):
    fields = dict(
        version_id=version.id, current_class="STANDARD", recommended_class="STANDARD_IA",
        rule_id="R3_TO_IA", reason="r", signals={}, status=status,
        resolved_at=None if status == "OPEN" else NOW,
    )
    fields.update(kw)
    return StorageRecommendation(**fields)


def assert_violates(db, fn, constraint=None):
    with pytest.raises(IntegrityError) as exc:
        fn()
        db.flush()
    db.rollback()
    if constraint:
        assert constraint in str(exc.value)


# ---- shape ----

def test_six_application_tables_plus_simulated_store(migrated_db):
    names = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert names == {
        "users", "documents", "document_versions", "access_logs", "processing_jobs", "storage_recommendations",
        "sim_object_versions",  # simulated S3 (AM-7)
    }


def test_models_match_migration(migrated_db):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_downgrade_then_upgrade(migrated_db):
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    assert "documents" in inspect(engine).get_table_names()


# ---- users ----

def test_email_unique_case_insensitive(db):
    make_user(db, "A@x.com")
    assert_violates(db, lambda: make_user(db, "a@x.com"), "uq_users_email_lower")


# ---- documents ----

def test_duplicate_active_name_rejected_case_insensitive(db):
    u = make_user(db)
    make_active_doc(db, u, "Report.pdf")
    assert_violates(db, lambda: make_doc(db, u, "report.PDF"), "uq_documents_owner_name_live")


def test_pending_document_reserves_name(db):
    u = make_user(db)
    make_doc(db, u, "a.pdf")
    assert_violates(db, lambda: make_doc(db, u, "a.pdf"), "uq_documents_owner_name_live")


def test_failed_name_can_be_reused(db):
    u = make_user(db)
    make_doc(db, u, "a.pdf", status="FAILED")
    make_doc(db, u, "a.pdf")


def test_trashed_name_can_be_reused(db):
    u = make_user(db)
    doc, _ = make_active_doc(db, u, "a.pdf")
    doc.status, doc.deleted_at, doc.delete_marker_version_id = "DELETED", NOW, "marker-1"
    db.flush()
    make_doc(db, u, "a.pdf")


def test_same_name_different_owners_allowed(db):
    make_doc(db, make_user(db, "a@x.com"), "a.pdf")
    make_doc(db, make_user(db, "b@x.com"), "a.pdf")


def test_s3_key_unique(db):
    u = make_user(db)
    doc = make_doc(db, u, "a.pdf")
    assert_violates(
        db,
        lambda: db.add(Document(owner_id=u.id, display_name="b.pdf", s3_key=doc.s3_key)),
        "documents_s3_key_key",
    )


def test_bad_document_status_rejected(db):
    doc, _ = make_active_doc(db, make_user(db))
    doc.status = "GONE"
    assert_violates(db, lambda: None, "ck_documents_status")


def test_active_document_needs_current_version(db):
    u = make_user(db)
    assert_violates(db, lambda: make_doc(db, u, status="ACTIVE"), "ck_documents_current_version")


def test_deleted_document_needs_marker_and_timestamp(db):
    doc, _ = make_active_doc(db, make_user(db))
    doc.status, doc.deleted_at = "DELETED", NOW
    assert_violates(db, lambda: None, "ck_documents_deleted_fields")


def test_active_document_must_not_keep_marker(db):
    doc, _ = make_active_doc(db, make_user(db))
    doc.delete_marker_version_id = "marker-1"
    assert_violates(db, lambda: None, "ck_documents_deleted_fields")


def test_pending_op_needs_timestamp_and_known_value(db):
    doc, _ = make_active_doc(db, make_user(db))
    doc.pending_op = "DELETE"
    assert_violates(db, lambda: None, "ck_documents_pending_op_at")
    doc, _ = make_active_doc(db, make_user(db))
    doc.pending_op, doc.pending_op_at = "RENAME", NOW
    assert_violates(db, lambda: None, "ck_documents_pending_op")


def test_current_version_cannot_be_deleted_alone(db):
    _, v = make_active_doc(db, make_user(db))
    assert_violates(db, lambda: db.delete(v), "fk_documents_current_version")


# ---- document_versions ----

@pytest.mark.parametrize("state", ["ACTIVE", "S3_MISSING"])
def test_every_version_needs_s3_id(db, state):
    """AM-9: a version row is inserted only after the store write, so the column is NOT NULL."""
    doc = make_doc(db, make_user(db))
    assert_violates(db, lambda: make_version(db, doc, state=state, s3_version_id=None), "s3_version_id")


@pytest.mark.parametrize("state", ["PENDING", "FAILED"])
def test_withdrawn_version_states_are_rejected(db, state):
    doc = make_doc(db, make_user(db))
    assert_violates(db, lambda: make_version(db, doc, state=state), "ck_versions_state")


def test_version_number_unique_per_document(db):
    doc = make_doc(db, make_user(db))
    make_version(db, doc, 1, s3_version_id="x")
    assert_violates(db, lambda: make_version(db, doc, 1, s3_version_id="y"), "uq_versions_doc_number")


def test_s3_version_id_unique_per_document(db):
    doc = make_doc(db, make_user(db))
    make_version(db, doc, 1, s3_version_id="x")
    assert_violates(db, lambda: make_version(db, doc, 2, s3_version_id="x"), "uq_versions_doc_s3_version")


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("size_bytes", 0, "ck_versions_size_positive"),
        ("n", 0, "ck_versions_number_positive"),
        ("sha256", "A" * 64, "ck_versions_sha256_hex"),
        ("sha256", "a" * 63, "ck_versions_sha256_hex"),
        ("state", "GONE", "ck_versions_state"),
        ("origin", "COPY", "ck_versions_origin"),
    ],
)
def test_version_value_checks(db, field, value, constraint):
    doc = make_doc(db, make_user(db))
    assert_violates(db, lambda: make_version(db, doc, **{field: value}), constraint)


def test_restore_origin_requires_source_version(db):
    doc = make_doc(db, make_user(db))
    assert_violates(db, lambda: make_version(db, doc, 1, origin="RESTORE"), "ck_versions_restore_source")
    doc = make_doc(db, make_user(db))
    assert_violates(
        db, lambda: make_version(db, doc, 1, restored_from_version=1), "ck_versions_restore_source"
    )
    doc = make_doc(db, make_user(db))
    make_version(db, doc, 2, origin="RESTORE", restored_from_version=1)


def test_version_defaults(db):
    doc = make_doc(db, make_user(db))
    v = DocumentVersion(
        document_id=doc.id, version_number=1, s3_version_id="v-1", size_bytes=1, content_type="text/plain",
        sha256=SHA,
    )
    db.add(v)
    db.flush()
    db.refresh(v)
    assert (v.state, v.origin, v.storage_class) == ("ACTIVE", "UPLOAD", "STANDARD")
    assert v.storage_class_changed_at == v.created_at


# ---- access_logs ----

def test_access_log_defaults_and_event_check(db):
    u = make_user(db)
    doc, v = make_active_doc(db, u)
    log = AccessLog(document_id=doc.id, version_id=v.id, user_id=u.id)
    db.add(log)
    db.flush()
    db.refresh(log)
    assert log.event_type == "DOWNLOAD" and log.accessed_at is not None
    assert_violates(
        db,
        lambda: db.add(AccessLog(document_id=doc.id, version_id=v.id, user_id=u.id, event_type="VIEW")),
        "ck_access_logs_event_type",
    )


@pytest.mark.parametrize("missing", ["document_id", "version_id", "user_id"])
def test_access_log_fks_required(db, missing):
    u = make_user(db)
    doc, v = make_active_doc(db, u)
    fields = {"document_id": doc.id, "version_id": v.id, "user_id": u.id, missing: None}
    assert_violates(db, lambda: db.add(AccessLog(**fields)), "not-null")


# ---- processing_jobs ----

def test_one_job_per_version(db):
    doc, v = make_active_doc(db, make_user(db))
    db.add(ProcessingJob(version_id=v.id, document_id=doc.id))
    db.flush()
    assert_violates(
        db, lambda: db.add(ProcessingJob(version_id=v.id, document_id=doc.id)), "processing_jobs_version_id_key"
    )


def test_job_finished_at_matches_status(db):
    doc, v = make_active_doc(db, make_user(db))
    assert_violates(
        db, lambda: db.add(ProcessingJob(version_id=v.id, document_id=doc.id, status="SUCCEEDED")),
        "ck_jobs_finished_at",
    )
    doc, v = make_active_doc(db, make_user(db))
    assert_violates(
        db, lambda: db.add(ProcessingJob(version_id=v.id, document_id=doc.id, finished_at=NOW)),
        "ck_jobs_finished_at",
    )


def test_job_excerpt_capped(db):
    doc, v = make_active_doc(db, make_user(db))
    assert_violates(
        db,
        lambda: db.add(ProcessingJob(version_id=v.id, document_id=doc.id, status="SUCCEEDED",
                                     finished_at=NOW, text_excerpt="x" * 4001)),
        "ck_jobs_excerpt_len",
    )


# ---- storage_recommendations ----

def test_one_open_recommendation_per_version(db):
    _, v = make_active_doc(db, make_user(db))
    db.add_all([make_rec(v), make_rec(v, "STALE"), make_rec(v, "DISMISSED")])
    db.flush()
    assert_violates(db, lambda: db.add(make_rec(v)), "uq_recs_open_per_version")


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"recommended_class": "DEEP_ARCHIVE"}, "ck_recs_recommended_class"),
        ({"rule_id": "KEEP"}, "ck_recs_rule_id"),
        ({"recommended_class": "STANDARD"}, "ck_recs_class_changes"),
        ({"resolved_at": NOW}, "ck_recs_resolved_at"),
    ],
)
def test_recommendation_checks(db, fields, constraint):
    _, v = make_active_doc(db, make_user(db))
    assert_violates(db, lambda: db.add(make_rec(v, **fields)), constraint)


# ---- cascades ----

def test_permanent_delete_of_document_cascades(db):
    u = make_user(db)
    doc, v = make_active_doc(db, u)
    make_version(db, doc, 2, s3_version_id="v-2")
    db.add_all([
        ProcessingJob(version_id=v.id, document_id=doc.id),
        AccessLog(document_id=doc.id, version_id=v.id, user_id=u.id),
        make_rec(v, recommended_class="GLACIER_IR", rule_id="R2_TO_GIR"),
    ])
    db.commit()
    db.delete(doc)
    db.commit()
    for model in (Document, DocumentVersion, ProcessingJob, AccessLog, StorageRecommendation):
        assert db.query(model).count() == 0
    assert db.query(User).count() == 1


def test_job_deliveries_default_and_check(db):
    doc, v = make_active_doc(db, make_user(db))
    job = ProcessingJob(version_id=v.id, document_id=doc.id)
    db.add(job)
    db.flush()
    db.refresh(job)
    assert (job.deliveries, job.claimed_at, job.attempts) == (0, None, 0)
    job.deliveries = -1
    assert_violates(db, lambda: None, "ck_jobs_deliveries")
