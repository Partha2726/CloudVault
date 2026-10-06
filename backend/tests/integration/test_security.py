"""T24 security pass: tests S1-S5 (doc 10.2, as amended by doc 15 AM-7) and the hardening checks.

S1 owner scoping (404, never 403, indistinguishable from a missing id), S2 no token, S3
expired signed link, S4 no internal endpoint (AM-7 removed it), S5 login brute force; plus
CORS, security headers, body caps, error hygiene, JWT edge cases, signed-route abuse and
sensitive logging.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, quote, unquote, urlsplit

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.config import get_settings
from app.http_hardening import NON_UPLOAD_BODY_LIMIT, RedactQueryStrings, SecurityHeadersMiddleware
from app.models import AccessLog, Document, DocumentVersion, StorageRecommendation
from app.routers import sim_s3
from app.services import document_service
from tests.conftest import PDF_BYTES
from tests.integration.test_download import fetch, link, with_query

ORIGIN = "http://localhost:5173"
PUBLIC_ROUTES = {
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/health"),
    ("GET", "/api/sim-s3/{bucket}/{key}"),  # authorized by its signature, not a login (AM-7)
}


def error(r):
    return r.status_code, r.json()["error"]["code"]


@pytest.fixture
def bob(auth_headers):
    return auth_headers("bob@example.com")


@pytest.fixture
def victim(client, upload, alice, cold, db):
    """Alice's document with two versions, an access-log row and an OPEN recommendation."""
    doc = upload(alice, "secret-plans.pdf").json()
    files = {"file": ("secret-plans.pdf", PDF_BYTES + b"v2", "application/octet-stream")}
    assert client.post(f"/api/documents/{doc['id']}/versions", headers=alice, files=files).status_code == 201
    link(client, alice, doc["id"])
    cold("cold.txt", rule="R3")
    recs = client.post("/api/recommendations/refresh", headers=alice).json()["items"]
    assert len(recs) == 1
    return {"doc": doc["id"], "rec": recs[0]["id"]}


def snapshot(db, doc_id):
    db.expire_all()
    d = db.get(Document, uuid.UUID(doc_id))
    return (
        d.status,
        d.current_version_id,
        db.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == d.id)),
        db.scalar(select(func.count()).select_from(AccessLog).where(AccessLog.document_id == d.id)),
        tuple(db.scalars(select(StorageRecommendation.status).order_by(StorageRecommendation.id))),
    )


# Every owner-scoped operation on a document, with a well-formed request.
def _file():
    return {"file": ("secret-plans.pdf", PDF_BYTES + b"bob", "application/octet-stream")}


DOC_OPERATIONS = [
    ("GET", "/api/documents/{id}", {}),
    ("GET", "/api/documents/{id}/versions", {}),
    ("POST", "/api/documents/{id}/versions", {"files": "file"}),
    ("POST", "/api/documents/{id}/versions/1/restore", {}),
    ("GET", "/api/documents/{id}/download", {}),
    ("GET", "/api/documents/{id}/download?version=1", {}),
    ("GET", "/api/documents/{id}/access-logs", {}),
    ("GET", "/api/documents/{id}/s3-info", {}),
    ("GET", "/api/documents/{id}/s3-info?version=1", {}),
    ("GET", "/api/documents/{id}/processing", {}),
    ("POST", "/api/documents/{id}/processing/retry", {}),
    ("POST", "/api/documents/{id}/processing/retry?version=1", {}),
    ("DELETE", "/api/documents/{id}", {}),
    ("POST", "/api/documents/{id}/undelete", {}),
    ("DELETE", "/api/documents/{id}/permanent?confirm=true", {}),
]


def call(client, method, path, headers, extra):
    kwargs = {"headers": headers}
    if extra.get("files"):
        kwargs["files"] = _file()
    return client.request(method, path, **kwargs)


# ---- S1: owner scoping ----

@pytest.mark.parametrize(("method", "path", "extra"), DOC_OPERATIONS, ids=[f"{m} {p}" for m, p, _ in DOC_OPERATIONS])
def test_s1_other_users_document_is_indistinguishable_from_a_missing_one(client, bob, victim, db, method, path, extra):
    before = snapshot(db, victim["doc"])
    theirs = call(client, method, path.format(id=victim["doc"]), bob, extra)
    missing = call(client, method, path.format(id=uuid.uuid4()), bob, extra)
    assert theirs.status_code == 404, theirs.text
    assert (theirs.status_code, theirs.json()) == (missing.status_code, missing.json())
    assert snapshot(db, victim["doc"]) == before  # nothing changed for Alice


def test_s1_trashed_document_stays_hidden(client, alice, bob, victim, db):
    """Alice would get 409 for these; Bob must not learn that the document exists or its state."""
    assert client.delete(f"/api/documents/{victim['doc']}", headers=alice).status_code == 204
    for method, path, extra in DOC_OPERATIONS:
        theirs = call(client, method, path.format(id=victim["doc"]), bob, extra)
        missing = call(client, method, path.format(id=uuid.uuid4()), bob, extra)
        assert (theirs.status_code, theirs.json()) == (missing.status_code, missing.json()), path
        assert theirs.status_code == 404


@pytest.mark.parametrize("action", ["apply", "dismiss"])
def test_s1_other_users_recommendation_is_404(client, bob, victim, db, action):
    before = snapshot(db, victim["doc"])
    theirs = client.post(f"/api/recommendations/{victim['rec']}/{action}", headers=bob)
    missing = client.post(f"/api/recommendations/{uuid.uuid4()}/{action}", headers=bob)
    assert error(theirs) == (404, "NOT_FOUND")
    assert theirs.json() == missing.json()
    assert snapshot(db, victim["doc"]) == before


def test_s1_lists_and_totals_show_only_own_data(client, bob, victim):
    assert client.get("/api/documents", headers=bob).json()["total"] == 0
    assert client.get("/api/documents?status=deleted", headers=bob).json()["total"] == 0
    for status in ("open", "applied", "dismissed", "stale"):
        assert client.get(f"/api/recommendations?status={status}", headers=bob).json()["items"] == []
    assert client.post("/api/recommendations/refresh", headers=bob).json()["items"] == []
    summary = client.get("/api/dashboard/summary", headers=bob).json()
    assert (summary["document_count"], summary["total_bytes_all_versions"], summary["accesses_30d"]) == (0, 0, 0)
    assert summary["open_recommendations"] == 0


def test_s1_signed_link_for_alice_does_not_open_bobs_object(client, alice, bob, upload):
    """A valid signature is bound to its key: it cannot be replayed against another user's object."""
    mine = upload(alice, "mine.pdf").json()
    theirs = upload(bob, "theirs.pdf", PDF_BYTES + b"bob").json()
    url = link(client, alice, mine["id"])["url"]
    bob_path = urlsplit(link(client, bob, theirs["id"])["url"]).path
    assert error(client.get(f"{bob_path}?{urlsplit(url).query}")) == (403, "ACCESS_DENIED")


def test_s1_client_identity_fields_are_ignored(client, alice, bob, victim):
    """Owner comes only from the verified token; extra query/body identity fields change nothing."""
    alice_id = client.get("/api/auth/me", headers=alice).json()["id"]
    r = client.get(f"/api/documents/{victim['doc']}?owner_id={alice_id}&user_id={alice_id}", headers=bob)
    assert error(r) == (404, "NOT_FOUND")
    r = client.get("/api/documents", headers={**bob, "X-User-Id": alice_id})
    assert r.json()["total"] == 0


# ---- S2: no token on every protected route ----

def protected_routes(app):
    """Every API operation, read from the OpenAPI schema so a new route cannot be missed."""
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if (method.upper(), path) not in PUBLIC_ROUTES:
                yield method.upper(), path


def fill(path):
    return (
        path.replace("{document_id}", str(uuid.uuid4()))
        .replace("{recommendation_id}", str(uuid.uuid4()))
        .replace("{version_number}", "1")
    )


def test_s2_every_protected_route_requires_a_token(app, client):
    routes = sorted(protected_routes(app))
    assert len(routes) >= 19  # all document, version, recommendation, dashboard and /me routes
    for method, path in routes:
        r = client.request(method, fill(path))
        assert error(r) == (401, "UNAUTHORIZED"), (method, path)


@pytest.mark.parametrize(
    "where",
    [
        {"params": {"access_token": "TOKEN"}},
        {"params": {"token": "TOKEN"}},
        {"cookies": {"access_token": "TOKEN"}},
        {"headers": {"X-Access-Token": "TOKEN"}},
        {"headers": {"Authorization": "TOKEN"}},  # no scheme
        {"headers": {"Authorization": "Basic TOKEN"}},
    ],
)
def test_s2_token_only_accepted_as_bearer_header(client, alice, where):
    token = alice["Authorization"].split()[1]
    kwargs = {k: {kk: vv.replace("TOKEN", token) for kk, vv in v.items()} for k, v in where.items()}
    if "cookies" in kwargs:
        client.cookies.update(kwargs.pop("cookies"))
    assert error(client.get("/api/documents", **kwargs)) == (401, "UNAUTHORIZED")


def test_s2_unauthenticated_upload_is_refused_before_size_checks(client):
    big = {"file": ("big.txt", b"a" * (11 * 1024 * 1024), "application/octet-stream")}
    assert error(client.post("/api/documents", files=big)) == (401, "UNAUTHORIZED")


# ---- JWT edge cases (S2 continued) ----

def _token(claims, secret=None, algorithm="HS256"):
    return jwt.encode(claims, secret or get_settings().jwt_secret, algorithm=algorithm)


def _claims(sub, **over):
    now = datetime.now(UTC)
    return {"sub": sub, "iat": now, "exp": now + timedelta(minutes=5), **over}


@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")  # the HS512 attack token
def test_jwt_algorithm_is_pinned_and_secrets_are_not_interchangeable(client, alice):
    sub = client.get("/api/auth/me", headers=alice).json()["id"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {_token(_claims(sub))}"}).status_code == 200
    for bad in (
        _token(_claims(sub), algorithm="HS512"),  # right secret, other algorithm
        _token(_claims(sub), secret=get_settings().sim_signing_secret),  # the download-link key
        _token(_claims(sub, exp=datetime.now(UTC) - timedelta(seconds=1))),
        _token({k: v for k, v in _claims(sub).items() if k != "iat"}),
        _token({k: v for k, v in _claims(sub).items() if k != "sub"}),
        _token(_claims(sub))[:-2] + "xx",  # tampered signature
        "a.b.c",
        "",
    ):
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert error(r) == (401, "UNAUTHORIZED")


def test_jwt_extra_identity_claims_are_ignored(client, alice, bob):
    alice_me = client.get("/api/auth/me", headers=alice).json()
    bob_id = client.get("/api/auth/me", headers=bob).json()["id"]
    forged = _token(_claims(alice_me["id"], email="bob@example.com", user_id=bob_id, owner_id=bob_id))
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.json() == alice_me


def test_auth_errors_never_reveal_why(client, register):
    register("carol@example.com", "correct horse")
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "correct horse"})
    wrong = client.post("/api/auth/login", json={"email": "carol@example.com", "password": "wrong horse!"})
    assert unknown.json() == wrong.json()
    bad_sig = client.get("/api/auth/me", headers={"Authorization": "Bearer a.b.c"}).json()
    unknown_user = _token(_claims(str(uuid.uuid4())))
    expired = client.get("/api/auth/me", headers={"Authorization": f"Bearer {unknown_user}"}).json()
    assert bad_sig == expired  # forged and unknown-user tokens look the same


# ---- S3: expired signed link, and signed-route abuse ----

def test_s3_expired_link_is_denied_and_cannot_be_replayed(client, alice, upload, monkeypatch):
    doc = upload(alice, "a.pdf").json()
    url = link(client, alice, doc["id"])["url"]
    expires = int(parse_qs(urlsplit(url).query)["expires"][0])
    assert expires - sim_s3.epoch_now() <= get_settings().presign_expiry_seconds
    monkeypatch.setattr(sim_s3, "epoch_now", lambda: expires + 121)  # "wait over 120 s"
    assert error(fetch(client, url)) == (403, "ACCESS_DENIED")
    later = str(expires + 3600)
    assert error(fetch(client, with_query(url, expires=later))) == (403, "ACCESS_DENIED")  # cannot extend


@pytest.mark.parametrize(
    "change",
    [
        {"expires": "9" * 5000},  # beyond int() string limits: must not become a 500
        {"expires": "١٢٣٤٥٦٧٨٩٠"},  # non-ASCII digits
        {"expires": "-1"},
        {"expires": " 1"},
        {"signature": "é" * 43},  # non-ASCII signature: must not become a 500
        {"signature": "\x00" * 43},
        {"signature": "A" * 100_00},
        {"versionId": "../" * 20},
        {"filename": "../../etc/passwd"},
        {"filename": "x\r\nSet-Cookie: a=b"},
    ],
)
def test_signed_route_rejects_hostile_parameters_with_403(client, alice, upload, change):
    doc = upload(alice, "a.pdf").json()
    url = link(client, alice, doc["id"])["url"]
    assert error(fetch(client, with_query(url, **change))) == (403, "ACCESS_DENIED")


def test_signed_route_accepts_only_the_canonical_expiry(client, alice, upload):
    doc = upload(alice, "a.pdf").json()
    url = link(client, alice, doc["id"])["url"]
    expires = parse_qs(urlsplit(url).query)["expires"][0]
    assert fetch(client, url).status_code == 200
    assert error(fetch(client, with_query(url, expires="0" + expires))) == (403, "ACCESS_DENIED")


def test_repeated_query_parameters_cannot_swap_the_signed_value(client, alice, upload):
    doc = upload(alice, "a.pdf").json()
    url = link(client, alice, doc["id"])["url"]
    parts = urlsplit(url)
    for extra in ("versionId=other", "filename=evil.html", "expires=9999999999"):
        r = client.get(f"{parts.path}?{parts.query}&{extra}")
        assert error(r) == (403, "ACCESS_DENIED")


def raw_get(app, path, query):
    """Send an exact path through the ASGI app (HTTP clients normalize dot segments first)."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": unquote(path), "raw_path": path.encode(), "query_string": query.encode(), "root_path": "",
        "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 1), "server": ("testserver", 80),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_signed_route_path_manipulation(app, client, alice, upload):
    doc = upload(alice, "a.pdf").json()
    other = upload(alice, "b.pdf", PDF_BYTES + b"b").json()
    url = urlsplit(link(client, alice, doc["id"])["url"])
    other_key = unquote(urlsplit(link(client, alice, other["id"])["url"]).path).split("/cloudvault-sim/", 1)[1]
    key = unquote(url.path).split("/cloudvault-sim/", 1)[1]
    prefix = "/api/sim-s3/cloudvault-sim/"
    assert raw_get(app, url.path, url.query) == 200
    hostile = [
        prefix + key.replace("documents/", "documents/../documents/", 1),
        prefix + key.replace("documents/", "documents/./", 1),
        prefix + key.replace("documents/", "documents//", 1),
        prefix + key.replace("documents/", "documents/..%2Fdocuments/", 1),
        prefix + key.replace("documents/", "documents%2F..%2Fdocuments/", 1),
        prefix + "../" + key,
        prefix + key + "/",
        prefix + key + "%00",
        prefix + key + "/../" + other_key.rsplit("/", 1)[1],
        prefix + other_key,  # same owner, other object: signature is bound to the key
        "/api/sim-s3/cloudvault-sim%2F.." + "/" + key,
        "/api/sim-s3/other-bucket/" + key,
        "/api/sim-s3/CLOUDVAULT-SIM/" + key,
    ]
    for path in hostile:
        assert raw_get(app, path, url.query) in (403, 404), path
    # Percent-encoding the same characters is the same signed key, never a different object.
    same = prefix + quote(key, safe="").replace("%2F", "/").replace("d", "%64", 1)
    assert raw_get(app, same, url.query) == 200


def test_signed_route_response_is_safe_to_receive(client, alice, upload):
    doc = upload(alice, 'evil"\r\nX-Injected: 1.txt', b"hello").json()
    r = fetch(client, link(client, alice, doc["id"])["url"])
    assert r.status_code == 200
    assert "x-injected" not in r.headers
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"  # the route's own value is kept
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


# ---- S4: the internal endpoint no longer exists (AM-7) ----

@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer x"}, {"X-Internal-Token": "x"}])
def test_s4_no_internal_processing_endpoint(app, client, headers):
    assert not [r.path for r in app.routes if "internal" in getattr(r, "path", "")]
    r = client.post("/api/internal/processing-results", headers=headers, json={"job": "x"})
    assert error(r) == (404, "NOT_FOUND")


# ---- S5: rate limits ----

def test_s5_login_limit_is_per_client_not_per_email(client, register):
    register("dave@example.com", "correct horse")
    for i in range(5):
        r = client.post("/api/auth/login", json={"email": f"guess{i}@example.com", "password": "wrong horse!"})
        assert r.status_code == 401
    blocked = client.post("/api/auth/login", json={"email": "dave@example.com", "password": "correct horse"})
    assert error(blocked) == (429, "RATE_LIMITED")
    assert blocked.json()["error"]["message"] == "Too many requests; try again later"


def test_s5_login_limit_does_not_block_signed_in_users(client, alice):
    for _ in range(6):
        client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong horse!"})
    assert client.get("/api/documents", headers=alice).status_code == 200


# ---- CORS ----

def test_cors_preflight_allows_only_the_frontend_origin(client):
    def preflight(origin, method="GET", headers="authorization"):
        return client.options(
            "/api/documents",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": headers,
            },
        )

    ok = preflight(ORIGIN, "POST", "authorization,content-type")
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert set(ok.headers["access-control-allow-methods"].replace(" ", "").split(",")) == {"GET", "POST", "DELETE"}
    assert "access-control-allow-credentials" not in ok.headers  # bearer tokens, no cookies
    for origin in ("https://evil.example", "http://localhost:5174", "null", ORIGIN + ".evil.example"):
        assert "access-control-allow-origin" not in preflight(origin).headers, origin
    # A disallowed method or header fails the preflight, so the browser never sends the request.
    assert preflight(ORIGIN, "PUT").status_code == 400
    assert preflight(ORIGIN, "GET", "x-custom").status_code == 400


def test_cors_actual_requests(client, alice):
    good = client.get("/api/documents", headers={**alice, "Origin": ORIGIN})
    assert good.headers["access-control-allow-origin"] == ORIGIN
    assert "origin" in good.headers["vary"].lower()
    bad = client.get("/api/documents", headers={**alice, "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    err = client.get(f"/api/documents/{uuid.uuid4()}", headers={**alice, "Origin": ORIGIN})
    assert err.status_code == 404 and err.headers["access-control-allow-origin"] == ORIGIN


# ---- security headers ----

API_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "cache-control": "no-store",
}


def test_security_headers_on_success_and_error_responses(client, alice):
    responses = [
        client.get("/api/health"),
        client.get("/api/documents", headers=alice),
        client.get("/api/documents"),  # 401
        client.get(f"/api/documents/{uuid.uuid4()}", headers=alice),  # 404
        client.get("/api/nope"),
        client.post("/api/auth/login", content=b"x" * (NON_UPLOAD_BODY_LIMIT + 1)),  # 413 before routing
        client.options("/api/documents", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"}),
    ]
    for r in responses:
        for name, value in API_HEADERS.items():
            assert r.headers.get(name) == value, (r.request.url, name)
        assert "strict-transport-security" not in r.headers  # production only


def test_api_docs_keep_working_without_the_api_csp(client):
    r = client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/openapi.json").status_code == 200


def test_hsts_only_when_enabled():
    def make(hsts):
        inner = Starlette(routes=[Route("/", lambda _: PlainTextResponse("ok"))])
        return TestClient(SecurityHeadersMiddleware(inner, hsts=hsts))

    assert make(True).get("/").headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in make(False).get("/").headers


# ---- body caps and upload bypass attempts ----

def test_json_routes_cap_declared_and_streamed_bodies(client, register):
    big = b'{"email":"' + b"a" * NON_UPLOAD_BODY_LIMIT + b'@example.com","password":"correct horse"}'
    headers = {"content-type": "application/json"}
    assert error(client.post("/api/auth/register", content=big, headers=headers)) == (413, "VALIDATION_ERROR")

    def chunks():  # no Content-Length: the cap must hold while streaming
        for i in range(0, len(big), 8192):
            yield big[i : i + 8192]

    r = client.post("/api/auth/login", content=chunks(), headers=headers)
    assert error(r) == (413, "VALIDATION_ERROR")
    assert r.json()["error"]["message"] == "Request body is too large"
    assert register("erin@example.com").status_code == 201  # normal bodies unaffected


def test_upload_routes_keep_their_own_streaming_cap(client, alice, upload):
    medium = b"a" * (NON_UPLOAD_BODY_LIMIT * 4)  # above the JSON cap, far below 10 MiB
    assert upload(alice, "notes.txt", medium).status_code == 201
    limit = get_settings().max_upload_bytes
    body_parts = [b"a" * (1024 * 1024)] * (limit // (1024 * 1024) + 1)
    boundary = "cvboundary"

    def multipart():  # chunked, no Content-Length to trust
        yield (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.txt"\r\n'
               "Content-Type: text/plain\r\n\r\n").encode()
        yield from body_parts
        yield f"\r\n--{boundary}--\r\n".encode()

    r = client.post("/api/documents", headers={**alice, "content-type": f"multipart/form-data; boundary={boundary}"},
                    content=multipart())
    assert error(r) == (413, "FILE_TOO_LARGE")


def test_upload_rejects_smuggled_or_ambiguous_parts(client, alice):
    boundary = "cvboundary"
    two_files = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\nhello\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="b.txt"\r\n\r\nworld\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    headers = {**alice, "content-type": f"multipart/form-data; boundary={boundary}"}
    assert error(client.post("/api/documents", headers=headers, content=two_files)) == (422, "VALIDATION_ERROR")
    not_a_file = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"\r\n\r\nhello\r\n--{boundary}--\r\n'
    ).encode()
    assert error(client.post("/api/documents", headers=headers, content=not_a_file)) == (422, "VALIDATION_ERROR")
    files = {"file": ("../../evil.txt", b"hello", "text/plain")}
    r = client.post("/api/documents", headers=alice, files=files)
    assert r.status_code == 201
    assert r.json()["display_name"] == "evil.txt"  # display name only; never a path or key
    files = {"file": ("payload.html", b"<script>alert(1)</script>", "text/plain")}
    assert error(client.post("/api/documents", headers=alice, files=files)) == (415, "UNSUPPORTED_TYPE")
    files = {"file": ("fake.pdf", b"<html>not a pdf</html>", "application/pdf")}
    assert error(client.post("/api/documents", headers=alice, files=files)) == (415, "UNSUPPORTED_TYPE")


# ---- error hygiene ----

@pytest.mark.parametrize(
    "path",
    [
        "/api/documents?page=99999999999999999999",
        "/api/documents?page=2147483648",
        "/api/documents/{id}/download?version=99999999999",
        "/api/documents/{id}/s3-info?version=99999999999",
        "/api/documents/{id}/access-logs?page=99999999999",
        "/api/documents/{id}/versions/99999999999/restore",
        "/api/documents/{id}/processing/retry?version=99999999999",
        "/api/documents/not-a-uuid",
        "/api/recommendations/not-a-uuid/apply",
    ],
)
def test_out_of_range_input_is_a_validation_error_not_a_crash(client, alice, upload, path):
    doc = upload(alice, "a.pdf").json()
    method = "POST" if path.endswith(("restore", "apply")) or "retry" in path else "GET"
    r = client.request(method, path.format(id=doc["id"]), headers=alice)
    assert error(r) == (422, "VALIDATION_ERROR")


def test_database_errors_are_not_exposed(client, alice, monkeypatch, caplog):
    def boom(*_, **__):
        statement = "SELECT secret FROM users WHERE password = 'hunter2'"
        raise DataError(statement, {}, Exception("psycopg detail /srv/app.py"))

    monkeypatch.setattr(document_service, "list_documents", boom)
    with caplog.at_level(logging.ERROR, logger="cloudvault.errors"):
        r = client.get("/api/documents", headers=alice)
    assert r.json() == {"error": {"code": "INTERNAL_ERROR", "message": "Internal server error", "details": {}}}
    for leak in ("SELECT", "psycopg", "hunter2", "/srv", "Traceback", "DataError"):
        assert leak not in r.text
    assert "Unhandled error on GET /api/documents" in caplog.text  # diagnosed server-side


def test_validation_errors_do_not_echo_submitted_secrets(client):
    password = "p" * 73 + "-SECRET"
    r = client.post("/api/auth/register", json={"email": "frank@example.com", "password": password})
    assert r.status_code == 422
    assert "SECRET" not in r.text and "ppp" not in r.text
    r = client.post("/api/auth/login", json={"email": "not-an-email", "password": "hunter2-SECRET"})
    assert "hunter2" not in r.text


# ---- sensitive logging ----

def test_access_log_redaction_filter():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/sim-s3/b/k?versionId=v&signature=SECRET", "1.1", 200), None,
    )
    assert RedactQueryStrings().filter(record)
    assert "SECRET" not in record.getMessage()
    assert "/api/sim-s3/b/k" in record.getMessage()


def test_access_log_filter_is_installed_once(app):
    from app.main import create_app

    create_app()
    filters = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, RedactQueryStrings)]
    assert len(filters) == 1


def test_no_secrets_in_application_logs(client, register, upload, monkeypatch, caplog):
    password = "correct horse SECRETPW"
    content = b"%PDF-1.4\nCONFIDENTIAL-FILE-BODY\n"
    with caplog.at_level(logging.DEBUG):
        register("gina@example.com", password)
        login = client.post("/api/auth/login", json={"email": "gina@example.com", "password": password})
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        doc = upload(headers, "c.pdf", content).json()
        url = link(client, headers, doc["id"])["url"]
        fetch(client, url)
        fetch(client, with_query(url, signature="A" * 43))
        monkeypatch.setattr(document_service, "list_documents", lambda *a, **k: 1 / 0)
        client.get("/api/documents?q=SECRETQUERY", headers=headers)
    # The test's own HTTP client logs the URLs it requests; only the application's logs count.
    logged = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore")))
    signature = parse_qs(urlsplit(url).query)["signature"][0]
    settings = get_settings()
    for secret in (password, token, signature, settings.jwt_secret, settings.sim_signing_secret,
                   "CONFIDENTIAL-FILE-BODY", "SECRETQUERY"):
        assert secret not in logged


def test_s5_register_is_rate_limited_per_client(client, register):
    """AM-8: registration runs bcrypt, so it is capped per client (10/min); 409 stays the duplicate answer."""
    assert register("henry@example.com").status_code == 201
    assert error(register("henry@example.com")) == (409, "EMAIL_EXISTS")
    codes = [register(f"user{i}@example.com").status_code for i in range(8)]
    assert codes == [201] * 8
    blocked = register("late@example.com")
    assert error(blocked) == (429, "RATE_LIMITED")
    login = client.post("/api/auth/login", json={"email": "henry@example.com", "password": "correct horse"})
    assert login.status_code == 200  # separate budget from login
