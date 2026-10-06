"""[S3-SIM] Object storage for CloudVault (doc 15, AM-7).

`get_storage()` is the single place that chooses the backend; routers depend on it so
tests (and a possible future real S3 adapter) can swap implementations.
"""

import uuid
from functools import lru_cache

from app.storage.base import ObjectStorage


def build_key(owner_id: uuid.UUID | str, document_id: uuid.UUID | str) -> str:
    """`documents/{owner_uuid}/{document_uuid}` (doc 02.3). UUIDs only; never a filename."""
    return f"documents/{uuid.UUID(str(owner_id))}/{uuid.UUID(str(document_id))}"


@lru_cache
def get_storage() -> ObjectStorage:
    from app.config import get_settings
    from app.db import SessionLocal
    from app.storage.postgres import PostgresObjectStorage

    settings = get_settings()
    if settings.storage_backend != "postgres":  # only backend today
        raise RuntimeError(f"Unknown STORAGE_BACKEND {settings.storage_backend!r}")
    return PostgresObjectStorage(SessionLocal, settings.sim_bucket_name, settings.sim_storage_limit_bytes)
