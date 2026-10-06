"""T8 concurrency: per-document advisory lock (AM-1), C3, independence, pool safety, storage limit.

T10 (competing deletes), T11 (competing version uploads) and T14 (Apply) concurrency are
tested with those tasks.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.locks import document_lock, lock_engine, lock_key
from app.models import Document
from app.storage import get_storage
from app.storage.postgres import PostgresObjectStorage

WAIT = 10  # seconds; generous upper bound so slow machines do not flake


def advisory_locks_held() -> int:
    with engine.connect() as conn:
        return conn.scalar(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            )
        )


def assert_pools_idle(db=None):
    if db is not None:
        db.rollback()  # the test's own session; it is not part of the code under test
    assert lock_engine.pool.checkedout() == 0
    assert engine.pool.checkedout() == 0
    assert advisory_locks_held() == 0


# ---- document_lock semantics ----

def test_lock_key_is_deterministic_signed_64_bit_and_distinct():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert lock_key(a) == lock_key(str(a))
    assert lock_key(a) != lock_key(b)
    keys = {lock_key(uuid.uuid4()) for _ in range(10_000)}
    assert len(keys) == 10_000
    assert all(-(2**63) <= k < 2**63 for k in keys)


def test_same_document_is_serialized(migrated_db):
    doc = uuid.uuid4()
    holding, release, second_in = threading.Event(), threading.Event(), threading.Event()

    def first():
        with document_lock(doc):
            holding.set()
            release.wait(WAIT)

    def second():
        holding.wait(WAIT)
        with document_lock(doc):
            second_in.set()

    with ThreadPoolExecutor(2) as pool:
        f1, f2 = pool.submit(first), pool.submit(second)
        assert holding.wait(WAIT)
        assert not second_in.wait(0.5), "second holder entered while the first still held the lock"
        release.set()
        assert second_in.wait(WAIT)
        f1.result(), f2.result()
    assert_pools_idle()


def test_different_documents_do_not_block_each_other(migrated_db):
    barrier = threading.Barrier(2, timeout=WAIT)

    def hold(doc):
        with document_lock(doc):
            barrier.wait()  # both must be inside their locks at the same time

    with ThreadPoolExecutor(2) as pool:
        for f in [pool.submit(hold, uuid.uuid4()), pool.submit(hold, uuid.uuid4())]:
            f.result()
    assert_pools_idle()


def test_lock_released_and_connection_returned_on_error(migrated_db):
    doc = uuid.uuid4()
    with pytest.raises(RuntimeError):
        with document_lock(doc):
            assert advisory_locks_held() == 1
            raise RuntimeError("boom")
    assert_pools_idle()
    with document_lock(doc):  # immediately available again
        pass


def test_lock_holds_no_open_transaction(migrated_db):
    doc = uuid.uuid4()
    with document_lock(doc):
        with engine.connect() as conn:
            states = conn.scalars(
                text(
                    "SELECT state FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            ).all()
        assert "idle in transaction" not in states
    assert_pools_idle()


def test_repeated_locked_operations_do_not_exhaust_pools(migrated_db):
    total = lock_engine.pool.size() + lock_engine.pool._max_overflow  # noqa: SLF001
    for i in range(total * 5):
        try:
            with document_lock(uuid.uuid4()):
                if i % 3 == 0:
                    raise ValueError("error inside the critical section")
        except ValueError:
            pass
    assert_pools_idle()

    # Many threads at once, more than either pool's capacity.
    def work(_):
        with document_lock(uuid.uuid4()):
            with SessionLocal() as s:  # a main-pool connection used inside the lock
                s.execute(text("SELECT 1"))

    with ThreadPoolExecutor(40) as pool:
        list(pool.map(work, range(200)))
    assert_pools_idle()


# ---- uploads ----

class GatedStorage:
    """Real simulated store whose put_object can be held open to force overlaps."""

    def __init__(self, inner=None):
        self._inner = inner or get_storage()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.barrier: threading.Barrier | None = None
        self.gate = True

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def put_object(self, *args, **kwargs):
        self.entered.set()
        if self.barrier is not None:
            self.barrier.wait()
        elif self.gate:
            self.release.wait(WAIT)
        return self._inner.put_object(*args, **kwargs)


def post(app, headers, name, data):
    client = TestClient(app, raise_server_exceptions=False)
    return client.post("/api/documents", headers=headers, files={"file": (name, data, "application/octet-stream")})


def test_c3_same_name_concurrent_create(app, auth_headers, db):
    """One 201, one 409; the loser never reaches storage, so no orphan object (doc 10 C3)."""
    alice = auth_headers("alice@example.com")
    gated = GatedStorage()
    app.dependency_overrides[get_storage] = lambda: gated

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(post, app, alice, "report.txt", b"first version")
        assert gated.entered.wait(WAIT)  # first upload is inside storage, holding its document lock
        second = pool.submit(post, app, alice, "report.txt", b"second version").result(WAIT)
        gated.release.set()
        first = first.result(WAIT)

    assert (first.status_code, second.status_code) == (201, 409)
    assert second.json()["error"]["details"] == {"existing_document_id": first.json()["id"]}
    assert len(gated.list_object_versions("documents/")) == 1
    assert [d.status for d in db.scalars(select(Document))] == ["ACTIVE"]
    assert_pools_idle(db)


def test_identical_concurrent_uploads_store_one_object(app, auth_headers, db):
    """Same name and content at once: one creates; the other is 409 (in flight) or 200 duplicate."""
    alice = auth_headers("alice@example.com")
    gated = GatedStorage()
    app.dependency_overrides[get_storage] = lambda: gated
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(post, app, alice, "same.txt", b"identical")
        assert gated.entered.wait(WAIT)
        second = pool.submit(post, app, alice, "same.txt", b"identical").result(WAIT)
        gated.release.set()
        first = first.result(WAIT)
    assert first.status_code == 201 and second.status_code in (200, 409)
    assert len(gated.list_object_versions("documents/")) == 1


def test_uploads_to_different_documents_run_concurrently(app, auth_headers):
    """Both uploads must be inside storage at the same moment; a global lock would deadlock the barrier."""
    alice = auth_headers("alice@example.com")
    gated = GatedStorage()
    gated.barrier = threading.Barrier(2, timeout=WAIT)
    app.dependency_overrides[get_storage] = lambda: gated
    with ThreadPoolExecutor(2) as pool:
        results = [f.result(WAIT * 2) for f in [
            pool.submit(post, app, alice, "one.txt", b"one"),
            pool.submit(post, app, alice, "two.txt", b"two"),
        ]]
    assert [r.status_code for r in results] == [201, 201]
    assert_pools_idle()


def test_many_concurrent_uploads_do_not_exhaust_pools(app, auth_headers, db):
    """More concurrent uploads than either pool holds; storage is slowed so they overlap."""
    users = [auth_headers(f"user{i}@example.com") for i in range(3)]

    class SlowStorage(GatedStorage):
        def put_object(self, *args, **kwargs):
            time.sleep(0.05)
            return self._inner.put_object(*args, **kwargs)

    app.dependency_overrides[get_storage] = lambda: SlowStorage()
    jobs = [(users[i % 3], f"file{i}.txt", f"content {i}".encode()) for i in range(36)]  # 12 per user (< 20/min)
    with ThreadPoolExecutor(36) as pool:
        codes = [r.status_code for r in pool.map(lambda j: post(app, *j), jobs)]
    assert codes == [201] * 36
    assert db.query(Document).filter(Document.status == "ACTIVE").count() == 36
    assert_pools_idle(db)


def test_concurrent_uploads_respect_storage_limit(app, auth_headers, db):
    """The atomic storage-limit invariant holds under contention; failures leave FAILED rows only."""
    alice = auth_headers("alice@example.com")
    limited = PostgresObjectStorage(SessionLocal, "cloudvault-sim", limit_bytes=100)
    app.dependency_overrides[get_storage] = lambda: limited
    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(lambda i: post(app, alice, f"f{i}.txt", b"x" * 29 + str(i).encode()), range(5)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 201, 201, 507, 507]
    assert limited.total_stored_bytes() == 90
    statuses = sorted(d.status for d in db.scalars(select(Document)))
    assert statuses == ["ACTIVE", "ACTIVE", "ACTIVE", "FAILED", "FAILED"]
    # Every stored object belongs to an ACTIVE document: no orphans from the failed uploads.
    active_keys = {d.s3_key for d in db.scalars(select(Document).where(Document.status == "ACTIVE"))}
    assert {v.key for v in limited.list_object_versions("documents/")} == active_keys
    assert_pools_idle(db)
