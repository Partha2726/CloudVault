"""Durable processing worker (doc 15 AM-7; replaces S3 -> Lambda, doc 08).

The `processing_jobs` table is the queue. Nothing lives only in memory, so a restart
loses nothing. One delivery of one job:

  1. claim   (short txn) SELECT ... FOR UPDATE SKIP LOCKED one PENDING job whose lease is
             free or expired and whose deliveries are below the cap; set `claimed_at` (the
             lease) and `deliveries + 1`; read what the delivery needs; commit.
  2. work    (no txn)    size gate from the stored size, read the exact stored version,
             run the pure extractor (app/processing/extract.py).
  3. finish  (short txn) write the result only if the job is still PENDING and still
             carries this delivery's lease (`claimed_at` and `deliveries` unchanged).

Outcomes:
- Deterministic results (doc 08.3) end the job: SUCCEEDED, SKIPPED or FAILED.
- The stored version is gone (the store answers NoSuchVersion while the version row
  still names that store id): the version is marked S3_MISSING (doc 02.2) and the job
  FAILED with error_code S3_MISSING. If the row's store id changed meanwhile (a
  concurrent Apply replaced the copy), nothing is marked; the lease is released so the
  job is read again with the new id.
- The version is not stored any more (state S3_MISSING): job FAILED with error_code
  S3_MISSING, no storage call. (Versions have no other non-stored state, AM-9.)
- Transient errors (storage failure, database error while working or finishing): the job
  stays PENDING; another delivery claims it when the lease expires. After
  MAX_DELIVERIES (one attempt plus two retries, like S3 -> Lambda) it is no longer
  claimed; the UI shows it as stalled after 10 minutes and T18's retry resets it.
- A second delivery of the same job (lost lease, restart) cannot overwrite a result: the
  finish step matches no row and is a logged no-op (doc 10 C4).
"""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion, ProcessingJob
from app.processing.extract import MAX_ERROR_CHARS, MAX_EXCERPT_CHARS, ExtractionResult, extract
from app.storage.base import MethodNotAllowed, NoSuchKey, NoSuchVersion, ObjectStorage

logger = logging.getLogger("cloudvault.worker")

LEASE_SECONDS = 120
MAX_DELIVERIES = 3


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Claim:
    """Everything one delivery needs, read inside the claim transaction."""

    job_id: uuid.UUID
    version_id: uuid.UUID
    claimed_at: datetime
    deliveries: int
    key: str
    store_version_id: str | None
    version_state: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class Outcome:
    job_id: uuid.UUID
    result: str  # SUCCEEDED / SKIPPED / FAILED, or "transient", "lost" (finish matched nothing), "reread"


class ProcessingWorker:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        storage: ObjectStorage,
        *,
        poll_seconds: float = 2.0,
        max_process_bytes: int = 5_242_880,
        lease_seconds: int = LEASE_SECONDS,
        max_deliveries: int = MAX_DELIVERIES,
        clock: Callable[[], datetime] = _utcnow,
        extractor: Callable[..., ExtractionResult] = extract,
    ):
        self._sessions = session_factory
        self._storage = storage
        self._poll = poll_seconds
        self._max_bytes = max_process_bytes
        self._lease = timedelta(seconds=lease_seconds)
        self._max_deliveries = max_deliveries
        self._clock = clock
        self._extract = extractor
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle ----

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cloudvault-processing-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                did_work = self.run_once() is not None
            except Exception:
                logger.exception("Processing worker iteration failed; continuing")
                did_work = False
            if not did_work:
                self._stop.wait(self._poll)

    # ---- one delivery ----

    def run_once(self) -> Outcome | None:
        """Claim and process at most one job. Returns None when nothing is claimable."""
        claim = self.claim()
        if claim is None:
            return None
        return self.process(claim)

    def claim(self) -> Claim | None:
        now = self._clock()
        with self._sessions() as s, s.begin():
            job = s.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.status == "PENDING",
                    ProcessingJob.deliveries < self._max_deliveries,
                    (ProcessingJob.claimed_at.is_(None)) | (ProcessingJob.claimed_at < now - self._lease),
                )
                .order_by(ProcessingJob.created_at, ProcessingJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.claimed_at, job.deliveries = now, job.deliveries + 1
            row = s.execute(
                select(DocumentVersion, Document.s3_key)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(DocumentVersion.id == job.version_id)
            ).one()
            version, key = row
            return Claim(
                job_id=job.id,
                version_id=version.id,
                claimed_at=now,
                deliveries=job.deliveries,
                key=key,
                store_version_id=version.s3_version_id,
                version_state=version.state,
                content_type=version.content_type,
                size_bytes=version.size_bytes,
            )

    def process(self, claim: Claim) -> Outcome:
        try:
            result = self._work(claim)
        except _Reread:
            self._release(claim)
            return Outcome(claim.job_id, "reread")
        except Exception:
            # Storage failure or similar: leave the job PENDING for the next delivery.
            logger.warning("Delivery %d of job %s failed transiently", claim.deliveries, claim.job_id, exc_info=True)
            return Outcome(claim.job_id, "transient")
        try:
            applied = self.finish(claim, result)
        except Exception:
            logger.warning("Could not record the result of job %s; it will be delivered again", claim.job_id,
                           exc_info=True)
            return Outcome(claim.job_id, "transient")
        if not applied:
            logger.info("Job %s was finished or reclaimed elsewhere; result discarded", claim.job_id)
            return Outcome(claim.job_id, "lost")
        logger.info("Job %s %s", claim.job_id, result.status)
        return Outcome(claim.job_id, result.status)

    def _work(self, claim: Claim) -> ExtractionResult:
        if claim.version_state != "ACTIVE":  # S3_MISSING: the only other version state (AM-9)
            return ExtractionResult(status="FAILED", error_code="S3_MISSING",
                                    error_message=f"Version is not stored (state {claim.version_state})")
        if claim.size_bytes > self._max_bytes:  # gate before any read (doc 08.2)
            return self._extract(claim.content_type, b"", size_bytes=claim.size_bytes, max_bytes=self._max_bytes)
        try:
            _, data = self._storage.get_object(claim.key, claim.store_version_id)
        except (NoSuchVersion, NoSuchKey, MethodNotAllowed) as exc:
            if not self._mark_missing(claim):
                raise _Reread from exc  # the row moved on (e.g. Apply); read again
            return ExtractionResult(status="FAILED", error_code="S3_MISSING",
                                    error_message="The stored version no longer exists")
        return self._extract(claim.content_type, data, size_bytes=claim.size_bytes, max_bytes=self._max_bytes)

    def _mark_missing(self, claim: Claim) -> bool:
        """Mark S3_MISSING only if the row still names the store id we failed to read."""
        with self._sessions() as s, s.begin():
            changed = s.execute(
                update(DocumentVersion)
                .where(
                    DocumentVersion.id == claim.version_id,
                    DocumentVersion.s3_version_id == claim.store_version_id,
                    DocumentVersion.state.in_(("ACTIVE", "S3_MISSING")),
                )
                .values(state="S3_MISSING")
            ).rowcount
        return changed == 1

    def finish(self, claim: Claim, result: ExtractionResult) -> bool:
        """Record a final result; True only if this delivery still owned the job."""
        with self._sessions() as s, s.begin():
            changed = s.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == claim.job_id,
                    ProcessingJob.status == "PENDING",
                    ProcessingJob.claimed_at == claim.claimed_at,
                    ProcessingJob.deliveries == claim.deliveries,
                )
                .values(
                    status=result.status,
                    error_code=result.error_code,
                    error_message=(result.error_message or None) and result.error_message[:MAX_ERROR_CHARS],
                    page_count=result.page_count,
                    word_count=result.word_count,
                    text_excerpt=(result.text_excerpt or None) and result.text_excerpt[:MAX_EXCERPT_CHARS],
                    finished_at=self._clock(),
                )
            ).rowcount
        return changed == 1

    def _release(self, claim: Claim) -> None:
        """Give the lease back at once (the delivery still counts)."""
        with self._sessions() as s, s.begin():
            s.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == claim.job_id, ProcessingJob.status == "PENDING",
                       ProcessingJob.claimed_at == claim.claimed_at)
                .values(claimed_at=None)
            )


class _Reread(Exception):
    """The version row changed under the delivery; release and process again."""
