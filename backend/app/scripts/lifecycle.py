"""Simulated S3 lifecycle rules (doc 02.2; doc 15 AM-7; docs/VERIFIED.md row 9).

    python -m app.scripts.lifecycle [--now ISO-8601] [--dry-run]

Rules, applied to every key under documents/:
1. NoncurrentVersionExpiration, 90 days: a version becomes noncurrent when the next newer
   entry for its key (version or delete marker) was written; it is permanently removed 90
   days after that. The current (latest) entry is never touched.
2. ExpiredObjectDeleteMarker: a delete marker with no versions left behind it is removed.
3. AbortIncompleteMultipartUpload: not applicable (no multipart uploads exist).

Results depend only on stored timestamps and --now, so nothing waits 90 days. Only the
simulated store changes; a version removed here is later found as S3_MISSING by the API
or `reconcile` (doc 02.2). Noncurrent delete markers are left to rule 2 (the AWS pages
read for VERIFIED.md describe rule 1 for object versions). Each key is handled under its
document's advisory lock so a live request never sees a half-applied rule.
"""

import argparse
import sys
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import groupby

from app.locks import document_lock
from app.storage.base import ObjectStorage, VersionEntry

NONCURRENT_DAYS = 90
PREFIX = "documents/"


@dataclass
class LifecycleReport:
    expired_versions: list[str] = field(default_factory=list)
    removed_markers: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"expired noncurrent versions: {len(self.expired_versions)}"]
        out += [f"  {x}" for x in self.expired_versions]
        out.append(f"removed expired delete markers: {len(self.removed_markers)}")
        out += [f"  {x}" for x in self.removed_markers]
        out.append("abort incomplete multipart uploads: not applicable")
        return out


def _lock_for(key: str):
    try:
        return document_lock(uuid.UUID(key.rsplit("/", 1)[-1]))
    except ValueError:
        return nullcontext()


def plan_key(entries: list[VersionEntry], now: datetime) -> tuple[list[VersionEntry], VersionEntry | None]:
    """Pure decision for one key. `entries` newest first. Returns (versions to expire, marker to remove)."""
    expire = [
        older
        for newer, older in zip(entries, entries[1:], strict=False)
        if not older.is_delete_marker and now - newer.last_modified >= timedelta(days=NONCURRENT_DAYS)
    ]
    remaining = [e for e in entries if e not in expire]
    marker = remaining[0] if len(remaining) == 1 and remaining[0].is_delete_marker else None
    return expire, marker


def apply_lifecycle(storage: ObjectStorage, *, now: datetime | None = None, dry_run: bool = False) -> LifecycleReport:
    now = now or datetime.now(UTC)
    report = LifecycleReport()
    keys = [k for k, _ in groupby(storage.list_object_versions(PREFIX), key=lambda e: e.key)]
    for key in keys:
        with nullcontext() if dry_run else _lock_for(key):
            entries = [e for e in storage.list_object_versions(key) if e.key == key]  # fresh, under the lock
            expire, marker = plan_key(entries, now)
            for entry in expire:
                if not dry_run:
                    storage.delete_version(key, entry.version_id)
                report.expired_versions.append(f"{key} {entry.version_id} ({entry.last_modified.isoformat()})")
            if marker is not None:
                if not dry_run:
                    storage.delete_version(key, marker.version_id)
                report.removed_markers.append(f"{key} {marker.version_id}")
    return report


def main(argv: list[str] | None = None) -> int:
    from app.scripts.reconcile import parse_time
    from app.storage import get_storage

    parser = argparse.ArgumentParser(description="Apply CloudVault's simulated S3 lifecycle rules.")
    parser.add_argument("--now", type=parse_time, help="evaluate as of this time (ISO 8601, UTC if no offset)")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, change nothing")
    args = parser.parse_args(argv)
    report = apply_lifecycle(get_storage(), now=args.now, dry_run=args.dry_run)
    print("\n".join(report.lines()))
    if args.dry_run:
        print("dry run: nothing changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
