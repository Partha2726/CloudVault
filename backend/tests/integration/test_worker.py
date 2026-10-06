"""T17: durable processing worker (AM-7). Reliability and concurrency, proven against real DB + store."""

import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import Document, DocumentVersion, ProcessingJob
from app.processing import worker as worker_module
from app.processing.extract import extract
from app.processing.worker import ProcessingWorker
from app.storage import get_storage
from app.storage.base import StorageError
from tests.integration.test_document_concurrency import assert_pools_idle

WAIT = 10


class Clock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


def make_worker(clock=None, storage=None, **kw):
    return ProcessingWorker(SessionLocal, storage or get_storage(), clock=clock or Clock(), **kw)


def docs(upload, headers, n, prefix="doc"):
    return [upload(headers, f"{prefix}{i}.txt", f"{prefix} document {i} body text".encode()).json() for i in range(n)]


def job_for(db, doc_id) -> ProcessingJob:
    db.rollback()
    return db.scalar(select(ProcessingJob).where(ProcessingJob.document_id == uuid.UUID(doc_id))
                     .execution_options(populate_existing=True))


def version_of(db, doc_id) -> DocumentVersion:
    db.rollback()
    d = db.get(Document, uuid.UUID(doc_id), populate_existing=True)
    return db.get(DocumentVersion, d.current_version_id, populate_existing=True)


class Wrapped:
    def __init__(self, **overrides):
        self._inner = get_storage()
        for k, v in overrides.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def drain(worker, limit=100):
    outcomes = []
    for _ in range(limit):
        o = worker.run_once()
        if o is None:
            break
        outcomes.append(o)
    return outcomes


# ---- basic delivery ----

def test_processes_a_pending_job(upload, alice, db, clock):
    d = upload(alice, "notes.txt", b"alpha beta gamma").json()
    outcome = make_worker(clock).run_once()
    assert outcome.result == "SUCCEEDED"
    j = job_for(db, d["id"])
    assert (j.status, j.word_count, j.text_excerpt, j.deliveries) == ("SUCCEEDED", 3, "alpha beta gamma", 1)
    assert j.finished_at is not None
    assert make_worker(clock).run_once() is None  # nothing left
    assert_pools_idle(db)


def test_a3_upload_to_processed_result_over_the_api(client, upload, alice, clock):
    """A3 as amended by AM-7: the job row (not an S3 event) triggers the worker; the API shows the result."""
    from app.scripts.seed_demo import _pdf

    d = upload(alice, "minutes.pdf", _pdf(["Board minutes", "Budget approved unanimously"], 2048)).json()
    pending = client.get(f"/api/documents/{d['id']}/processing", headers=alice).json()["items"]
    assert [(i["version_number"], i["status"]) for i in pending] == [(1, "PENDING")]
    assert make_worker(clock).run_once().result == "SUCCEEDED"
    item = client.get(f"/api/documents/{d['id']}/processing", headers=alice).json()["items"][0]
    assert (item["status"], item["page_count"], item["error_code"]) == ("SUCCEEDED", 1, None)
    assert item["word_count"] >= 5
    summary = client.get(f"/api/documents/{d['id']}", headers=alice).json()["processing"]
    assert (summary["status"], summary["page_count"], summary["word_count"]) == ("SUCCEEDED", 1, item["word_count"])


def test_jobs_are_processed_oldest_first(upload, alice, db, clock):
    ds = docs(upload, alice, 3)
    worker = make_worker(clock)
    order = [worker.run_once().job_id for _ in range(3)]
    assert order == [job_for(db, d["id"]).id for d in ds]


def test_oversized_object_is_skipped_without_reading(upload, alice, db, clock):
    d = upload(alice, "big.txt", b"x" * 300).json()
    def no_read(*a, **k):
        raise AssertionError("read an object over the size gate")
    outcome = make_worker(clock, storage=Wrapped(get_object=no_read), max_process_bytes=100).run_once()
    assert outcome.result == "SKIPPED" and job_for(db, d["id"]).error_code == "TOO_LARGE"


# ---- many workers, one queue ----

def test_many_workers_process_each_job_exactly_once(upload, alice, auth_headers, db):
    docs(upload, alice, 10)
    docs(upload, auth_headers("bob@example.com"), 10, prefix="bob")
    calls, lock = Counter(), threading.Lock()

    def counting(content_type, data, **kw):
        with lock:
            calls[data] += 1
        time.sleep(0.01)
        return extract(content_type, data, **kw)

    workers = [make_worker(extractor=counting) for _ in range(5)]
    with ThreadPoolExecutor(5) as pool:
        results = [o for batch in pool.map(drain, workers) for o in batch]
    assert sorted(o.result for o in results) == ["SUCCEEDED"] * 20
    assert len({o.job_id for o in results}) == 20
    assert set(calls.values()) == {1}  # no document extracted twice
    db.rollback()
    assert {j.status for j in db.scalars(select(ProcessingJob))} == {"SUCCEEDED"}
    assert {j.deliveries for j in db.scalars(select(ProcessingJob))} == {1}
    assert_pools_idle(db)


def test_workers_extract_different_documents_at_the_same_time_without_open_transactions(upload, alice, db):
    docs(upload, alice, 2)
    barrier = threading.Barrier(2, timeout=WAIT)
    seen_states = []

    def gated(content_type, data, **kw):
        barrier.wait()  # both deliveries are inside extraction together
        with engine.connect() as conn:
            seen_states.extend(conn.execute(text(
                "SELECT state, left(query, 120) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )).all())
        barrier.wait()
        return extract(content_type, data, **kw)

    workers = [make_worker(extractor=gated) for _ in range(2)]
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(lambda w: w.run_once(), workers))
    assert sorted(o.result for o in outcomes) == ["SUCCEEDED", "SUCCEEDED"]
    # No transaction held during work (the probe's own query in the other thread excluded).
    held = [q for st, q in seen_states if st == "idle in transaction" and "pg_stat_activity" not in q]
    assert held == []
    assert_pools_idle(db)


# ---- leases, restarts, duplicate delivery (C4) ----

def test_active_lease_is_not_reclaimed(upload, alice, db, clock):
    upload(alice, "a.txt", b"one two")
    assert make_worker(clock).claim() is not None
    clock.advance(60)
    assert make_worker(clock).claim() is None


def test_crashed_delivery_is_reclaimed_after_the_lease(upload, alice, db, clock):
    d = upload(alice, "a.txt", b"one two").json()
    make_worker(clock).claim()  # this worker "dies" before working
    clock.advance(121)
    outcome = make_worker(clock).run_once()
    assert outcome.result == "SUCCEEDED"
    assert job_for(db, d["id"]).deliveries == 2


def test_c4_duplicate_delivery_cannot_overwrite_the_result(upload, alice, db, clock):
    d = upload(alice, "a.txt", b"one two three").json()
    slow, fast = make_worker(clock), make_worker(clock)
    first = slow.claim()
    clock.advance(121)  # first lease expires while it is still working
    assert fast.run_once().result == "SUCCEEDED"
    late = slow.process(first)  # the first delivery finishes late
    assert late.result == "lost"
    j = job_for(db, d["id"])
    assert (j.status, j.word_count, j.deliveries) == ("SUCCEEDED", 3, 2)


def test_restart_loses_no_job(app, upload, alice, db, clock):
    """Jobs written while no worker runs are processed by the next worker."""
    ds = docs(upload, alice, 3)
    assert all(job_for(db, d["id"]).status == "PENDING" for d in ds)
    assert [o.result for o in drain(make_worker(clock))] == ["SUCCEEDED"] * 3


# ---- delivery limit ----

def test_delivery_limit_then_stalled_and_not_claimed(client, upload, alice, db, clock):
    d = upload(alice, "a.txt", b"text").json()

    def broken(*a, **k):
        raise StorageError("store unavailable")

    w = make_worker(clock, storage=Wrapped(get_object=broken))
    for _ in range(3):
        assert w.run_once().result == "transient"
        clock.advance(121)
    assert w.run_once() is None  # cap reached: no fourth delivery
    j = job_for(db, d["id"])
    assert (j.status, j.deliveries) == ("PENDING", 3)
    db.execute(text("UPDATE processing_jobs SET created_at = now() - interval '11 minutes'"))
    db.commit()
    assert client.get(f"/api/documents/{d['id']}", headers=alice).json()["processing"]["stalled"] is True


def test_transient_error_then_success(upload, alice, db, clock):
    d = upload(alice, "a.txt", b"recover me").json()
    calls = {"n": 0}
    real = get_storage()

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StorageError("blip")
        return real.get_object(*a, **k)

    w = make_worker(clock, storage=Wrapped(get_object=flaky))
    assert w.run_once().result == "transient"
    assert w.run_once() is None  # lease still held
    clock.advance(121)
    assert w.run_once().result == "SUCCEEDED"
    assert job_for(db, d["id"]).deliveries == 2


def test_finish_failure_is_retried_on_the_next_delivery(upload, alice, db, clock, monkeypatch):
    d = upload(alice, "a.txt", b"finish later").json()
    w = make_worker(clock)
    real_finish = w.finish
    calls = {"n": 0}

    def flaky_finish(claim, result):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("UPDATE", {}, Exception("db blip"))
        return real_finish(claim, result)

    monkeypatch.setattr(w, "finish", flaky_finish)
    assert w.run_once().result == "transient"
    assert job_for(db, d["id"]).status == "PENDING"
    clock.advance(121)
    assert w.run_once().result == "SUCCEEDED"


# ---- missing and unavailable versions ----

def test_missing_stored_version_marks_s3_missing(upload, alice, db, clock):
    d = upload(alice, "a.txt", b"gone soon").json()
    v = version_of(db, d["id"])
    get_storage().delete_version(db.get(Document, uuid.UUID(d["id"])).s3_key, v.s3_version_id)
    assert make_worker(clock).run_once().result == "FAILED"
    j = job_for(db, d["id"])
    assert (j.status, j.error_code) == ("FAILED", "S3_MISSING")
    assert version_of(db, d["id"]).state == "S3_MISSING"


@pytest.mark.parametrize(("state", "code"), [("S3_MISSING", "S3_MISSING")])
def test_unavailable_version_fails_without_storage_call(upload, alice, db, clock, state, code):
    d = upload(alice, "a.txt", b"x y").json()
    db.execute(text("UPDATE document_versions SET state=:s WHERE document_id=:d"), {"s": state, "d": d["id"]})
    db.commit()

    def no_read(*a, **k):
        raise AssertionError("storage read for an unavailable version")

    assert make_worker(clock, storage=Wrapped(get_object=no_read)).run_once().result == "FAILED"
    assert job_for(db, d["id"]).error_code == code


def test_concurrent_apply_does_not_cause_a_false_s3_missing(upload, alice, db, clock):
    """An Apply swaps the stored copy after the claim: the job is re-read, not marked missing."""
    d = upload(alice, "a.txt", b"moving target text").json()
    w = make_worker(clock)
    claim = w.claim()
    doc = db.get(Document, uuid.UUID(d["id"]))
    v = version_of(db, d["id"])
    old = v.s3_version_id
    new = get_storage().copy_object(doc.s3_key, old, storage_class="STANDARD_IA").version_id
    db.execute(text("UPDATE document_versions SET s3_version_id=:n, storage_class='STANDARD_IA' WHERE id=:v"),
               {"n": new, "v": v.id})
    db.commit()
    get_storage().delete_version(doc.s3_key, old)

    assert w.process(claim).result == "reread"
    assert version_of(db, d["id"]).state == "ACTIVE"
    assert job_for(db, d["id"]).claimed_at is None  # lease released at once
    assert w.run_once().result == "SUCCEEDED"


def test_document_permanently_deleted_mid_delivery(upload, alice, db, clock):
    d = upload(alice, "a.txt", b"bye").json()
    w = make_worker(clock)
    claim = w.claim()
    doc = db.get(Document, uuid.UUID(d["id"]))
    get_storage().delete_all_versions(doc.s3_key)
    db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": d["id"]})
    db.commit()
    assert w.process(claim).result in ("reread", "lost")
    assert w.run_once() is None
    assert_pools_idle(db)


# ---- application lifespan ----

def test_worker_runs_inside_the_app(app, upload, alice, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "processing_worker_enabled", True)
    monkeypatch.setattr(get_settings(), "processing_poll_seconds", 0.05)
    with TestClient(app) as live:
        d = upload(alice, "live.txt", b"processed by the running app", test_client=live).json()
        deadline = time.time() + WAIT
        while time.time() < deadline and job_for(db, d["id"]).status == "PENDING":
            time.sleep(0.05)
        assert job_for(db, d["id"]).status == "SUCCEEDED"
    alive = [t for t in threading.enumerate() if t.name == "cloudvault-processing-worker"]
    assert alive == []  # stopped cleanly on shutdown


def test_loop_survives_unexpected_errors(monkeypatch, clock):
    w = make_worker(clock, poll_seconds=0.01)
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("unexpected")

    monkeypatch.setattr(w, "run_once", boom)
    w.start()
    time.sleep(0.1)
    w.stop()
    assert calls["n"] >= 2
    assert worker_module.MAX_DELIVERIES == 3
