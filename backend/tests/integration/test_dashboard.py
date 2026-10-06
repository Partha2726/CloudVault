"""T15: GET /api/dashboard/summary (doc 05.5). Owner-scoped; ACTIVE documents and ACTIVE versions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from tests.conftest import PDF_BYTES
from tests.integration.test_recommendations import BIG, add_access, doc_row, one_rec

EMPTY = {
    "document_count": 0, "current_bytes": 0, "total_bytes_all_versions": 0, "accesses_30d": 0,
    "bytes_by_class": {"STANDARD": 0, "STANDARD_IA": 0, "GLACIER_IR": 0},
    "open_recommendations": 0,
    "jobs_by_status": {"PENDING": 0, "SUCCEEDED": 0, "FAILED": 0, "SKIPPED": 0},
}


def summary(client, headers):
    r = client.get("/api/dashboard/summary", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_empty_account(client, alice):
    assert summary(client, alice) == EMPTY


def test_requires_login(client):
    assert client.get("/api/dashboard/summary").status_code == 401


def test_totals_versions_accesses_and_jobs(client, upload, alice, db):
    a = upload(alice, "a.pdf").json()
    upload(alice, "b.txt", b"b" * 100)
    files = {"file": ("a.pdf", PDF_BYTES + b"v2", "application/octet-stream")}
    client.post(f"/api/documents/{a['id']}/versions", headers=alice, files=files)
    client.get(f"/api/documents/{a['id']}/download", headers=alice)
    owner = doc_row(db, a["id"]).owner_id
    add_access(db, a["id"], owner, days_ago=45)  # outside the 30-day window
    db.execute(text("UPDATE processing_jobs SET status='SUCCEEDED', finished_at=now() WHERE document_id=:d"),
               {"d": a["id"]})
    db.commit()

    s = summary(client, alice)
    v1, v2, b = len(PDF_BYTES), len(PDF_BYTES) + 2, 100
    assert s["document_count"] == 2
    assert s["current_bytes"] == v2 + b
    assert s["total_bytes_all_versions"] == v1 + v2 + b
    assert s["bytes_by_class"] == {"STANDARD": v1 + v2 + b, "STANDARD_IA": 0, "GLACIER_IR": 0}
    assert s["accesses_30d"] == 1
    assert s["jobs_by_status"] == {"PENDING": 1, "SUCCEEDED": 2, "FAILED": 0, "SKIPPED": 0}


def test_classes_and_open_recommendations(client, alice, cold, db):
    cold("ia.txt", fill=b"i")
    cold("gir.txt", rule="R2", fill=b"g")
    recs = {r["display_name"]: r for r in client.post("/api/recommendations/refresh", headers=alice).json()["items"]}
    assert summary(client, alice)["open_recommendations"] == 2
    client.post(f"/api/recommendations/{recs['ia.txt']['id']}/apply", headers=alice)
    client.post(f"/api/recommendations/{recs['gir.txt']['id']}/apply", headers=alice)
    s = summary(client, alice)
    assert s["bytes_by_class"] == {"STANDARD": 0, "STANDARD_IA": BIG, "GLACIER_IR": BIG}
    assert s["open_recommendations"] == 0 and s["total_bytes_all_versions"] == 2 * BIG


def test_excludes_trashed_failed_missing_and_other_users(client, upload, alice, auth_headers, db):
    bob = auth_headers("bob@example.com")
    keep = upload(alice, "keep.pdf").json()
    trashed = upload(alice, "trash.txt", b"t" * 50).json()
    missing = upload(alice, "missing.txt", b"m" * 70).json()
    upload(bob, "bobs.txt", b"x" * 999)
    client.delete(f"/api/documents/{trashed['id']}", headers=alice)
    client.get(f"/api/documents/{trashed['id']}/access-logs", headers=alice)
    db.execute(text("UPDATE document_versions SET state='S3_MISSING' WHERE document_id=:d"), {"d": missing["id"]})
    db.execute(text("INSERT INTO access_logs (document_id, version_id, user_id, accessed_at) "
                    "SELECT d.id, d.current_version_id, d.owner_id, :t FROM documents d WHERE d.id=:d"),
               {"d": trashed["id"], "t": datetime.now(UTC) - timedelta(days=1)})
    db.commit()
    s = summary(client, alice)
    assert s["document_count"] == 2  # keep + missing (still ACTIVE)
    assert s["current_bytes"] == len(PDF_BYTES)  # the S3_MISSING version is no longer stored
    assert s["total_bytes_all_versions"] == len(PDF_BYTES)
    assert s["accesses_30d"] == 0
    assert s["jobs_by_status"]["PENDING"] == 1
    assert keep["id"]


def test_engine_open_recommendation_count_only_for_active(client, alice, cold):
    doc = cold()
    one_rec(client, alice)
    client.delete(f"/api/documents/{doc['id']}", headers=alice)
    assert summary(client, alice)["open_recommendations"] == 0
