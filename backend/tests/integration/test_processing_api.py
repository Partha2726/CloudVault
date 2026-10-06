"""T18: GET /documents/{id}/processing and POST .../processing/retry (doc 05.5, W16; AM-7)."""

import uuid

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import ProcessingJob
from app.processing.worker import ProcessingWorker
from app.storage import get_storage
from tests.integration.test_worker import Clock, job_for


def error(r):
    return r.status_code, r.json()["error"]["code"]


@pytest.fixture
def doc(upload, alice):
    return upload(alice, "notes.txt", b"alpha beta gamma").json()


def status(client, headers, doc_id):
    r = client.get(f"/api/documents/{doc_id}/processing", headers=headers)
    assert r.status_code == 200
    return r.json()["items"]


def retry(client, headers, doc_id, **params):
    return client.post(f"/api/documents/{doc_id}/processing/retry", headers=headers, params=params)


def set_job(db, doc_id, **fields):
    sets = ", ".join(f"{k} = {v}" for k, v in fields.items())
    db.execute(text(f"UPDATE processing_jobs SET {sets} WHERE document_id = :d"), {"d": doc_id})
    db.commit()


def worker():
    return ProcessingWorker(SessionLocal, get_storage(), clock=Clock())


# ---- status ----

def test_status_per_version_newest_first(client, alice, doc):
    files = {"file": ("notes.txt", b"alpha beta gamma delta", "application/octet-stream")}
    client.post(f"/api/documents/{doc['id']}/versions", headers=alice, files=files)
    worker().run_once()
    items = status(client, alice, doc["id"])
    assert [i["version_number"] for i in items] == [2, 1]
    assert items[1] == {"version_number": 1, "status": "SUCCEEDED", "attempts": 0, "error_code": None,
                        "page_count": None, "word_count": 3, "stalled": False}
    assert items[0]["status"] == "PENDING"


def test_status_shows_stalled_after_ten_minutes(client, alice, doc, db):
    set_job(db, doc["id"], created_at="now() - interval '11 minutes'")
    assert status(client, alice, doc["id"])[0]["stalled"] is True


def test_status_scoping(client, alice, auth_headers, doc):
    bob = auth_headers("bob@example.com")
    assert error(client.get(f"/api/documents/{doc['id']}/processing", headers=bob)) == (404, "NOT_FOUND")
    assert error(client.get(f"/api/documents/{uuid.uuid4()}/processing", headers=alice)) == (404, "NOT_FOUND")
    assert error(client.get(f"/api/documents/{doc['id']}/processing")) == (401, "UNAUTHORIZED")


# ---- retry ----

def test_retry_failed_job_requeues_it_and_worker_processes_again(client, alice, doc, db):
    set_job(db, doc["id"], status="'FAILED'", finished_at="now()", error_code="'CORRUPT'",
            error_message="'bad'", deliveries=1)
    r = retry(client, alice, doc["id"])
    assert r.status_code == 202
    assert r.json() == {"version_number": 1, "status": "PENDING", "attempts": 1, "error_code": None,
                        "page_count": None, "word_count": None, "stalled": False}
    j = job_for(db, doc["id"])
    assert (j.deliveries, j.claimed_at, j.finished_at, j.error_message) == (0, None, None, None)
    assert worker().run_once().result == "SUCCEEDED"
    assert job_for(db, doc["id"]).attempts == 1


def test_retry_stalled_pending_job_after_delivery_cap(client, alice, doc, db):
    set_job(db, doc["id"], deliveries=3, claimed_at="now() - interval '1 hour'",
            created_at="now() - interval '30 minutes'")
    assert worker().run_once() is None  # cap reached
    assert retry(client, alice, doc["id"]).status_code == 202
    assert status(client, alice, doc["id"])[0]["stalled"] is False  # stall clock restarted
    assert worker().run_once().result == "SUCCEEDED"


def test_retry_pending_not_stalled_is_a_no_op(client, alice, doc, db):
    before = job_for(db, doc["id"])
    before_created, before_attempts = before.created_at, before.attempts
    r = retry(client, alice, doc["id"])
    assert r.status_code == 202 and r.json()["status"] == "PENDING"
    after = job_for(db, doc["id"])
    assert (after.created_at, after.attempts) == (before_created, before_attempts)


@pytest.mark.parametrize("final", ["SUCCEEDED", "SKIPPED"])
def test_retry_finished_job_is_not_retryable(client, alice, doc, db, final):
    set_job(db, doc["id"], status=f"'{final}'", finished_at="now()")
    assert error(retry(client, alice, doc["id"])) == (409, "JOB_NOT_RETRYABLE")
    assert job_for(db, doc["id"]).status == final


def test_retry_specific_version_and_errors(client, alice, auth_headers, doc, db):
    set_job(db, doc["id"], status="'FAILED'", finished_at="now()")
    assert retry(client, alice, doc["id"], version=1).status_code == 202
    assert error(retry(client, alice, doc["id"], version=9)) == (404, "VERSION_NOT_FOUND")
    assert error(retry(client, alice, doc["id"], version=0)) == (422, "VALIDATION_ERROR")
    assert error(retry(client, auth_headers("bob@example.com"), doc["id"])) == (404, "NOT_FOUND")


def test_retry_of_missing_version_is_410(client, alice, doc, db):
    set_job(db, doc["id"], status="'FAILED'", finished_at="now()", error_code="'S3_MISSING'")
    db.execute(text("UPDATE document_versions SET state='S3_MISSING' WHERE document_id=:d"), {"d": doc["id"]})
    db.commit()
    assert error(retry(client, alice, doc["id"])) == (410, "VERSION_EXPIRED")


def test_retry_never_creates_a_second_job(client, alice, doc, db):
    set_job(db, doc["id"], status="'FAILED'", finished_at="now()")
    for _ in range(3):
        retry(client, alice, doc["id"])
        set_job(db, doc["id"], status="'FAILED'", finished_at="now()")
    db.rollback()
    assert db.query(ProcessingJob).filter(ProcessingJob.document_id == uuid.UUID(doc["id"])).count() == 1


def test_in_flight_delivery_of_old_attempt_cannot_finish_after_retry(client, alice, doc, db):
    """Stalled job still claimed by a slow worker: the retry wins; the old delivery's finish is a no-op."""
    w = worker()
    claim = w.claim()
    set_job(db, doc["id"], created_at="now() - interval '15 minutes'")
    assert retry(client, alice, doc["id"]).status_code == 202
    assert w.process(claim).result == "lost"
    assert job_for(db, doc["id"]).status == "PENDING"
    assert worker().run_once().result == "SUCCEEDED"
    db.rollback()
    assert db.scalar(select(ProcessingJob.deliveries).where(ProcessingJob.document_id == uuid.UUID(doc["id"]))) == 1
