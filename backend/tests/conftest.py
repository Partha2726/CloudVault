"""Shared fixtures. Tests use a throwaway `<dev db>_test` database on a local Postgres only."""

import os

from sqlalchemy.engine import make_url

from app.config import get_settings

# Point the app at the test database before any app module creates its engine.
_dev_url = make_url(os.environ.get("DATABASE_URL") or get_settings().database_url)
if _dev_url.host not in ("localhost", "127.0.0.1", "::1"):
    raise RuntimeError(f"Refusing to run tests against non-local database host {_dev_url.host!r}")
TEST_DB_NAME = f"{_dev_url.database}_test"
os.environ["DATABASE_URL"] = _dev_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-" + "x" * 24
os.environ["SIM_SIGNING_SECRET"] = "test-only-signing-secret-" + "y" * 24
os.environ["PROCESSING_WORKER_ENABLED"] = "false"
ADMIN_URL = _dev_url.set(database="postgres").render_as_string(hide_password=False)
get_settings.cache_clear()

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import BACKEND_DIR  # noqa: E402

TABLES = (
    "storage_recommendations, processing_jobs, access_logs, document_versions, documents, users, sim_object_versions"
)


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"].replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db():
    """Recreate the empty test database and migrate it to head once per session."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()
    command.upgrade(alembic_config(), "head")
    yield
    from app.db import engine
    from app.locks import lock_engine

    engine.dispose()
    lock_engine.dispose()


@pytest.fixture
def db(migrated_db):
    from app.db import SessionLocal, engine

    session = SessionLocal()
    yield session
    session.rollback()
    session.close()
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
def app(db):
    """Depends on `db` so every API test starts and ends with empty tables."""
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _fast_bcrypt_and_fresh_limits(monkeypatch):
    """Cheap bcrypt rounds in tests; rate-limit counters start empty for every test."""
    from app import security
    from app.rate_limit import limiter

    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)
    security._dummy_hash.cache_clear()
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def register(client):
    def _register(email="user@example.com", password="correct horse"):
        return client.post("/api/auth/register", json={"email": email, "password": password})

    return _register


@pytest.fixture
def auth_headers(client, register):
    """Register + log in a user; returns a function giving Bearer headers for an email."""

    def _headers(email="user@example.com", password="correct horse"):
        register(email, password)
        token = client.post("/api/auth/login", json={"email": email, "password": password}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _headers


PDF_BYTES = b"%PDF-1.4\n% CloudVault test document\n"


@pytest.fixture
def upload(client):
    """POST /api/documents with a multipart `file` part."""

    def _upload(headers, name="report.pdf", data=PDF_BYTES, test_client=None):
        files = {"file": (name, data, "application/octet-stream")}
        return (test_client or client).post("/api/documents", headers=headers, files=files)

    return _upload
