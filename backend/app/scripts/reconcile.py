"""Reconcile the simulated store with the application tables (doc 09.3; AM-1, AM-7).

    python -m app.scripts.reconcile [--fix] [--now ISO-8601]

Without --fix it only reports. With --fix, every change to one document runs under that
document's advisory lock (app/locks.py), so it never races a live request:

1. Stale PENDING documents (older than 1 hour): an upload that never finalized. No version
   row exists for it (AM-9: rows are inserted only after the store write), so the
   document is marked FAILED, which frees the name; any object the upload left in the
   store is unreferenced and handled by check 3.
2. Stale pending_op (older than 1 hour): rolled forward or dropped by the same recovery
   the API uses (app/services/deletion_service.recover_interrupted).
3. Stored object versions no version row references: reported; deleted when older than
   1 hour (an upload in progress is younger).
4. ACTIVE versions the store no longer holds: marked S3_MISSING (doc 02.2).
5. ACTIVE documents whose latest stored entry is a delete marker: reported only.
"""

import argparse
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.locks import document_lock
from app.models import Document, DocumentVersion
from app.services.deletion_service import recover_interrupted
from app.storage.base import NoSuchVersion, ObjectStorage, VersionEntry

STALE_AFTER = timedelta(hours=1)
PREFIX = "documents/"


@dataclass
class Report:
    failed_uploads: list[str] = field(default_factory=list)
    recovered_ops: list[str] = field(default_factory=list)
    unreferenced: list[str] = field(default_factory=list)
    deleted_unreferenced: list[str] = field(default_factory=list)
    marked_missing: list[str] = field(default_factory=list)
    marker_on_active: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = []
        for name, items in vars(self).items():
            out.append(f"{name}: {len(items)}")
            out.extend(f"  {item}" for item in items)
        return out

    @property
    def clean(self) -> bool:
        return not any(vars(self).values())


def _entries(storage: ObjectStorage, key: str) -> list[VersionEntry]:
    return [e for e in storage.list_object_versions(key) if e.key == key]


def reconcile(
    session_factory: Callable[[], Session],
    storage: ObjectStorage,
    *,
    fix: bool = False,
    now: datetime | None = None,
) -> Report:
    now = now or datetime.now(UTC)
    cutoff = now - STALE_AFTER
    report = Report()

    with session_factory() as db:
        _stale_uploads(db, storage, report, fix=fix, cutoff=cutoff)
        _stale_ops(db, storage, report, fix=fix, cutoff=cutoff)
        _unreferenced(db, storage, report, fix=fix, cutoff=cutoff)
        _missing_versions(db, storage, report, fix=fix)
        _markers_on_active(db, storage, report)
    return report


# ---- 1. stale PENDING documents ----


def _stale_uploads(db: Session, storage: ObjectStorage, report: Report, *, fix: bool, cutoff: datetime) -> None:
    stale = db.scalars(
        select(Document.id)
        .where(Document.status == "PENDING", Document.created_at < cutoff)
        .order_by(Document.created_at)
    ).all()
    db.commit()
    for document_id in stale:
        if not fix:
            report.failed_uploads.append(f"would mark PENDING document {document_id} FAILED")
            continue
        with document_lock(document_id):  # an upload still finalizing holds this lock
            changed = db.execute(
                update(Document)
                .where(Document.id == document_id, Document.status == "PENDING")
                .values(status="FAILED")
            ).rowcount
            db.commit()
        if changed:
            report.failed_uploads.append(f"document {document_id} marked FAILED")


# ---- 2. stale pending_op ----


def _stale_ops(db: Session, storage: ObjectStorage, report: Report, *, fix: bool, cutoff: datetime) -> None:
    stale = db.execute(
        select(Document.id, Document.owner_id, Document.pending_op).where(
            Document.pending_op.is_not(None), Document.pending_op_at < cutoff
        )
    ).all()
    db.commit()
    for document_id, owner_id, op in stale:
        if not fix:
            report.recovered_ops.append(f"would recover {op} on document {document_id}")
            continue
        with document_lock(document_id):
            _, completed = recover_interrupted(db, storage, owner_id, document_id)
        report.recovered_ops.append(f"{op} on document {document_id}: {'completed' if completed else 'resolved'}")


# ---- 3. unreferenced stored versions ----


def _referenced_ids(db: Session) -> set[str]:
    ids = {v for v in db.scalars(select(DocumentVersion.s3_version_id)) if v}
    ids |= {m for m in db.scalars(select(Document.delete_marker_version_id)) if m}
    db.commit()
    return ids


def _document_id_of(key: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(key.rsplit("/", 1)[-1])
    except ValueError:
        return None


def _unreferenced(db: Session, storage: ObjectStorage, report: Report, *, fix: bool, cutoff: datetime) -> None:
    referenced = _referenced_ids(db)
    for entry in storage.list_object_versions(PREFIX):
        if entry.is_delete_marker or entry.version_id in referenced:
            continue  # markers are covered by check 5
        line = f"{entry.key} {entry.version_id} ({entry.last_modified.isoformat()})"
        report.unreferenced.append(line)
        if not fix or entry.last_modified >= cutoff:
            continue
        doc_id = _document_id_of(entry.key)
        if doc_id is None:
            storage.delete_version(entry.key, entry.version_id)
        else:
            with document_lock(doc_id):
                if entry.version_id not in _referenced_ids(db):  # re-check under the lock
                    storage.delete_version(entry.key, entry.version_id)
        report.deleted_unreferenced.append(line)


# ---- 4. ACTIVE versions missing from the store ----


def _missing_versions(db: Session, storage: ObjectStorage, report: Report, *, fix: bool) -> None:
    rows = db.execute(
        select(DocumentVersion.id, DocumentVersion.s3_version_id, Document.s3_key)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.state == "ACTIVE")
    ).all()
    db.commit()
    for version_id, store_id, key in rows:
        try:
            storage.head_object(key, store_id)
            continue
        except NoSuchVersion:
            pass
        except Exception:  # a delete marker id or another storage answer: not "missing"
            continue
        report.marked_missing.append(f"version {version_id} ({key} {store_id})")
        if fix:
            db.execute(
                update(DocumentVersion)
                .where(DocumentVersion.id == version_id, DocumentVersion.s3_version_id == store_id,
                       DocumentVersion.state == "ACTIVE")
                .values(state="S3_MISSING")
            )
            db.commit()


# ---- 5. ACTIVE documents hidden by a delete marker ----


def _markers_on_active(db: Session, storage: ObjectStorage, report: Report) -> None:
    rows = db.execute(select(Document.id, Document.s3_key).where(Document.status == "ACTIVE")).all()
    db.commit()
    for doc_id, key in rows:
        entries = _entries(storage, key)
        if entries and entries[0].is_delete_marker:
            report.marker_on_active.append(f"document {doc_id} ({key})")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile the simulated S3 store with CloudVault's tables.")
    parser.add_argument("--fix", action="store_true", help="apply fixes (default: report only)")
    parser.add_argument("--now", type=parse_time, help="evaluate as of this time (ISO 8601, UTC if no offset)")
    args = parser.parse_args(argv)

    from app.db import SessionLocal
    from app.storage import get_storage

    report = reconcile(SessionLocal, get_storage(), fix=args.fix, now=args.now)
    print("\n".join(report.lines()))
    print("clean" if report.clean else ("fixed" if args.fix else "issues found (run with --fix to apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
