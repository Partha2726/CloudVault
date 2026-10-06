"""[S3-SIM] PostgreSQL-backed simulation of a versioned S3 bucket (doc 15, AM-7).

Every call runs in its own short transaction on its own session, separate from the
application's transaction (AM-1). Behavior follows `docs/VERIFIED.md`.
"""

import base64
import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, undefer

from app.storage.base import (
    MAX_KEY_BYTES,
    MAX_TAG_KEY_CHARS,
    MAX_TAG_VALUE_CHARS,
    MAX_TAGS,
    STANDARD,
    STORAGE_CLASSES,
    BadDigest,
    DeleteResult,
    InvalidArgument,
    MethodNotAllowed,
    NoSuchKey,
    NoSuchVersion,
    ObjectHead,
    PutResult,
    StorageLimitExceeded,
    VersionEntry,
)
from app.storage.models import SimObjectVersion

# Transaction-level advisory lock serializing writes that grow the store, so two
# concurrent writes cannot both pass the total-size check.
_QUOTA_LOCK_KEY = 0x43565F5155  # "CV_QU"


def new_version_id() -> str:
    """Opaque, URL-safe, 32 characters (real S3 version ids are opaque strings too)."""
    return secrets.token_urlsafe(24)


def sha256_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def md5_etag(data: bytes) -> str:
    return f'"{hashlib.md5(data, usedforsecurity=False).hexdigest()}"'


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_key(key: str) -> None:
    if not isinstance(key, str) or not 1 <= len(key.encode("utf-8")) <= MAX_KEY_BYTES:
        raise InvalidArgument("Object key must be 1 to 1024 bytes of UTF-8")


def _check_ascii_map(name: str, values: dict[str, str]) -> None:
    for k, v in values.items():
        if not (isinstance(k, str) and isinstance(v, str) and k.isascii() and v.isascii() and k.isprintable()):
            raise InvalidArgument(f"{name} keys and values must be printable ASCII strings")


def _check_tags(tags: dict[str, str]) -> None:
    if len(tags) > MAX_TAGS:
        raise InvalidArgument(f"At most {MAX_TAGS} tags per object")
    for k, v in tags.items():
        if not isinstance(k, str) or not isinstance(v, str) or not 1 <= len(k) <= MAX_TAG_KEY_CHARS:
            raise InvalidArgument(f"Tag keys must be 1 to {MAX_TAG_KEY_CHARS} characters")
        if len(v) > MAX_TAG_VALUE_CHARS:
            raise InvalidArgument(f"Tag values must be at most {MAX_TAG_VALUE_CHARS} characters")


class PostgresObjectStorage:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        bucket: str,
        limit_bytes: int,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._sessions = session_factory
        self._bucket = bucket
        self._limit = limit_bytes
        self._clock = clock

    @property
    def bucket(self) -> str:
        return self._bucket

    # ---- helpers ----

    def _latest(self, s: Session, key: str) -> SimObjectVersion | None:
        return s.scalar(
            select(SimObjectVersion)
            .where(SimObjectVersion.bucket == self._bucket, SimObjectVersion.key == key)
            .order_by(SimObjectVersion.id.desc())
            .limit(1)
        )

    def _version(self, s: Session, key: str, version_id: str, *, with_data: bool = False) -> SimObjectVersion:
        query = select(SimObjectVersion).where(
            SimObjectVersion.bucket == self._bucket,
            SimObjectVersion.key == key,
            SimObjectVersion.version_id == version_id,
        )
        if with_data:
            query = query.options(undefer(SimObjectVersion.data))
        row = s.scalar(query)
        if row is None:
            raise NoSuchVersion(key, version_id)
        return row

    def _resolve(self, s: Session, key: str, version_id: str | None, *, with_data: bool = False) -> SimObjectVersion:
        """GET/HEAD target: the named version, or the latest one (doc VERIFIED rows 3 and 5)."""
        if version_id is not None:
            row = self._version(s, key, version_id, with_data=with_data)
            if row.is_delete_marker:
                raise MethodNotAllowed(f"{key}@{version_id} is a delete marker")
            return row
        latest = self._latest(s, key)
        if latest is None:
            raise NoSuchKey(key)
        if latest.is_delete_marker:
            raise NoSuchKey(key, delete_marker=True)
        if with_data:
            s.refresh(latest, attribute_names=["data"])
        return latest

    def _is_latest(self, s: Session, row: SimObjectVersion) -> bool:
        latest = self._latest(s, row.key)
        return latest is not None and latest.id == row.id

    def _head(self, row: SimObjectVersion, is_latest: bool) -> ObjectHead:
        return ObjectHead(
            bucket=row.bucket,
            key=row.key,
            version_id=row.version_id,
            etag=row.etag or "",
            size_bytes=row.size_bytes,
            content_type=row.content_type or "",
            last_modified=row.last_modified,
            storage_class=None if row.storage_class == STANDARD else row.storage_class,
            checksum_sha256=row.checksum_sha256 or "",
            metadata=dict(row.metadata_),
            is_latest=is_latest,
        )

    def _reserve(self, s: Session, extra_bytes: int) -> None:
        s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _QUOTA_LOCK_KEY})
        used = s.scalar(select(func.coalesce(func.sum(SimObjectVersion.size_bytes), 0)))
        if used + extra_bytes > self._limit:
            raise StorageLimitExceeded(f"Simulated storage limit of {self._limit} bytes would be exceeded")

    # ---- operations ----

    def put_object(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
        checksum_sha256: str | None = None,
    ) -> PutResult:
        _check_key(key)
        metadata, tags = dict(metadata or {}), dict(tags or {})
        _check_ascii_map("Metadata", metadata)
        _check_tags(tags)
        if not content_type:
            raise InvalidArgument("Content type is required")
        actual = sha256_b64(data)
        if checksum_sha256 is not None and not secrets.compare_digest(checksum_sha256, actual):
            raise BadDigest("SHA-256 checksum does not match the uploaded bytes")
        row = SimObjectVersion(
            bucket=self._bucket,
            key=key,
            version_id=new_version_id(),
            is_delete_marker=False,
            data=data,
            size_bytes=len(data),
            content_type=content_type,
            etag=md5_etag(data),
            checksum_sha256=actual,
            storage_class=STANDARD,
            metadata_=metadata,
            tags=tags,
            last_modified=self._clock(),
        )
        with self._sessions() as s, s.begin():
            self._reserve(s, len(data))
            s.add(row)
        return PutResult(version_id=row.version_id, etag=row.etag, last_modified=row.last_modified)

    def copy_object(self, key: str, source_version_id: str, *, storage_class: str | None = None) -> PutResult:
        """Copy a version onto the same key: new version, class STANDARD unless given (VERIFIED row 4)."""
        target_class = storage_class or STANDARD
        if target_class not in STORAGE_CLASSES:
            raise InvalidArgument(f"Unsupported storage class {target_class}")
        with self._sessions() as s, s.begin():
            source = self._version(s, key, source_version_id, with_data=True)
            if source.is_delete_marker:
                raise MethodNotAllowed(f"{key}@{source_version_id} is a delete marker")
            self._reserve(s, source.size_bytes)
            row = SimObjectVersion(
                bucket=self._bucket,
                key=key,
                version_id=new_version_id(),
                is_delete_marker=False,
                data=source.data,
                size_bytes=source.size_bytes,
                content_type=source.content_type,
                etag=source.etag,
                checksum_sha256=source.checksum_sha256,
                storage_class=target_class,
                metadata_=dict(source.metadata_),
                tags=dict(source.tags),
                last_modified=self._clock(),
            )
            s.add(row)
        return PutResult(version_id=row.version_id, etag=row.etag or "", last_modified=row.last_modified)

    def delete_object(self, key: str) -> str:
        _check_key(key)
        row = SimObjectVersion(
            bucket=self._bucket, key=key, version_id=new_version_id(), is_delete_marker=True,
            last_modified=self._clock(),
        )
        with self._sessions() as s, s.begin():
            s.add(row)
        return row.version_id

    def delete_version(self, key: str, version_id: str) -> None:
        with self._sessions() as s, s.begin():
            s.execute(
                delete(SimObjectVersion).where(
                    SimObjectVersion.bucket == self._bucket,
                    SimObjectVersion.key == key,
                    SimObjectVersion.version_id == version_id,
                )
            )

    def delete_all_versions(self, key: str) -> list[DeleteResult]:
        with self._sessions() as s, s.begin():
            removed = s.scalars(
                delete(SimObjectVersion)
                .where(SimObjectVersion.bucket == self._bucket, SimObjectVersion.key == key)
                .returning(SimObjectVersion.version_id)
            ).all()
        return [DeleteResult(version_id=v, deleted=True) for v in removed]

    def head_object(self, key: str, version_id: str | None = None) -> ObjectHead:
        with self._sessions() as s:
            row = self._resolve(s, key, version_id)
            return self._head(row, self._is_latest(s, row))

    def get_object(self, key: str, version_id: str | None = None) -> tuple[ObjectHead, bytes]:
        with self._sessions() as s:
            row = self._resolve(s, key, version_id, with_data=True)
            return self._head(row, self._is_latest(s, row)), bytes(row.data or b"")

    def get_object_tagging(self, key: str, version_id: str | None = None) -> dict[str, str]:
        with self._sessions() as s:
            return dict(self._resolve(s, key, version_id).tags)

    def list_object_versions(self, prefix: str = "") -> list[VersionEntry]:
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._sessions() as s:
            rows = s.scalars(
                select(SimObjectVersion)
                .where(SimObjectVersion.bucket == self._bucket, SimObjectVersion.key.like(f"{escaped}%", escape="\\"))
                .order_by(SimObjectVersion.key, SimObjectVersion.id.desc())
            ).all()
        entries, previous_key = [], None
        for row in rows:
            entries.append(
                VersionEntry(
                    key=row.key,
                    version_id=row.version_id,
                    is_delete_marker=row.is_delete_marker,
                    is_latest=row.key != previous_key,
                    size_bytes=row.size_bytes,
                    storage_class=row.storage_class,
                    etag=row.etag,
                    last_modified=row.last_modified,
                )
            )
            previous_key = row.key
        return entries

    def total_stored_bytes(self) -> int:
        with self._sessions() as s:
            return int(s.scalar(select(func.coalesce(func.sum(SimObjectVersion.size_bytes), 0))))

    def check(self) -> None:
        with self._sessions() as s:
            s.execute(select(SimObjectVersion.id).limit(0))
