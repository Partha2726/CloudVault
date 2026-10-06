from sqlalchemy.exc import OperationalError

from app.db import get_db


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_db_down(app, client):
    class Broken:
        def execute(self, *_):
            raise OperationalError("SELECT 1", {}, Exception("down"))

    app.dependency_overrides[get_db] = lambda: Broken()
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DB_UNAVAILABLE"


def test_unknown_route_uses_error_shape(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "message": "Not found", "details": {}}}


def test_cors_only_frontend_origin(client):
    def preflight(origin):
        return client.options("/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})

    ok = preflight("http://localhost:5173")
    bad = preflight("https://evil.example")
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers
