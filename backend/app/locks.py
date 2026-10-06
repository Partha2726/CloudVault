"""Per-document serialization with PostgreSQL session advisory locks (doc 15, AM-1).

`document_lock(document_id)` holds `pg_advisory_lock` for the whole logical operation,
including storage calls, without keeping a transaction open:

- The lock lives on a dedicated connection from a separate small pool (`lock_engine`),
  in AUTOCOMMIT mode, so the connection is never "idle in transaction".
- Callers must not hold a main-pool connection while waiting for the lock (commit or
  close their session first). Lock waiters then hold nothing, and main-pool waiters never
  wait on the lock pool, so the two pools cannot deadlock each other.
- The lock is released in `finally`. If release cannot be confirmed, the connection is
  invalidated (closed) instead of being returned to the pool still holding the lock.
- Keys are derived deterministically from the document UUID; different documents get
  independent locks. There is no global lock.

Production must use a direct (non-pooled) Neon connection string: session advisory
locks do not survive transaction-mode connection pooling (AM-1).
"""

import hashlib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger("cloudvault.locks")

# Separates document lock keys from other advisory-lock users (e.g. the storage quota lock).
_NAMESPACE = b"cloudvault:document:"

lock_engine = create_engine(
    get_settings().database_url,
    isolation_level="AUTOCOMMIT",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=15,
    pool_timeout=10,
    # The statement timeout also bounds how long a request waits for a busy document.
    connect_args={"connect_timeout": 5, "options": "-c statement_timeout=30000 -c timezone=UTC"},
)


def lock_key(document_id: uuid.UUID | str) -> int:
    """Signed 64-bit advisory-lock key for a document (BLAKE2b of the namespaced UUID bytes)."""
    raw = uuid.UUID(str(document_id)).bytes
    digest = hashlib.blake2b(_NAMESPACE + raw, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


@contextmanager
def document_lock(document_id: uuid.UUID | str) -> Iterator[None]:
    key = lock_key(document_id)
    conn = lock_engine.connect()
    try:
        try:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
        except BaseException:
            # The server may have granted the lock even if we did not see the reply.
            conn.invalidate()
            raise
        try:
            yield
        finally:
            _release(conn, key)
    finally:
        conn.close()


def _release(conn, key: int) -> None:
    try:
        released = conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key}).scalar()
    except BaseException:
        logger.exception("Could not release document lock; discarding its connection")
        conn.invalidate()
        raise
    if not released:
        logger.error("Document lock was not held at release; discarding its connection")
        conn.invalidate()
