"""T5: simulated S3 store semantics (AM-7, docs/VERIFIED.md). Replaces doc 10 A1/A2."""

import base64
import hashlib
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.db import SessionLocal
from app.storage import build_key, get_storage
from app.storage.base import (
    BadDigest,
    InvalidArgument,
    MethodNotAllowed,
    NoSuchKey,
    NoSuchVersion,
    StorageLimitExceeded,
)
from app.storage.postgres import PostgresObjectStorage

KEY = "documents/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def tick(self, seconds=1):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(db, clock):
    return PostgresObjectStorage(SessionLocal, "cv-test", limit_bytes=1_000_000, clock=clock)


def put(store, data=b"hello", key=KEY, **kw):
    kw.setdefault("content_type", "text/plain")
    return store.put_object(key, data, **kw)


# ---- put / head / get ----

def test_put_returns_version_etag_and_stores_bytes(store):
    r = put(store, b"hello", metadata={"cv-doc-id": "d"}, tags={"project": "cloudvault", "env": "test"})
    assert len(r.version_id) == 32
    assert r.etag == f'"{hashlib.md5(b"hello").hexdigest()}"'  # VERIFIED row 6
    head, data = store.get_object(KEY)
    assert data == b"hello"
    assert (head.version_id, head.size_bytes, head.is_latest) == (r.version_id, 5, True)
    assert head.content_type == "text/plain"
    assert head.metadata == {"cv-doc-id": "d"}
    assert head.checksum_sha256 == base64.b64encode(hashlib.sha256(b"hello").digest()).decode()
    assert store.get_object_tagging(KEY) == {"project": "cloudvault", "env": "test"}


def test_head_omits_storage_class_for_standard(store):  # A2, VERIFIED row 5
    put(store)
    assert store.head_object(KEY).storage_class is None


def test_checksum_verified(store):  # VERIFIED row 7
    good = base64.b64encode(hashlib.sha256(b"abc").digest()).decode()
    put(store, b"abc", checksum_sha256=good)
    with pytest.raises(BadDigest):
        put(store, b"abd", checksum_sha256=good)


def test_missing_key_and_version(store):
    with pytest.raises(NoSuchKey):
        store.head_object(KEY)
    put(store)
    with pytest.raises(NoSuchVersion):
        store.get_object(KEY, "nope")


# ---- versioning and delete markers (A1) ----

def test_put_put_delete_gives_two_versions_and_a_marker(store, clock):
    v1 = put(store, b"one").version_id
    clock.tick()
    v2 = put(store, b"two").version_id
    clock.tick()
    marker = store.delete_object(KEY)  # VERIFIED row 1
    entries = store.list_object_versions("documents/")
    assert [(e.version_id, e.is_delete_marker, e.is_latest) for e in entries] == [
        (marker, True, True), (v2, False, False), (v1, False, False),
    ]
    # Current version is a marker: 404 with the delete-marker flag (VERIFIED row 3).
    with pytest.raises(NoSuchKey) as exc:
        store.get_object(KEY)
    assert exc.value.delete_marker
    # Naming the marker's version: 405.
    with pytest.raises(MethodNotAllowed):
        store.head_object(KEY, marker)
    # Older versions stay readable by id.
    assert store.get_object(KEY, v1)[1] == b"one"


def test_undelete_by_removing_marker(store):  # VERIFIED row 2
    put(store, b"one")
    v2 = put(store, b"two").version_id
    marker = store.delete_object(KEY)
    store.delete_version(KEY, marker)
    head, data = store.get_object(KEY)
    assert (head.version_id, data, head.is_latest) == (v2, b"two", True)


def test_plain_delete_on_marker_adds_another_marker(store):
    put(store)
    m1 = store.delete_object(KEY)
    m2 = store.delete_object(KEY)
    assert m1 != m2
    assert [e.is_delete_marker for e in store.list_object_versions(KEY)] == [True, True, False]


def test_delete_version_is_exact_and_idempotent(store):
    v1 = put(store, b"one").version_id
    put(store, b"two")
    store.delete_version(KEY, v1)
    store.delete_version(KEY, v1)  # already gone: no error
    remaining = [e.version_id for e in store.list_object_versions(KEY)]
    assert len(remaining) == 1 and v1 not in remaining


def test_delete_all_versions_removes_versions_and_markers(store):
    put(store, b"one")
    put(store, b"two")
    store.delete_object(KEY)
    other = KEY[:-1] + "9"
    put(store, b"keep", key=other)
    results = store.delete_all_versions(KEY)
    assert len(results) == 3 and all(r.deleted for r in results)
    assert store.list_object_versions(KEY) == []
    assert len(store.list_object_versions(other)) == 1


# ---- copy (restore and apply) ----

def test_copy_creates_new_version_with_requested_class(store):  # VERIFIED row 4
    src = put(store, b"data", tags={"project": "cloudvault"}).version_id
    r = store.copy_object(KEY, src, storage_class="STANDARD_IA")
    assert r.version_id != src
    head, data = store.get_object(KEY)
    assert (head.version_id, head.storage_class, data) == (r.version_id, "STANDARD_IA", b"data")
    assert store.get_object_tagging(KEY) == {"project": "cloudvault"}
    assert store.get_object(KEY, src)[1] == b"data"  # source untouched


def test_copy_without_class_is_standard(store):
    src = put(store).version_id
    ia = store.copy_object(KEY, src, storage_class="GLACIER_IR").version_id
    restored = store.copy_object(KEY, ia).version_id
    assert store.head_object(KEY, restored).storage_class is None  # STANDARD


def test_copy_from_old_version_restores_content(store):
    v1 = put(store, b"one").version_id
    put(store, b"two")
    store.copy_object(KEY, v1)
    assert store.get_object(KEY)[1] == b"one"
    assert len(store.list_object_versions(KEY)) == 3


def test_copy_errors(store):
    put(store)
    marker = store.delete_object(KEY)
    with pytest.raises(NoSuchVersion):
        store.copy_object(KEY, "missing")
    with pytest.raises(MethodNotAllowed):
        store.copy_object(KEY, marker)
    with pytest.raises(InvalidArgument):
        store.copy_object(KEY, marker, storage_class="DEEP_ARCHIVE")


# ---- validation ----

@pytest.mark.parametrize(
    "kwargs",
    [
        {"tags": {f"k{i}": "v" for i in range(11)}},
        {"tags": {"k" * 129: "v"}},
        {"tags": {"k": "v" * 257}},
        {"metadata": {"name": "résumé"}},
        {"content_type": ""},
    ],
)
def test_invalid_arguments(store, kwargs):
    with pytest.raises(InvalidArgument):
        put(store, **kwargs)


def test_key_length_limits(store):
    with pytest.raises(InvalidArgument):
        put(store, key="")
    with pytest.raises(InvalidArgument):
        put(store, key="k" * 1025)


def test_list_prefix_escapes_wildcards(store):
    put(store, key="documents/a_b/x")
    put(store, key="documents/aXb/x")
    assert [e.key for e in store.list_object_versions("documents/a_b/")] == ["documents/a_b/x"]


# ---- storage limit ----

def test_storage_limit_counts_every_version(db, clock):
    small = PostgresObjectStorage(SessionLocal, "cv-test", limit_bytes=10, clock=clock)
    v1 = small.put_object(KEY, b"12345", content_type="text/plain").version_id
    small.put_object(KEY, b"1234", content_type="text/plain")
    with pytest.raises(StorageLimitExceeded):
        small.put_object(KEY, b"12", content_type="text/plain")
    with pytest.raises(StorageLimitExceeded):
        small.copy_object(KEY, v1)
    assert small.total_stored_bytes() == 9
    small.delete_version(KEY, v1)
    small.put_object(KEY, b"12", content_type="text/plain")


def test_concurrent_writes_cannot_overshoot_limit(db):
    limited = PostgresObjectStorage(SessionLocal, "cv-test", limit_bytes=100)
    errors, barrier = [], threading.Barrier(5)

    def write(i):
        barrier.wait()
        try:
            limited.put_object(f"{KEY}{i}", b"x" * 30, content_type="text/plain")
        except StorageLimitExceeded:
            errors.append(i)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert limited.total_stored_bytes() == 90
    assert len(errors) == 2


# ---- provider ----

def test_provider_and_key_builder(db):
    store = get_storage()
    store.check()
    assert store.bucket == "cloudvault-sim"
    assert build_key(
        "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    ) == KEY
    with pytest.raises(ValueError):
        build_key("../etc", "x")
