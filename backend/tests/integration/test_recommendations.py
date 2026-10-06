"""T14: recommendation refresh/list/dismiss/apply (doc 03 W10/W11, doc 07; AM-1, AM-7).

Doc 10.2 I10, I11, stale detection, failure paths, and every APPLY recovery state (A-D).
Cold documents are built through the API and then backdated in the database, as the
seed script will do (doc 07.7); the real T13 engine produces the recommendations.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.models import AccessLog, Document, DocumentVersion, StorageRecommendation
from app.services import recommendation_service
from app.storage import get_storage
from app.storage.base import StorageError

BIG = 200 * 1024  # above REC_MIN_SIZE (128 KiB)


def error(r):
    return r.status_code, r.json()["error"]["code"]


@pytest.fixture
def alice(auth_headers):
    return auth_headers("alice@example.com")


@pytest.fixture
def bob(auth_headers):
    return auth_headers("bob@example.com")


def backdate(db, doc_id, days):
    t = datetime.now(UTC) - timedelta(days=days)
    db.execute(text("UPDATE document_versions SET created_at=:t, storage_class_changed_at=:t WHERE document_id=:d"),
               {"t": t, "d": doc_id})
    db.commit()


def add_access(db, doc_id, user_id, days_ago):
    version = current_version(db, doc_id)
    db.add(AccessLog(document_id=uuid.UUID(doc_id), version_id=version.id, user_id=user_id,
                     accessed_at=datetime.now(UTC) - timedelta(days=days_ago)))
    db.commit()


def set_class(db, doc_id, storage_class, days_ago):
    """Put the current version in another class in both DB and store (as an earlier Apply would)."""
    v = current_version(db, doc_id)
    db.execute(text("UPDATE sim_object_versions SET storage_class=:c WHERE version_id=:v"),
               {"c": storage_class, "v": v.s3_version_id})
    db.execute(text("UPDATE document_versions SET storage_class=:c, storage_class_changed_at=:t WHERE id=:id"),
               {"c": storage_class, "t": datetime.now(UTC) - timedelta(days=days_ago), "id": v.id})
    db.commit()


def doc_row(db, doc_id) -> Document:
    db.rollback()
    return db.get(Document, uuid.UUID(doc_id), populate_existing=True)


def current_version(db, doc_id) -> DocumentVersion:
    d = doc_row(db, doc_id)
    return db.get(DocumentVersion, d.current_version_id, populate_existing=True)


def store_entries(db, doc_id):
    return get_storage().list_object_versions(doc_row(db, doc_id).s3_key)


def rec_row(db, rec_id) -> StorageRecommendation:
    db.rollback()
    return db.get(StorageRecommendation, uuid.UUID(rec_id), populate_existing=True)


def refresh(client, headers):
    r = client.post("/api/recommendations/refresh", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def apply(client, headers, rec_id):
    return client.post(f"/api/recommendations/{rec_id}/apply", headers=headers)


def one_rec(client, headers):
    items = refresh(client, headers)
    assert len(items) == 1
    return items[0]


def assert_applied(db, doc_id, target, old_store_id):
    """Final invariants of a completed Apply in DB and store."""
    v = current_version(db, doc_id)
    assert v.storage_class == target and v.version_number == 1 and v.s3_version_id != old_store_id
    assert doc_row(db, doc_id).pending_op is None
    entries = store_entries(db, doc_id)
    assert [e.version_id for e in entries] == [v.s3_version_id]  # old stored version removed
    head = get_storage().head_object(doc_row(db, doc_id).s3_key, v.s3_version_id)
    assert head.storage_class == (None if target == "STANDARD" else target)


class StorageWrapper:
    def __init__(self, **overrides):
        self._inner = get_storage()
        for name, fn in overrides.items():
            setattr(self, name, fn)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def db_error(*args, **kwargs):
    raise OperationalError("COMMIT", {}, Exception("database went away"))


def storage_error(*args, **kwargs):
    raise StorageError("injected")


def fail_once(monkeypatch, module, name):
    real = getattr(module, name)
    calls = {"n": 0}

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("COMMIT", {}, Exception("database went away"))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)


# ---- refresh / list ----

def test_refresh_new_documents_gives_nothing(client, upload, alice):
    upload(alice, "fresh.txt", b"a" * BIG)
    assert refresh(client, alice) == []


def test_refresh_r3(client, alice, cold):
    doc = cold(rule="R3")
    rec = one_rec(client, alice)
    assert rec == {
        "id": rec["id"], "document_id": doc["id"], "display_name": "cold.txt", "version_number": 1,
        "current_class": "STANDARD", "recommended_class": "STANDARD_IA", "rule_id": "R3_TO_IA",
        "reason": "Low access frequency (1 in 90 days), idle 40 days",
        "signals": {"size_bytes": BIG, "age_days": 120, "a30": 0, "a90": 1, "idle_days": 40, "days_in_class": 120},
        "estimate": None, "status": "OPEN", "created_at": rec["created_at"],
    }


def test_refresh_r2_and_r1(client, alice, cold):
    cold("r2.txt", rule="R2", fill=b"b")
    cold("r1.txt", rule="R1", fill=b"c")
    by_name = {r["display_name"]: r for r in refresh(client, alice)}
    assert (by_name["r2.txt"]["rule_id"], by_name["r2.txt"]["recommended_class"]) == ("R2_TO_GIR", "GLACIER_IR")
    assert (by_name["r1.txt"]["rule_id"], by_name["r1.txt"]["recommended_class"]) == ("R1_PROMOTE", "STANDARD")


def test_refresh_replaces_open_with_stale(client, alice, cold):
    cold()
    first = one_rec(client, alice)
    second = one_rec(client, alice)
    assert first["id"] != second["id"]
    stale = client.get("/api/recommendations", headers=alice, params={"status": "stale"}).json()["items"]
    assert [r["id"] for r in stale] == [first["id"]]
    assert [r["id"] for r in client.get("/api/recommendations", headers=alice).json()["items"]] == [second["id"]]


def test_refresh_skips_trashed_small_and_missing(client, upload, alice, cold, db):
    trashed = cold("trashed.txt", fill=b"t")
    client.delete(f"/api/documents/{trashed['id']}", headers=alice)
    missing = cold("missing.txt", fill=b"m")
    db.execute(text("UPDATE document_versions SET state='S3_MISSING' WHERE document_id=:d"), {"d": missing["id"]})
    db.commit()
    small = upload(alice, "small.txt", b"s" * 1000).json()
    backdate(db, small["id"], days=200)
    assert refresh(client, alice) == []


def test_list_scoping_and_validation(client, alice, bob, cold):
    cold()
    refresh(client, alice)
    assert client.get("/api/recommendations", headers=bob).json()["items"] == []
    assert refresh(client, bob) == []
    assert error(client.get("/api/recommendations", headers=alice, params={"status": "x"})) == (422, "VALIDATION_ERROR")
    assert error(client.get("/api/recommendations")) == (401, "UNAUTHORIZED")


# ---- dismiss ----

def test_dismiss_is_idempotent_and_blocks_apply(client, alice, bob, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    assert error(client.post(f"/api/recommendations/{rec['id']}/dismiss", headers=bob)) == (404, "NOT_FOUND")
    r1 = client.post(f"/api/recommendations/{rec['id']}/dismiss", headers=alice).json()
    r2 = client.post(f"/api/recommendations/{rec['id']}/dismiss", headers=alice).json()
    assert r1["status"] == r2["status"] == "DISMISSED"
    assert error(apply(client, alice, rec["id"])) == (409, "STALE_RECOMMENDATION")
    assert len(store_entries(db, doc["id"])) == 1


# ---- I10: apply ----

@pytest.mark.parametrize(("rule", "target"), [("R3", "STANDARD_IA"), ("R2", "GLACIER_IR"), ("R1", "STANDARD")])
def test_i10_apply_changes_simulated_class(client, alice, cold, db, rule, target):
    doc = cold(rule=rule)
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"])
    old_id, old_store_id, old_changed_at = old.id, old.s3_version_id, old.storage_class_changed_at
    logs_before = db.query(AccessLog).count()
    r = apply(client, alice, rec["id"])
    assert r.status_code == 200 and r.json()["status"] == "APPLIED"
    assert_applied(db, doc["id"], target, old_store_id)
    assert current_version(db, doc["id"]).id == old_id  # same row, same number
    assert current_version(db, doc["id"]).storage_class_changed_at > old_changed_at
    assert db.query(AccessLog).count() == logs_before  # history kept with the version row
    detail = client.get(f"/api/documents/{doc['id']}", headers=alice).json()
    assert detail["current_version"]["storage_class"] == target
    assert rec_row(db, rec["id"]).resolved_at is not None


def test_applied_version_is_still_downloadable(client, alice, cold):
    doc = cold()
    apply(client, alice, one_rec(client, alice)["id"])
    url = client.get(f"/api/documents/{doc['id']}/download", headers=alice).json()["url"]
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    assert client.get(urlunsplit(("", "", parts.path, parts.query, ""))).content == b"a" * BIG


def test_already_applied_is_a_no_op(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    apply(client, alice, rec["id"])
    before = store_entries(db, doc["id"])
    app.dependency_overrides[get_storage] = lambda: StorageWrapper(copy_object=storage_error)
    r = apply(client, alice, rec["id"])
    assert r.status_code == 200 and r.json()["status"] == "APPLIED"
    assert store_entries(db, doc["id"]) == before


def test_engine_says_keep_after_apply(client, alice, cold):
    """Cooldown: the applied class is not re-recommended immediately."""
    cold()
    apply(client, alice, one_rec(client, alice)["id"])
    assert refresh(client, alice) == []


# ---- I11 and other stale cases ----

def test_i11_stale_after_new_accesses(client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    user_id = doc_row(db, doc["id"]).owner_id
    for d in (1, 2, 3):  # now a90 = 4 > 2: R3 no longer holds
        add_access(db, doc["id"], user_id, days_ago=d)
    before = store_entries(db, doc["id"])
    assert error(apply(client, alice, rec["id"])) == (409, "STALE_RECOMMENDATION")
    assert rec_row(db, rec["id"]).status == "STALE"
    assert store_entries(db, doc["id"]) == before and doc_row(db, doc["id"]).pending_op is None


def test_stale_after_new_version(client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    files = {"file": ("cold.txt", b"z" * BIG, "application/octet-stream")}
    assert client.post(f"/api/documents/{doc['id']}/versions", headers=alice, files=files).status_code == 201
    assert error(apply(client, alice, rec["id"])) == (409, "STALE_RECOMMENDATION")
    assert rec_row(db, rec["id"]).status == "STALE"
    assert all(e.storage_class == "STANDARD" for e in store_entries(db, doc["id"]))


def test_stale_when_document_trashed(client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    assert error(apply(client, alice, rec["id"])) == (409, "STALE_RECOMMENDATION")
    assert [e.is_delete_marker for e in store_entries(db, doc["id"])] == [True, False]


def test_apply_scoping(client, alice, bob, cold):
    cold()
    rec = one_rec(client, alice)
    assert error(apply(client, bob, rec["id"])) == (404, "NOT_FOUND")
    assert error(apply(client, alice, str(uuid.uuid4()))) == (404, "NOT_FOUND")
    assert error(client.post("/api/recommendations/nope/apply", headers=alice)) == (422, "VALIDATION_ERROR")


# ---- failures ----

def test_copy_failure_keeps_original(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"]).s3_version_id
    app.dependency_overrides[get_storage] = lambda: StorageWrapper(copy_object=storage_error)
    assert error(apply(client, alice, rec["id"])) == (502, "STORAGE_ERROR")
    assert rec_row(db, rec["id"]).status == "OPEN"
    v = current_version(db, doc["id"])
    assert (v.s3_version_id, v.storage_class) == (old, "STANDARD") and doc_row(db, doc["id"]).pending_op is None
    assert [e.version_id for e in store_entries(db, doc["id"])] == [old]

    app.dependency_overrides.pop(get_storage)
    assert apply(client, alice, rec["id"]).status_code == 200  # a retry succeeds
    assert_applied(db, doc["id"], "STANDARD_IA", old)


def test_source_missing_from_store(client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    v = current_version(db, doc["id"])
    get_storage().delete_version(doc_row(db, doc["id"]).s3_key, v.s3_version_id)
    assert error(apply(client, alice, rec["id"])) == (410, "VERSION_EXPIRED")
    assert current_version(db, doc["id"]).state == "S3_MISSING"
    assert rec_row(db, rec["id"]).status == "STALE" and doc_row(db, doc["id"]).pending_op is None
    assert store_entries(db, doc["id"]) == []  # nothing recreated


# ---- recovery states A-D ----

def test_state_b_finalize_failure_rolls_forward_on_retry(client, alice, cold, db, monkeypatch):
    doc = cold()
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"]).s3_version_id
    fail_once(monkeypatch, recommendation_service, "finalize_apply")
    assert error(apply(client, alice, rec["id"])) == (503, "DB_UNAVAILABLE")
    assert doc_row(db, doc["id"]).pending_op == "APPLY"
    assert current_version(db, doc["id"]).s3_version_id == old  # app still on the old version
    assert len(store_entries(db, doc["id"])) == 2  # copy exists, not adopted

    r = apply(client, alice, rec["id"])  # recovery adopts the copy, then: already applied
    assert r.status_code == 200 and r.json()["status"] == "APPLIED"
    assert_applied(db, doc["id"], "STANDARD_IA", old)


def test_state_b_recovered_by_a_delete(client, alice, cold, db, monkeypatch):
    doc = cold()
    rec = one_rec(client, alice)
    fail_once(monkeypatch, recommendation_service, "finalize_apply")
    apply(client, alice, rec["id"])
    assert client.delete(f"/api/documents/{doc['id']}", headers=alice).status_code == 204
    v = current_version(db, doc["id"])
    assert v.storage_class == "STANDARD_IA" and rec_row(db, rec["id"]).status == "APPLIED"
    entries = store_entries(db, doc["id"])
    assert [e.is_delete_marker for e in entries] == [True, False]  # marker on top of the adopted copy
    assert entries[1].version_id == v.s3_version_id and doc_row(db, doc["id"]).pending_op is None


def test_state_c_old_version_cleanup_failure(app, client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"]).s3_version_id
    app.dependency_overrides[get_storage] = lambda: StorageWrapper(delete_version=storage_error)
    r = apply(client, alice, rec["id"])
    assert r.status_code == 200 and r.json()["status"] == "APPLIED"  # the change took effect
    assert doc_row(db, doc["id"]).pending_op == "APPLY"
    assert old in [e.version_id for e in store_entries(db, doc["id"])]  # still stored, unreferenced

    app.dependency_overrides.pop(get_storage)
    assert apply(client, alice, rec["id"]).status_code == 200  # recovery removes the old version
    assert_applied(db, doc["id"], "STANDARD_IA", old)


def test_state_d_intent_not_cleared(client, alice, cold, db, monkeypatch):
    doc = cold()
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"]).s3_version_id
    fail_once(monkeypatch, recommendation_service, "clear_apply_intent")
    assert apply(client, alice, rec["id"]).status_code == 200
    assert doc_row(db, doc["id"]).pending_op == "APPLY"
    assert len(store_entries(db, doc["id"])) == 1  # old version already gone

    files = {"file": ("cold.txt", b"n" * BIG, "application/octet-stream")}  # any operation recovers
    assert client.post(f"/api/documents/{doc['id']}/versions", headers=alice, files=files).status_code == 201
    assert doc_row(db, doc["id"]).pending_op is None
    v1 = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(doc["id"]),
                                                 DocumentVersion.version_number == 1))
    assert v1.storage_class == "STANDARD_IA" and v1.s3_version_id != old


def test_state_a_intent_without_copy_is_dropped(client, alice, cold, db):
    doc = cold()
    rec = one_rec(client, alice)
    old = current_version(db, doc["id"]).s3_version_id
    d = doc_row(db, doc["id"])
    d.pending_op, d.pending_op_at = "APPLY", datetime.now(UTC)
    db.commit()
    assert apply(client, alice, rec["id"]).status_code == 200  # intent dropped, then a normal Apply
    assert_applied(db, doc["id"], "STANDARD_IA", old)


def test_recovery_never_adopts_an_object_older_than_the_intent(client, alice, cold, db):
    """A stray copy written before pending_op_at (same bytes, same class) is not taken for the Apply's copy."""
    doc = cold()
    rec = one_rec(client, alice)
    d, v = doc_row(db, doc["id"]), current_version(db, doc["id"])
    stray = get_storage().copy_object(d.s3_key, v.s3_version_id, storage_class="STANDARD_IA").version_id
    d = doc_row(db, doc["id"])
    d.pending_op, d.pending_op_at = "APPLY", datetime.now(UTC) + timedelta(seconds=1)
    db.commit()
    assert apply(client, alice, rec["id"]).status_code == 200
    v = current_version(db, doc["id"])
    assert v.storage_class == "STANDARD_IA" and v.s3_version_id != stray
    assert v.s3_version_id == store_entries(db, doc["id"])[0].version_id  # the Apply's own copy is current
    assert doc_row(db, doc["id"]).pending_op is None
