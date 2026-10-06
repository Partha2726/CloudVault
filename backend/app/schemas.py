"""Request/response models (doc 05)."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.security import BCRYPT_MAX_BYTES

EMAIL_MAX_LENGTH = 254
PASSWORD_MIN_CHARS = 8
PASSWORD_MAX_CHARS = 128
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    return value.strip().lower()


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        email = normalize_email(value)
        if len(email) > EMAIL_MAX_LENGTH or not _EMAIL_SHAPE.match(email):
            raise ValueError("Enter a valid email address")
        return email


class RegisterRequest(Credentials):
    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        """Doc 05.5 (8-128 characters) plus AM-5 (at most 72 UTF-8 bytes, bcrypt's limit)."""
        if not PASSWORD_MIN_CHARS <= len(value) <= PASSWORD_MAX_CHARS:
            raise ValueError(f"Password must be {PASSWORD_MIN_CHARS} to {PASSWORD_MAX_CHARS} characters")
        if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError("Password must be at most 72 bytes when UTF-8 encoded")
        return value


class LoginRequest(Credentials):
    """Login accepts any password string; a wrong one simply fails with 401."""


class UserOut(BaseModel):
    id: uuid.UUID
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- documents (doc 05.4) ----


class CurrentVersionOut(BaseModel):
    version_number: int
    size_bytes: int
    content_type: str
    storage_class: str
    created_at: datetime
    origin: str
    state: str


class ProcessingSummaryOut(BaseModel):
    status: str
    page_count: int | None
    word_count: int | None
    stalled: bool


class DocumentOut(BaseModel):
    id: uuid.UUID
    display_name: str
    status: str
    current_version: CurrentVersionOut | None
    version_count: int
    processing: ProcessingSummaryOut | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class DuplicateOut(BaseModel):
    duplicate: bool = True
    document: DocumentOut


class DownloadLinkOut(BaseModel):
    url: str
    expires_in: int


class AccessLogOut(BaseModel):
    accessed_at: datetime
    version_number: int
    event_type: str


class AccessLogPage(BaseModel):
    items: list[AccessLogOut]
    total: int
    page: int
    page_size: int


class VersionOut(BaseModel):
    version_number: int
    size_bytes: int
    content_type: str
    sha256: str
    storage_class: str
    origin: str
    restored_from_version: int | None
    state: str
    is_current: bool
    created_at: datetime


class VersionList(BaseModel):
    items: list[VersionOut]


class VersionDuplicateOut(BaseModel):
    duplicate: bool = True


class S3InfoOut(BaseModel):
    """Doc 05.4 S3 info, read from the simulated store (AM-7)."""

    bucket: str
    key: str
    version_id: str
    etag: str
    content_length: int
    content_type: str
    last_modified: datetime
    storage_class: str
    metadata: dict[str, str]
    tags: dict[str, str]
    source: str = "simulated-s3"


class RecommendationOut(BaseModel):
    """Doc 05.4 Recommendation. `estimate` stays null (doc 07.5; no pricing format specified)."""

    id: uuid.UUID
    document_id: uuid.UUID
    display_name: str
    version_number: int
    current_class: str
    recommended_class: str
    rule_id: str
    reason: str
    signals: dict[str, int]
    estimate: None = None
    status: str
    created_at: datetime


class RecommendationList(BaseModel):
    items: list[RecommendationOut]


class DashboardSummary(BaseModel):
    document_count: int
    current_bytes: int
    total_bytes_all_versions: int
    accesses_30d: int
    bytes_by_class: dict[str, int]
    open_recommendations: int
    jobs_by_status: dict[str, int]


class ProcessingItem(BaseModel):
    """Doc 05.5 `GET /documents/{id}/processing` item."""

    version_number: int
    status: str
    attempts: int
    error_code: str | None
    page_count: int | None
    word_count: int | None
    stalled: bool


class ProcessingList(BaseModel):
    items: list[ProcessingItem]
