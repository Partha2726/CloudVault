"""[S3-SIM] Object-storage interface (doc 15, AM-7).

The application talks to object storage only through `ObjectStorage`. The one
implementation is `PostgresObjectStorage`; a real S3 adapter could implement the same
protocol later. Semantics follow `docs/VERIFIED.md`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

STANDARD = "STANDARD"
STORAGE_CLASSES = ("STANDARD", "STANDARD_IA", "GLACIER_IR")
MAX_TAGS = 10
MAX_TAG_KEY_CHARS = 128
MAX_TAG_VALUE_CHARS = 256
MAX_KEY_BYTES = 1024


# ---- errors (names follow the S3 error codes they simulate) ----

class StorageError(Exception):
    """Base class for storage-layer failures."""

    code = "StorageError"


class NoSuchKey(StorageError):
    """No object at this key, or its current version is a delete marker (S3: 404)."""

    code = "NoSuchKey"

    def __init__(self, key: str, delete_marker: bool = False):
        super().__init__(key)
        self.key = key
        self.delete_marker = delete_marker


class NoSuchVersion(StorageError):
    """The named version does not exist (S3: 404). Callers map it to 410 + S3_MISSING."""

    code = "NoSuchVersion"

    def __init__(self, key: str, version_id: str):
        super().__init__(f"{key}@{version_id}")
        self.key = key
        self.version_id = version_id


class MethodNotAllowed(StorageError):
    """The named version is a delete marker (S3: 405 with x-amz-delete-marker)."""

    code = "MethodNotAllowed"


class BadDigest(StorageError):
    """The supplied SHA-256 checksum does not match the bytes."""

    code = "BadDigest"


class InvalidArgument(StorageError):
    """Bad key, tags or storage class."""

    code = "InvalidArgument"


class StorageLimitExceeded(StorageError):
    """The simulated store's total size limit would be exceeded (507 STORAGE_LIMIT_EXCEEDED)."""

    code = "StorageLimitExceeded"


# ---- results ----

@dataclass(frozen=True)
class PutResult:
    version_id: str
    etag: str
    last_modified: datetime


@dataclass(frozen=True)
class ObjectHead:
    """HEAD response. `storage_class` is None for STANDARD, as real S3 omits the header."""

    bucket: str
    key: str
    version_id: str
    etag: str
    size_bytes: int
    content_type: str
    last_modified: datetime
    storage_class: str | None
    checksum_sha256: str
    metadata: dict[str, str] = field(default_factory=dict)
    is_latest: bool = False


@dataclass(frozen=True)
class VersionEntry:
    """One row of ListObjectVersions: an object version or a delete marker."""

    key: str
    version_id: str
    is_delete_marker: bool
    is_latest: bool
    size_bytes: int
    storage_class: str | None
    etag: str | None
    last_modified: datetime


@dataclass(frozen=True)
class DeleteResult:
    version_id: str
    deleted: bool
    error: str | None = None


class ObjectStorage(Protocol):
    @property
    def bucket(self) -> str: ...

    def put_object(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
        checksum_sha256: str | None = None,
    ) -> PutResult: ...

    def copy_object(self, key: str, source_version_id: str, *, storage_class: str | None = None) -> PutResult: ...

    def delete_object(self, key: str) -> str:
        """Plain delete: adds a delete marker and returns its version id."""
        ...

    def delete_version(self, key: str, version_id: str) -> None:
        """Permanently removes exactly one version or marker; a missing version is a no-op."""
        ...

    def delete_all_versions(self, key: str) -> list[DeleteResult]: ...

    def head_object(self, key: str, version_id: str | None = None) -> ObjectHead: ...

    def get_object(self, key: str, version_id: str | None = None) -> tuple[ObjectHead, bytes]: ...

    def get_object_tagging(self, key: str, version_id: str | None = None) -> dict[str, str]: ...

    def list_object_versions(self, prefix: str = "") -> list[VersionEntry]: ...

    def total_stored_bytes(self) -> int: ...

    def check(self) -> None:
        """Startup check (the simulated HeadBucket): raises if the store is unusable."""
        ...
