"""Standard error envelope for framework and unexpected errors (doc 05.1, AM-6)."""

import logging

from fastapi import APIRouter
from fastapi.testclient import TestClient

SECRET = "db-password-in-exception-text"


def make_client(app):
    router = APIRouter()

    @router.get("/api/boom")
    def boom():
        raise RuntimeError(SECRET)

    @router.get("/api/items/{item_id}")
    def item(item_id: int):
        return {"id": item_id}

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_error_returns_generic_envelope(app, caplog):
    client = make_client(app)
    with caplog.at_level(logging.ERROR, logger="cloudvault.errors"):
        r = client.get("/api/boom", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "INTERNAL_ERROR", "message": "Internal server error", "details": {}}}
    assert SECRET not in r.text and "Traceback" not in r.text
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    record = caplog.records[-1]
    assert "GET /api/boom" in record.getMessage()
    assert record.exc_info and SECRET in str(record.exc_info[1])


def test_request_validation_error_envelope(app):
    r = make_client(app).get("/api/items/not-a-number")
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["fields"][0]["loc"] == ["path", "item_id"]
    assert "not-a-number" not in r.text


def test_method_not_allowed_envelope(app):
    r = make_client(app).delete("/api/health")
    assert r.status_code == 405
    assert r.json()["error"] == {"code": "VALIDATION_ERROR", "message": "Method not allowed", "details": {}}
