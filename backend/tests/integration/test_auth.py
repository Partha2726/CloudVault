"""T7: register, login, me (doc 05.5, AM-5). Tests S2 and S5 from doc 10.2."""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pytest

from app.config import get_settings
from app.models import User
from app.security import create_access_token


def error(r):
    return r.status_code, r.json()["error"]["code"]


# ---- register ----

def test_register_returns_id_and_normalized_email(client, register, db):
    r = register("  Alice@Example.COM ", "correct horse")
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alice@example.com" and uuid.UUID(body["id"])
    assert set(body) == {"id", "email"}
    stored = db.get(User, uuid.UUID(body["id"]))
    assert stored.password_hash.startswith("$2") and "correct horse" not in stored.password_hash
    assert bcrypt.checkpw(b"correct horse", stored.password_hash.encode())


def test_register_duplicate_email_case_insensitive(register, db):
    assert register("bob@example.com").status_code == 201
    assert error(register("BOB@example.com ")) == (409, "EMAIL_EXISTS")


@pytest.mark.parametrize("password", ["a" * 8, "a" * 72, "é" * 36, "日本語のパスワード"])
def test_register_accepts_passwords_within_limits(register, password):
    assert register(f"{uuid.uuid4().hex}@example.com", password).status_code == 201


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("a" * 7, "Password must be 8 to 128 characters"),
        ("a" * 129, "Password must be 8 to 128 characters"),
        ("a" * 73, "Password must be at most 72 bytes when UTF-8 encoded"),
        ("é" * 37, "Password must be at most 72 bytes when UTF-8 encoded"),  # 37 chars, 74 bytes
        ("日" * 25, "Password must be at most 72 bytes when UTF-8 encoded"),  # 25 chars, 75 bytes
    ],
)
def test_register_rejects_bad_password_length(register, password, message):
    r = register("p@example.com", password)
    assert error(r) == (422, "VALIDATION_ERROR")
    assert r.json()["error"]["message"] == message


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "a b@c.com", "x" * 250 + "@e.com"])
def test_register_rejects_bad_email(register, email):
    assert error(register(email)) == (422, "VALIDATION_ERROR")


def test_register_rejects_unknown_fields(client):
    r = client.post("/api/auth/register", json={"email": "a@b.co", "password": "longenough", "role": "admin"})
    assert error(r) == (422, "VALIDATION_ERROR")


# ---- login ----

def test_login_returns_bearer_token(client, register):
    register("carol@example.com", "correct horse")
    r = client.post("/api/auth/login", json={"email": "CAROL@example.com", "password": "correct horse"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    claims = jwt.decode(body["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 60 * 60


def test_login_same_401_for_unknown_email_and_wrong_password(client, register):
    register("dave@example.com", "correct horse")
    wrong = client.post("/api/auth/login", json={"email": "dave@example.com", "password": "wrong horse"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "correct horse"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "UNAUTHORIZED"


def test_login_with_overlong_password_is_plain_401(client, register):
    register("erin@example.com", "correct horse")
    r = client.post("/api/auth/login", json={"email": "erin@example.com", "password": "é" * 100})
    assert error(r) == (401, "UNAUTHORIZED")


def test_s5_login_brute_force_rate_limited(client, register):
    register("frank@example.com", "correct horse")
    bad = {"email": "frank@example.com", "password": "wrong horse"}
    codes = [client.post("/api/auth/login", json=bad).status_code for _ in range(5)]
    assert codes == [401] * 5
    r = client.post("/api/auth/login", json=bad)
    assert error(r) == (429, "RATE_LIMITED")
    # The limit is per IP for all logins, including correct ones.
    ok = client.post("/api/auth/login", json={"email": "frank@example.com", "password": "correct horse"})
    assert ok.status_code == 429


# ---- me / tokens ----

def test_me_returns_current_user(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers("gina@example.com"))
    assert r.status_code == 200 and r.json()["email"] == "gina@example.com"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not.a.jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    ],
)
def test_s2_missing_or_malformed_token(client, headers):
    assert error(client.get("/api/auth/me", headers=headers)) == (401, "UNAUTHORIZED")


def test_expired_token_rejected(client, register):
    user_id = register("hank@example.com").json()["id"]
    past = datetime.now(UTC) - timedelta(hours=2)
    token = create_access_token(uuid.UUID(user_id), now=past)
    assert error(client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})) == (401, "UNAUTHORIZED")


def test_token_signed_with_other_secret_rejected(client, register):
    user_id = register("ivy@example.com").json()["id"]
    now = datetime.now(UTC)
    forged = jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(hours=1)}, "x" * 40, algorithm="HS256")
    assert error(client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})) == (401, "UNAUTHORIZED")


def test_none_algorithm_token_rejected(client, register):
    user_id = register("jack@example.com").json()["id"]
    now = datetime.now(UTC)
    unsigned = jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(hours=1)}, None, algorithm="none")
    assert error(client.get("/api/auth/me", headers={"Authorization": f"Bearer {unsigned}"})) == (401, "UNAUTHORIZED")


def test_token_missing_exp_rejected(client, register):
    user_id = register("kim@example.com").json()["id"]
    token = jwt.encode({"sub": user_id, "iat": datetime.now(UTC)}, get_settings().jwt_secret, algorithm="HS256")
    assert error(client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})) == (401, "UNAUTHORIZED")


def test_token_for_deleted_or_unknown_user_rejected(client):
    token = create_access_token(uuid.uuid4())
    assert error(client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})) == (401, "UNAUTHORIZED")


def test_token_with_non_uuid_subject_rejected(client):
    now = datetime.now(UTC)
    token = jwt.encode({"sub": "admin", "iat": now, "exp": now + timedelta(hours=1)},
                       get_settings().jwt_secret, algorithm="HS256")
    assert error(client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})) == (401, "UNAUTHORIZED")
