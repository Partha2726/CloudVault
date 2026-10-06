"""T9: download links (W3), the signed simulated-S3 route (AM-7) and the access log (W9).

The signed URL is the credential: the route authorizes only from the verified signature,
expiry and bound resource, never from the caller's login state.
"""

import uuid
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal
from app.models import AccessLog, Document, DocumentVersion
from app.routers import sim_s3
from app.services import document_service
from app.storage import get_storage
from tests.conftest import PDF_BYTES


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
    return upload(alice, "Quarterly résumé.pdf").json()


def link(client, headers, doc_id, **params):
    r = client.get(f"/api/documents/{doc_id}/download", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def fetch(client, url, headers=None):
    """Request a signed URL through the test client (path + query only)."""
    parts = urlsplit(url)
    return client.get(urlunsplit(("", "", parts.path, parts.query, "")), headers=headers or {})


def with_query(url, **changes):
    parts = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    q.update(changes)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


def add_version(db, doc_id, content):
    """Store a second version directly (T11 owns the API for this)."""
    row = db.get(Document, uuid.UUID(doc_id))
    stored = get_storage().put_object(row.s3_key, content, content_type="application/pdf")
    version = DocumentVersion(
        document_id=row.id, version_number=2, s3_version_id=stored.version_id, size_bytes=len(content),
        content_type="application/pdf", sha256="b" * 64, state="ACTIVE",
    )
    db.add(version)
    db.flush()
    row.current_version_id = version.id
    db.commit()
    return stored.version_id


# ---- link issuing ----

def test_i9_download_logs_one_access(client, alice, doc, db):
    body = link(client, alice, doc["id"])
    assert body["expires_in"] == 120
    url = urlsplit(body["url"])
    assert (url.scheme, url.netloc) == ("http", "localhost:8000")  # PUBLIC_API_BASE_URL
    assert url.path.startswith("/api/sim-s3/cloudvault-sim/documents/")
    logs = db.scalars(select(AccessLog)).all()
    assert len(logs) == 1 and logs[0].event_type == "DOWNLOAD"
    assert str(logs[0].document_id) == doc["id"]


def test_access_log_is_committed_before_the_response(client, alice, doc):
    link(client, alice, doc["id"])
    with SessionLocal() as other:  # separate connection: sees only committed rows
        assert other.scalar(select(AccessLog.id).limit(1)) is not None


def test_link_refused_if_access_log_cannot_be_written(client, alice, doc, monkeypatch):
    def failing_record(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(document_service, "record_access", failing_record)
    r = client.get(f"/api/documents/{doc['id']}/download", headers=alice)
    assert error(r) == (503, "DB_UNAVAILABLE")
    assert "url" not in r.text


def test_issuing_a_link_makes_no_storage_call(app, client, alice, doc):
    class NoCallsStorage:
        bucket = "cloudvault-sim"

        def __getattr__(self, name):
            raise AssertionError(f"storage.{name} called while issuing a link")

    app.dependency_overrides[get_storage] = lambda: NoCallsStorage()
    assert link(client, alice, doc["id"])["url"]


def test_each_link_request_is_logged(client, alice, doc, db):
    link(client, alice, doc["id"])
    link(client, alice, doc["id"])
    assert db.query(AccessLog).count() == 2


def test_other_users_document_is_404(client, bob, doc, db):
    assert error(client.get(f"/api/documents/{doc['id']}/download", headers=bob)) == (404, "NOT_FOUND")
    assert db.query(AccessLog).count() == 0


def test_link_requires_login(client, doc):
    assert error(client.get(f"/api/documents/{doc['id']}/download")) == (401, "UNAUTHORIZED")


def test_deleted_document_cannot_get_a_link(client, alice, doc, db):
    db.execute(text("UPDATE documents SET status='DELETED', deleted_at=now(), delete_marker_version_id='m' "
                    "WHERE id=:d"), {"d": doc["id"]})
    db.commit()
    assert error(client.get(f"/api/documents/{doc['id']}/download", headers=alice)) == (409, "DOCUMENT_DELETED")
    assert db.query(AccessLog).count() == 0


def test_missing_version_number_is_404(client, alice, doc):
    r = client.get(f"/api/documents/{doc['id']}/download", headers=alice, params={"version": 7})
    assert error(r) == (404, "VERSION_NOT_FOUND")


@pytest.mark.parametrize("status", ["PENDING", "FAILED"])
def test_unfinished_documents_are_not_downloadable(client, alice, doc, db, status):
    """AM-9: an unfinished upload is a PENDING/FAILED document with no version row; it is 404."""
    row = db.get(Document, uuid.UUID(doc["id"]))
    unfinished = Document(owner_id=row.owner_id, display_name=f"{status}.pdf", s3_key=f"documents/x/{status}",
                          status=status)
    db.add(unfinished)
    db.commit()
    assert error(client.get(f"/api/documents/{unfinished.id}/download", headers=alice)) == (404, "NOT_FOUND")
    assert db.query(AccessLog).count() == 0


def test_s3_missing_version_is_410(client, alice, doc, db):
    db.execute(text("UPDATE document_versions SET state='S3_MISSING' WHERE document_id=:d"), {"d": doc["id"]})
    db.commit()
    assert error(client.get(f"/api/documents/{doc['id']}/download", headers=alice)) == (410, "VERSION_EXPIRED")
    assert db.query(AccessLog).count() == 0


def test_bad_version_parameter(client, alice, doc):
    r = client.get(f"/api/documents/{doc['id']}/download", headers=alice, params={"version": 0})
    assert error(r) == (422, "VALIDATION_ERROR")


# ---- signed route ----

def test_valid_signed_download_without_login(app, client, alice, doc):
    url = link(client, alice, doc["id"])["url"]
    r = fetch(TestClient(app), url)  # fresh client, no Authorization header
    assert r.status_code == 200
    assert r.content == PDF_BYTES
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == (
        "attachment; filename=\"Quarterly r_sum_.pdf\"; filename*=UTF-8''Quarterly%20r%C3%A9sum%C3%A9.pdf"
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in r.headers["cache-control"]


@pytest.mark.parametrize(
    "headers",
    [{"Authorization": "Bearer not-a-real-token"}, {"Authorization": "Basic x"}],
)
def test_signed_route_ignores_authorization_headers(client, alice, doc, headers):
    url = link(client, alice, doc["id"])["url"]
    assert fetch(client, url, headers).status_code == 200


def test_another_users_session_cannot_unlock_an_invalid_link(client, alice, bob, doc):
    url = link(client, alice, doc["id"])["url"]
    tampered = with_query(url, signature="A" * 43)
    assert error(fetch(client, tampered, alice)) == (403, "ACCESS_DENIED")
    assert error(fetch(client, tampered, bob)) == (403, "ACCESS_DENIED")


def test_expired_link_is_403(client, alice, doc, monkeypatch):
    url = link(client, alice, doc["id"])["url"]
    issued_until = int(parse_qs(urlsplit(url).query)["expires"][0])
    monkeypatch.setattr(sim_s3, "epoch_now", lambda: issued_until)
    assert fetch(client, url).status_code == 200  # still valid at the expiry second
    monkeypatch.setattr(sim_s3, "epoch_now", lambda: issued_until + 1)
    assert error(fetch(client, url)) == (403, "ACCESS_DENIED")


@pytest.mark.parametrize(
    "change",
    [
        {"signature": "A" * 43},
        {"filename": "evil.html"},
        {"expires": "9999999999"},
        {"versionId": "someone-elses-version"},
    ],
)
def test_tampered_link_is_403(client, alice, doc, change):
    url = link(client, alice, doc["id"])["url"]
    assert error(fetch(client, with_query(url, **change))) == (403, "ACCESS_DENIED")


@pytest.mark.parametrize("drop", ["signature", "expires", "versionId", "filename"])
def test_incomplete_link_is_403(client, alice, doc, drop):
    url = link(client, alice, doc["id"])["url"]
    parts = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(parts.query).items() if k != drop}
    assert error(fetch(client, urlunsplit(("", "", parts.path, urlencode(q), "")))) == (403, "ACCESS_DENIED")


def test_l3_encoded_characters_in_names_never_reach_the_key(client, alice, upload, db):
    """L3 as amended by AM-7: no S3 event keys to decode. Keys are generated, so `+`, `%20` and
    spaces in a filename stay in the display name and survive the signed link unchanged."""
    name = "Q1+Q2 report%20final.pdf"
    doc = upload(alice, name).json()
    assert doc["display_name"] == name
    row = db.get(Document, uuid.UUID(doc["id"]))
    assert row.s3_key == f"documents/{row.owner_id}/{row.id}"
    r = fetch(client, link(client, alice, doc["id"])["url"])
    assert r.status_code == 200 and r.content == PDF_BYTES
    assert r.headers["content-disposition"].endswith("filename*=UTF-8''Q1%2BQ2%20report%2520final.pdf")


def test_link_cannot_be_moved_to_another_key_or_bucket(client, alice, doc, upload):
    other = upload(alice, "other.pdf", PDF_BYTES + b"other").json()
    url = link(client, alice, doc["id"])["url"]
    other_url = link(client, alice, other["id"])["url"]
    other_path = urlsplit(other_url).path
    moved = urlunsplit(("", "", other_path, urlsplit(url).query, ""))
    assert error(fetch(client, moved)) == (403, "ACCESS_DENIED")
    wrong_bucket = urlunsplit(("", "", urlsplit(url).path.replace("cloudvault-sim", "other-bucket", 1),
                               urlsplit(url).query, ""))
    assert error(fetch(client, wrong_bucket)) == (403, "ACCESS_DENIED")


def test_version_binding(client, alice, doc, db):
    """A link for v1 serves v1 even after v2 exists, and cannot be re-pointed at v2."""
    v1_url = link(client, alice, doc["id"], version=1)["url"]
    v2_store_id = add_version(db, doc["id"], PDF_BYTES + b"v2")
    assert fetch(client, v1_url).content == PDF_BYTES
    assert error(fetch(client, with_query(v1_url, versionId=v2_store_id))) == (403, "ACCESS_DENIED")
    v2 = fetch(client, link(client, alice, doc["id"])["url"])
    assert v2.content == PDF_BYTES + b"v2"


def test_signed_version_gone_from_store_is_404(client, alice, doc, db):
    url = link(client, alice, doc["id"])["url"]
    row = db.get(Document, uuid.UUID(doc["id"]))
    get_storage().delete_all_versions(row.s3_key)
    assert error(fetch(client, url)) == (404, "NOT_FOUND")


# ---- access log listing ----

def test_access_log_listing(client, alice, doc, db):
    link(client, alice, doc["id"])
    add_version(db, doc["id"], PDF_BYTES + b"v2")
    link(client, alice, doc["id"])
    link(client, alice, doc["id"], version=1)
    body = client.get(f"/api/documents/{doc['id']}/access-logs", headers=alice).json()
    assert body["total"] == 3 and (body["page"], body["page_size"]) == (1, 25)
    assert [(i["version_number"], i["event_type"]) for i in body["items"]] == [
        (1, "DOWNLOAD"), (2, "DOWNLOAD"), (1, "DOWNLOAD"),  # newest first
    ]
    assert set(body["items"][0]) == {"accessed_at", "version_number", "event_type"}
    page2 = client.get(f"/api/documents/{doc['id']}/access-logs", headers=alice,
                       params={"page": 2, "page_size": 2}).json()
    assert len(page2["items"]) == 1 and page2["total"] == 3


def test_access_log_visible_for_trashed_document(client, alice, doc, db):
    link(client, alice, doc["id"])
    db.execute(text("UPDATE documents SET status='DELETED', deleted_at=now(), delete_marker_version_id='m' "
                    "WHERE id=:d"), {"d": doc["id"]})
    db.commit()
    assert client.get(f"/api/documents/{doc['id']}/access-logs", headers=alice).json()["total"] == 1


def test_access_log_is_owner_scoped(client, alice, bob, doc):
    link(client, alice, doc["id"])
    assert error(client.get(f"/api/documents/{doc['id']}/access-logs", headers=bob)) == (404, "NOT_FOUND")
    assert error(client.get(f"/api/documents/{doc['id']}/access-logs")) == (401, "UNAUTHORIZED")
