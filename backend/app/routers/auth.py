from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import User
from app.rate_limit import limiter
from app.schemas import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.security import (
    burn_password_check,
    create_access_token,
    get_current_user,
    hash_password,
    unauthorized,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REGISTER_LIMIT = "10/minute"  # per client IP (doc 15 AM-8)


def _email_taken() -> AppError:
    return AppError("EMAIL_EXISTS", 409, "An account with this email already exists")


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
@limiter.limit(REGISTER_LIMIT)  # AM-8: each call runs bcrypt; checked before hashing
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)) -> User:
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email)):
        raise _email_taken()
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent registration hit the unique index
        db.rollback()
        raise _email_taken() from exc
    return user


@router.post("/login", response_model=TokenOut)
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email))
    if user is None:
        burn_password_check(body.password)
        raise unauthorized("Invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise unauthorized("Invalid email or password")
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
