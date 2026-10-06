"""Demo seed: real sample documents with backdated history (doc 07.7; AM-4, AM-7).

    python -m app.scripts.seed_demo [--email EMAIL] [--password PASSWORD] [--reset]

Uploads real files (128 KiB to 10 MiB, AM-4) through the same services the API uses, then
backdates their creation dates, class-change dates and access history so CloudVault's
heuristic has something to recommend. The backdating is applied consistently to the
application tables and the simulated store's timestamps. The demo and README must
disclose it: real uploads are never 30+ days old at demo time.

Outcome, as evaluated by the T13 engine:
- "Annual report 2023 (sample).pdf": STANDARD, 150 days old, never downloaded  -> R2 (GLACIER_IR)
- "Meeting minutes Q1 (sample).txt": STANDARD, 120 days old, 1 download 40 days ago -> R3 (STANDARD_IA)
- "Archive index (sample).csv": STANDARD_IA for 60 days, 4 downloads this month -> R1 (STANDARD)
- "Project plan (sample).md": recent, two versions, downloaded -> no recommendation
- "Budget FY26 (sample).csv": recent, small -> no recommendation
"""

import argparse
import io
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.locks import document_lock
from app.models import AccessLog, Document, DocumentVersion, User
from app.security import hash_password
from app.services.document_service import create_document
from app.services.validation import validate_upload
from app.services.version_service import upload_version
from app.storage.base import ObjectStorage

DEFAULT_EMAIL = "demo@cloudvault.example"
DEFAULT_PASSWORD = "cloudvault-demo-1"  # demo account on a local or demo deployment only


@dataclass(frozen=True)
class SeedResult:
    email: str
    documents: dict[str, str]  # name -> document id


def _pdf(text_lines: list[str], target_bytes: int) -> bytes:
    """A valid PDF with real text, padded with PDF comments to reach the target size."""
    content = "BT /F1 12 Tf 72 740 Td 14 TL " + " ".join(f"({line}) '" for line in text_lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    padding = max(0, target_bytes - 1200)
    while padding > 0:  # comment lines are ignored by PDF readers
        chunk = min(padding, 100)
        out.write(b"%" + b"x" * (chunk - 2) + b"\n")
        padding -= chunk
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _text(lines: list[str], target_bytes: int) -> bytes:
    body = "\n".join(lines) + "\n"
    repeats = max(1, target_bytes // len(body.encode()) + 1)
    return (body * repeats).encode()[:target_bytes]


def sample_files() -> dict[str, bytes]:
    """Synthetic sample content (labelled "(sample)" in every name)."""
    return {
        "Annual report 2023 (sample).pdf": _pdf(
            ["CloudVault sample annual report 2023", "Revenue, costs and outlook", "Synthetic demo document"],
            300 * 1024,
        ),
        "Meeting minutes Q1 (sample).txt": _text(
            ["Meeting minutes, first quarter (sample).", "Attendees discussed the storage migration plan."],
            200 * 1024,
        ),
        "Archive index (sample).csv": _text(
            ["box,folder,title,year", "1,3,Correspondence (sample),2019", "2,7,Plans and drawings (sample),2020"],
            250 * 1024,
        ),
        "Project plan (sample).md": _text(
            ["# Project plan (sample)", "", "- Milestone 1: upload documents", "- Milestone 2: review classes"],
            150 * 1024,
        ),
        "Budget FY26 (sample).csv": _text(["item,amount", "Storage,120.00", "Tools,45.50"], 140 * 1024),
    }


def _ensure_user(db: Session, email: str, password: str, reset: bool, storage: ObjectStorage) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        user = User(email=email.lower(), password_hash=hash_password(password))
        db.add(user)
        db.commit()
        return user
    docs = db.execute(select(Document.id, Document.s3_key).where(Document.owner_id == user.id)).all()
    db.commit()
    if docs and not reset:
        raise SystemExit(f"{email} already has documents; rerun with --reset to replace them")
    for doc_id, key in docs:  # --reset: remove the demo user's documents entirely
        with document_lock(doc_id):
            storage.delete_all_versions(key)
            db.execute(delete(Document).where(Document.id == doc_id))
            db.commit()
    return user


def _backdate(db: Session, doc_id, *, created: datetime, class_changed: datetime | None = None) -> None:
    """Backdate the current version in the DB and its stored object in the simulated store, together."""
    doc = db.get(Document, doc_id, populate_existing=True)
    version = db.get(DocumentVersion, doc.current_version_id, populate_existing=True)
    version.created_at = created
    version.storage_class_changed_at = class_changed or created
    db.execute(
        text("UPDATE sim_object_versions SET last_modified = :t WHERE version_id = :v"),
        {"t": class_changed or created, "v": version.s3_version_id},
    )
    db.commit()


def _log_downloads(db: Session, doc_id, user_id, days_ago: list[int], now: datetime) -> None:
    doc = db.get(Document, doc_id, populate_existing=True)
    for d in days_ago:
        db.add(AccessLog(document_id=doc.id, version_id=doc.current_version_id, user_id=user_id,
                         accessed_at=now - timedelta(days=d)))
    db.commit()


def _change_class(db: Session, storage: ObjectStorage, doc_id, storage_class: str) -> None:
    """Place the current version in another simulated class, the way Apply does (copy, adopt, delete old)."""
    with document_lock(doc_id):
        doc = db.get(Document, doc_id, populate_existing=True)
        version = db.get(DocumentVersion, doc.current_version_id, populate_existing=True)
        key, old = doc.s3_key, version.s3_version_id
        db.commit()
        copied = storage.copy_object(key, old, storage_class=storage_class)
        version = db.get(DocumentVersion, version.id, populate_existing=True)
        version.s3_version_id, version.storage_class = copied.version_id, storage_class
        db.commit()
        storage.delete_version(key, old)


def seed(
    session_factory: Callable[[], Session],
    storage: ObjectStorage,
    *,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    reset: bool = False,
    now: datetime | None = None,
) -> SeedResult:
    now = now or datetime.now(UTC)
    ids: dict[str, str] = {}
    with session_factory() as db:
        user = _ensure_user(db, email, password, reset, storage)
        for name, data in sample_files().items():
            result = create_document(db, storage, user, validate_upload(name, data))
            ids[name] = str(result.document.id)

        def doc(name):
            return ids[name]

        # Project plan: a second version and recent downloads (active use, no recommendation).
        plan_v2 = sample_files()["Project plan (sample).md"].replace(b"Milestone 2", b"Milestone 2 (revised)")
        upload_version(db, storage, user, doc("Project plan (sample).md"),
                       validate_upload("Project plan (sample).md", plan_v2))
        _log_downloads(db, doc("Project plan (sample).md"), user.id, [1, 3], now)

        # R2: old and never downloaded.
        _backdate(db, doc("Annual report 2023 (sample).pdf"), created=now - timedelta(days=150))
        # R3: old, one download 40 days ago.
        _backdate(db, doc("Meeting minutes Q1 (sample).txt"), created=now - timedelta(days=120))
        _log_downloads(db, doc("Meeting minutes Q1 (sample).txt"), user.id, [40], now)
        # R1: already in STANDARD_IA for 60 days, downloaded four times this month.
        _change_class(db, storage, doc("Archive index (sample).csv"), "STANDARD_IA")
        _backdate(db, doc("Archive index (sample).csv"), created=now - timedelta(days=200),
                  class_changed=now - timedelta(days=60))
        _log_downloads(db, doc("Archive index (sample).csv"), user.id, [2, 6, 11, 20], now)
    return SeedResult(email=email.lower(), documents=ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed CloudVault with backdated sample documents.")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--reset", action="store_true", help="replace the demo user's existing documents")
    args = parser.parse_args(argv)

    from app.db import SessionLocal
    from app.storage import get_storage

    result = seed(SessionLocal, get_storage(), email=args.email, password=args.password, reset=args.reset)
    print(f"Seeded {len(result.documents)} sample documents for {result.email}.")
    print("Disclosure: creation dates, storage-class dates and download history of the seeded documents are")
    print("backdated in the database and the simulated store, so CloudVault's heuristic has old data to")
    print("evaluate (doc 07.7). Run 'Refresh' on the Optimization page to see the recommendations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
