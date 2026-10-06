"""Password hashing (bcrypt, AM-5), JWT issue/verify (HS256, doc 05.1) and the auth dependency."""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError
from app.models import User

BCRYPT_ROUNDS = 12
BCRYPT_MAX_BYTES = 72
JWT_ALGORITHM = "HS256"

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:  # validated earlier (AM-5); never truncate silently
        raise ValueError("password longer than bcrypt's 72-byte limit")
    return bcrypt.hashpw(raw, bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(raw, password_hash.encode("ascii"))


@lru_cache
def _dummy_hash() -> str:
    return hash_password("timing-equalizer-not-a-real-password")


def burn_password_check(password: str) -> None:
    """Spend the same bcrypt time as a real check, so unknown emails are not revealed by timing."""
    verify_password(password, _dummy_hash())


def unauthorized(message: str = "Not authenticated") -> AppError:
    return AppError("UNAUTHORIZED", 401, message)


def create_access_token(user_id: uuid.UUID, now: datetime | None = None) -> str:
    settings = get_settings()
    issued = now or datetime.now(UTC)
    claims = {"sub": str(user_id), "iat": issued, "exp": issued + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise unauthorized("Invalid or expired token") from exc


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    user = db.get(User, decode_access_token(credentials.credentials))
    if user is None:
        raise unauthorized("Invalid or expired token")
    request.state.user_id = str(user.id)  # per-user rate limits (app.rate_limit.user_key)
    return user
