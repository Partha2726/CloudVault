# 15. Approved Amendments

> **CloudVault is a functional simulation of Amazon S3. It reproduces selected S3 concepts and semantics locally using PostgreSQL-backed simulated object storage. A real AWS account is not required.**

This document records changes to docs 01 to 14 that the project owner approved after the original specification was written. **Where an amendment and an earlier document disagree, the amendment wins.** Affected sections of the earlier documents carry a short note pointing here. Docs 01 to 14 were written for a real AWS deployment; read every mention of the real S3 bucket, IAM, Lambda, CloudWatch, the AWS Console or AWS billing through AM-7 below. The same holds for the diagrams in `docs/diagrams/`: `01`, `02`, `03`, `07` and `11` still draw the original real-AWS design (bucket, IAM user, Lambda, CloudWatch), and `03` and `10` predate AM-9. They are kept as the original specification; the About page draws the accepted architecture.

Dates are the owner's approval dates. Implementation status lives in `IMPLEMENTATION_PLAN.md`.

## 15.1 AM-7: CloudVault is a functional S3 simulation (2026-10-05)

**Why.** The assignment brief asks students to "simulate the selected AWS service by developing a functional website" and to "implement the core functionality of the selected AWS service in their own application"; the rubric asks the site to "simulate the major functionality" of the service. It does not require a real AWS account, real S3 API calls, a real bucket, or any AWS usage.

**Replaces:** every dependency on a real AWS account in docs 01 to 14: the real S3 bucket and `setup_s3.py` (doc 02.2, 11, 12 T4), boto3 and the IAM user (doc 09.1, 11.3), AWS Lambda, S3 event notifications and CloudWatch (doc 08, 12 T16 to T18), AWS cost control and teardown (doc 11.2), the `-m aws` test suite (doc 10), and "show it in the AWS Console" demo steps (doc 01.2, 12.4, 13.1).

### Original specification concept and accepted simulation

The original requirements are kept in docs 01 to 14 as written. This table says what each one became; nothing in CloudVault connects to AWS, uses boto3 or moto, needs AWS credentials, creates AWS resources, or depends on AWS billing, the Free Tier or AWS pricing.

| Original specification (docs 01 to 14) | Accepted CloudVault implementation | Why the original no longer applies |
|---|---|---|
| Private, versioned S3 bucket in `ap-south-1`, created by `infrastructure/setup_s3.py` (doc 02.2, 12 T4) | One simulated bucket in PostgreSQL (`sim_object_versions`), versioning always on | The brief asks for a simulation; no AWS account is used |
| boto3 `s3_service.py`, IAM user `cloudvault-backend`, bucket policy, Block Public Access, SSE-S3 (doc 02, 09.1, 11.3) | `ObjectStorage` interface with `PostgresObjectStorage`; "private" means reachable only through an owner check or a signed link | No AWS credentials or IAM exist to configure |
| Presigned S3 GET URL, 120 s, VersionId-bound (doc 03 W3) | HMAC-signed link to `GET /api/sim-s3/{bucket}/{key}`, 120 s, version-bound | Same contract, signed by the application instead of AWS SigV4 |
| S3 `ObjectCreated:Put` to Lambda `cloudvault-processor`, internal callback, CloudWatch Logs (doc 08, 12 T16 to T18) | Durable `processing_jobs` queue with an in-process worker | No Lambda or event notifications exist; the job row is the trigger |
| Lifecycle rules configured on the bucket (doc 02.2) | `python -m app.scripts.lifecycle` over the simulated store | No bucket to configure; rules are applied to stored timestamps |
| STANDARD, STANDARD_IA, GLACIER_IR as billed AWS classes; cost control, Budget, teardown (doc 07, 11.2) | Simulated storage classes; Apply copies within the simulated store | Nothing is billed; doc 07.2 thresholds keep their AWS rationale only as explanation |
| `pytest -m aws` suite against a real bucket (doc 10) | Tests against the simulated store on local PostgreSQL | No AWS to test against |
| "Show it in the AWS Console" demo and Definition of Done items (doc 01.2, 12.4, 13.1) | In-app S3 Inspector ("Live from simulated S3") | No Console exists for a simulated bucket |
| `VERIFY` items about AWS account, region, pricing and free tiers (doc 14.5) | `docs/VERIFIED.md` checks only the S3 behaviors the simulation copies | Account, billing and pricing questions do not arise |

### Labels (replaces the doc README label table and AGENTS.md rule 2)

| Label | Meaning |
|---|---|
| `[S3-SIM]` | CloudVault's simulation of a real Amazon S3 behavior, modeled on the AWS documentation (`docs/VERIFIED.md`) |
| `[APP]` | CloudVault application logic that S3 itself does not provide (version numbers, trash view, access log, recommendations, dashboard, duplicate detection) |
| `[UI]` | Interface representation only |

The product, README, About page and demo always say "simulated S3" and never imply that the application makes real AWS calls.

### Simulated object store (decision A)

- Object bytes and S3 object state live in PostgreSQL, behind an `ObjectStorage` interface (`backend/app/storage/`). The only implementation is `PostgresObjectStorage`. A real S3 adapter is a possible future extension and is not built.
- New table `sim_object_versions`, one row per object version or delete marker: bucket, key, version id, delete-marker flag, bytes, size, content type, ETag, SHA-256 checksum, storage class, user metadata, tags, last-modified time. These tables simulate S3; the six application tables of doc 04 remain the application's own state.
- Uploaded bytes are never written to local disk.
- One simulated bucket, name from `SIM_BUCKET_NAME`, versioning always enabled. "Block Public Access" is simulated by the rule that objects are reachable only through signed links.
- Total simulated storage is capped by `SIM_STORAGE_LIMIT_BYTES` (default 300 MiB, sized for a free database tier), counting the bytes of every stored version. A write that would exceed it fails with 507 `STORAGE_LIMIT_EXCEEDED`. The per-file limit stays 10 MiB (doc 05.3); there is no other per-file limit.
- The S3 Inspector (`GET /documents/{id}/s3-info`) reads the simulated store; its `source` field is `"simulated-s3"` instead of `"live-from-s3"`, and the UI badge reads "Live from simulated S3".
- Every storage operation runs in its own short transaction, separate from the application's transaction, so AM-1 applies unchanged.
- Simulated behaviors (each checked against AWS documentation in `docs/VERIFIED.md`): a plain delete adds a delete marker; delete by version id removes exactly that version or marker; removing the current marker makes the previous version current; copying onto the same key creates a new version and can set the storage class; HEAD omits the storage class for STANDARD; ETag of a single-part upload is the MD5 of the bytes; the SHA-256 checksum is verified on write. A copy with no storage class is stored as STANDARD (so a restored version is STANDARD); tags and metadata are copied.

### Signed download links (decision B; replaces presigned S3 URLs)

- `GET /api/documents/{id}/download` returns `{url, expires_in}` as before. The URL points at the application's own route `GET /api/sim-s3/{bucket}/{key}` with query parameters `versionId`, `filename`, `expires` and `signature`.
- `signature` is an HMAC-SHA256, keyed by `SIM_SIGNING_SECRET`, over the bucket, key, version id, filename and expiry. Default expiry is 120 s (`PRESIGN_EXPIRY_SECONDS`).
- The signed route needs no login. It serves the bytes of exactly that version with `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store`.
- A missing, altered or expired signature returns 403 `ACCESS_DENIED` (S3 answers an expired presigned URL with 403 AccessDenied). A version that no longer exists returns 404 `NOT_FOUND`.
- Issuing the link is local signing with no storage call (AM-4). The access log is still written when the link is issued (doc 03 W9).
- `PUBLIC_API_BASE_URL` is the absolute backend origin used to build the link.

### Document processing (decision C; replaces AWS Lambda and S3 event notifications)

- `processing_jobs` is the durable queue. The transaction that makes a version `ACTIVE` also inserts its `PENDING` job, so no version exists without its job.
- An in-process worker (`PROCESSING_WORKER_ENABLED`, polling every `PROCESSING_POLL_SECONDS`) claims one `PENDING` job at a time with `SELECT ... FOR UPDATE SKIP LOCKED`, records a lease (`claimed_at`) and counts the delivery (`deliveries`), then runs the doc 08 extraction (size gate 5 MB, pdf/txt/md/csv/docx, images skipped) and writes the result only if the job is still `PENDING`.
- Deterministic outcomes (doc 08.3) end the job as `SUCCEEDED`, `SKIPPED` or `FAILED`. A transient error leaves it `PENDING`; it is claimed again after the lease (120 s) expires. After 3 deliveries (one attempt plus two retries, as S3 to Lambda would do) the worker stops claiming it; the UI shows "Stalled" after 10 minutes.
- A restart loses nothing: an unfinished job is still `PENDING` in the database and its lease expires.
- Duplicate processing is a no-op (C4): the result is applied only to a `PENDING` job.
- `ObjectCreated:Put` remains a domain concept (the store reports it, the Inspector and logs can show it), but the job row is the trigger.
- Retry (W16) resets a `FAILED` or stalled job to `PENDING`, adds 1 to `attempts`, and sets `deliveries` to 0. The worker then picks it up.
- Removed: the Lambda function, `lambda/`, the internal callback `POST /internal/processing-results`, `INTERNAL_WEBHOOK_SECRET`, `LAMBDA_FUNCTION_NAME`, and error `VERSION_NOT_REGISTERED` (a job can no longer arrive before its version).
- New columns on `processing_jobs`: `claimed_at` (nullable) and `deliveries` (int, default 0).
- Two job error codes beyond doc 08.3 (T17): `S3_MISSING` when the stored version no longer exists (the version is also marked `S3_MISSING`), and `VERSION_UNAVAILABLE` when a job's version is not in a stored state (withdrawn by AM-9: a version is always stored or `S3_MISSING`, so the worker reports `S3_MISSING` only; old job rows may still carry the code). Retry (T18) restarts the job's `created_at`, so the 10-minute stall clock starts over.

### Lifecycle rules (decision D)

- `python -m app.scripts.lifecycle [--now ISO-8601] [--dry-run]` applies the doc 02.2 rules to the simulated store: expire noncurrent versions 90 days after they became noncurrent, then remove delete markers that have no versions left behind them. The abort-incomplete-multipart rule has nothing to act on (no multipart) and is listed as not applicable.
- Results depend only on stored timestamps and `--now`, so tests and the demo never wait 90 days.
- Lifecycle does not touch application tables. A version it removes is later marked `S3_MISSING` (version state) and answered with 410 `VERSION_EXPIRED` (error code), exactly as doc 02.2 describes; `reconcile` marks it.

### Storage classes (decision E; AM-3 withdrawn)

- STANDARD, STANDARD_IA and GLACIER_IR are simulated storage classes. Recommendation, refresh, dismiss and **Apply** work in full: Apply copies the object onto the same key with the target class (new version in the store), updates the version row, marks the recommendation `APPLIED`, then deletes the old version (doc 03 W11, doc 07.6, owner decision of 2026-10-04).
- Tests I10 and I11 and the doc 12.4 Definition of Done item apply, read as "the simulated storage class changes and the old simulated version is removed".
- The AM-3 cost-policy block, `ALLOW_PAID_STORAGE_CLASS_CHANGES` and error `AWS_COST_POLICY` are withdrawn.

### Configuration (replaces doc 11.4 AWS and Lambda variables)

Removed: `AWS_REGION`, `S3_BUCKET`, `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `LAMBDA_FUNCTION_NAME`, `INTERNAL_WEBHOOK_SECRET`, `BACKEND_WEBHOOK_URL`. Added: `STORAGE_BACKEND=postgres`, `SIM_BUCKET_NAME`, `SIM_STORAGE_LIMIT_BYTES`, `SIM_SIGNING_SECRET`, `PUBLIC_API_BASE_URL`, `PROCESSING_WORKER_ENABLED`, `PROCESSING_POLL_SECONDS`, `MAX_PROCESS_BYTES`. Production requires strong, distinct `JWT_SECRET` and `SIM_SIGNING_SECRET`, `DATABASE_URL` with `sslmode=require`, and an `https` `PUBLIC_API_BASE_URL`.

### Error codes (doc 05.2)

| Change | Code | HTTP | Meaning |
|---|---|---|---|
| Added | `ACCESS_DENIED` | 403 | Signed download link missing, altered or expired (simulated S3 AccessDenied). The "404, never 403" rule for other users' resources still holds |
| Added | `STORAGE_LIMIT_EXCEEDED` | 507 | The simulated store's total size limit would be exceeded |
| Kept | `STORAGE_ERROR` | 502 | Failure inside the storage layer |
| Unused | `STORAGE_FORBIDDEN` | 502 | Kept for a future real S3 adapter; the simulated store has no permission errors |
| Removed | `VERSION_NOT_REGISTERED` | 409 | No external callback exists any more |

### Deployment (replaces doc 11.1 to 11.3 AWS parts)

Vercel (frontend), Render (backend web service with the in-process worker), Neon (PostgreSQL for application tables and the simulated store). No AWS account, IAM, Budget or teardown steps. The Neon direct (non-pooled) connection string is used because of AM-1's advisory locks.

### Verification (decision H; replaces doc 14.5)

`docs/VERIFIED.md` records only the AWS behaviors the simulation copies, each with an AWS documentation link and date. No AWS account is needed.

## 15.2 AM-1: Storage calls never run inside an application transaction (2026-10-05)

**Replaces:** doc 03 section 3.5 (row lock held across the S3 call), W2, W4 to W6, W11 transaction steps; doc 04 `documents.status`, `document_versions.s3_version_id` and `state`; doc 09.3 "transaction held open across the PUT"; diagrams `03-upload-sequence`, `06-apply-recommendation-sequence`, `10-state-machines` (document status).

> **Superseded in part by AM-9 (2026-10-06):** the `PENDING` and `FAILED` version states, the nullable `document_versions.s3_version_id`, the version-row steps of W2, W5 and W6, the version-number gaps and the reconcile finalization of `PENDING` versions below no longer apply. The document-level states, advisory locks, `pending_op` recovery and the Apply steps stay as written.

**Rule.** An application transaction or row lock is never held open while a storage call runs. Each write goes **PENDING, then the storage operation, then ACTIVE (available) or FAILED**, with short transactions before and after. This keeps the domain code correct for any `ObjectStorage` backend.

**Per-document serialization.** Operations that must keep document and storage order in step (upload of a new version, delete, undelete, permanent delete, restore, apply) take a PostgreSQL session-level advisory lock for that document (`pg_advisory_lock`) on a dedicated pooled connection, with no transaction open, and hold it for the whole logical operation including the storage call. The lock is released and the connection returned to the pool in a `finally` block, even on errors, so locks and connections cannot leak. Concurrent requests on one document queue; both succeed (doc 10 C1, C2). Production uses Neon's direct connection string, because session advisory locks do not work through transaction-mode connection pooling. Concurrency tests cover competing uploads and competing deletes.

*Implementation note (T8, 2026-10-05).* The lock connection comes from a separate, bounded pool (`app/locks.py`: 5 connections plus up to 15 overflow, 10 s checkout timeout, AUTOCOMMIT), not from the main application pool. Reason: an operation holds its lock connection while it also needs a main-pool connection (the store call and the finalizing transaction). With one shared pool, enough concurrent operations could each hold a lock connection and wait for a second connection that never frees up (pool starvation deadlock). With two pools and the rule "commit or close the request session before taking the lock", a lock waiter holds no main-pool connection, and main-pool users never wait for the lock pool, so no wait cycle is possible. Waiting for a busy document is bounded by the 30 s statement timeout. Tested in `tests/integration/test_document_concurrency.py`.

*Implementation note (T10, 2026-10-05): recovery of interrupted operations.* Because the document lock is a session advisory lock, a crashed process releases it. So a `pending_op` found while holding the lock always belongs to an interrupted operation, and it is resolved first, from the store's actual state: `DELETE` is finished if the latest stored entry is a delete marker, otherwise dropped; `UNDELETE` is finished if the recorded marker no longer exists, otherwise dropped; `PURGE` stays until a permanent delete completes, and undelete is refused meanwhile (409 `DOCUMENT_DELETED`). A failed final transaction leaves `pending_op` set for this roll-forward instead of undoing the store change. The one rollback is an undelete that collides with a newer same-name document: a new delete marker is added and 409 `NAME_EXISTS` is returned. `reconcile` (T19) remains the backstop for documents nobody touches again.

*Implementation note (T14, 2026-10-05): Apply and recovery of `pending_op='APPLY'`.* Apply runs under the document lock in five steps: (1) re-read the recommendation and document, re-run the engine, record `pending_op='APPLY'` with `pending_op_at`; (2) copy the current stored version onto the key with the target class; (3) one transaction points the existing version row at the copy (same row and number, new store id, class, `storage_class_changed_at`) and marks the recommendation `APPLIED`; (4) delete the old stored version; (5) clear `pending_op`. The application never points at a deleted version: the old version is removed only after step 3 committed. Recovery runs first in any later operation on the document and decides only from DB and store state:
- **A** (crash after 1): no copy in the store; the intent is dropped and the recommendation stays `OPEN`.
- **B** (after 2): the copy is recognised only if it is the latest stored entry for the key, referenced by no version row, not a delete marker, has the current version's ETag and the open recommendation's target class, and was written at or after `pending_op_at`; it is adopted (step 3), then steps 4 and 5 run. Nothing else is ever adopted.
- **C** (after 3): stored versions that no version row references, are not delete markers, carry the current version's ETag and are older than the current stored version are deleted; then step 5.
- **D** (after 4): step 5 only.
A failed step 3 is reported (503) and rolled forward by the next operation, including a retried Apply, which then returns 200 `APPLIED`. Failures in steps 4 and 5 are logged and left to recovery; the Apply still returns 200 because it has taken effect. `refresh` row-locks the documents it evaluates and skips any with a `pending_op`, so an Apply in flight keeps its `OPEN` recommendation.

**Schema changes (doc 04).**

| Table.column | Change |
|---|---|
| `documents.status` | `PENDING`, `ACTIVE`, `DELETED`, `FAILED` (default `PENDING`) |
| `documents` name index | Partial unique index covers `status IN ('PENDING','ACTIVE')`, so a document being uploaded reserves its name |
| `documents.pending_op`, `pending_op_at` | Nullable. In-flight document-level storage operation: `DELETE`, `UNDELETE`, `PURGE`, `APPLY`. Used for crash recovery by `reconcile` |
| `document_versions.state` | *(Superseded by AM-9: `ACTIVE`, `S3_MISSING`, default `ACTIVE`.)* `PENDING`, `ACTIVE`, `FAILED`, `S3_MISSING` (default `PENDING`). `ACTIVE` is the available state; the API `state` field keeps that name |
| `document_versions.s3_version_id` | *(Superseded by AM-9: NOT NULL.)* Nullable, with CHECK: required unless `state` is `PENDING` or `FAILED`. Holds the simulated store's version id |

Integrity checks: a document in `ACTIVE` or `DELETED` has a `current_version_id`; `deleted_at` and `delete_marker_version_id` are set exactly when `status='DELETED'`; `sha256` is 64 lowercase hex characters; a job's `finished_at` is set exactly when it is not `PENDING`; a recommendation's `resolved_at` is set exactly when it is not `OPEN`, and it names one of the three classes and rules.

**Upload (W2).** *(Version-row steps superseded by AM-9.)* (1) Validate. (2) Transaction 1: insert `documents(PENDING)` and `document_versions(v1, PENDING)`; commit. A name clash fails here with 409 `NAME_EXISTS`, before storage. (3) Store the object. (4) Transaction 2: version `ACTIVE` with the store's version id, document `ACTIVE`, `current_version_id`, `processing_jobs(PENDING)`; commit. On storage failure, mark both rows `FAILED` and return the error; nothing is exposed. If transaction 2 fails after the write, delete that exact stored version (best effort); `reconcile` handles leftovers.

**New version, restore, apply (W5, W6, W11).** *(W5 and W6 superseded by AM-9; W11 unchanged.)* Under the document's advisory lock: transaction 1 checks state and records the pending work (a `PENDING` version row with `version_number = max + 1`, or `pending_op='APPLY'`); commit. Then the storage call. Transaction 2 finalizes or marks `FAILED`.

**Readers** (list, detail, download, versions, engine, dashboard) show only `ACTIVE` and `DELETED` documents and only `ACTIVE` versions; the versions list also shows `S3_MISSING`. A failed write can leave a gap in version numbers *(no longer true under AM-9)*.

**Reconcile additions (doc 09.3).** *(The `PENDING`-version part is superseded by AM-9.)* `PENDING` rows older than 1 hour are stale: finalize them if the store holds the matching version (`cv-doc-id` metadata), otherwise mark them `FAILED`. A `pending_op` older than 1 hour is reported, and cleared by `--fix` after checking the store.

## 15.3 AM-2: Restore gets its own processing job (2026-10-05)

**Replaces:** doc 03 W6 "copy the extraction fields from the source job if it succeeded".

*Confirmed by the owner on 2026-10-06* in place of the earlier draft proposal (inherit the source job's terminal result, 409 when the source job is still `PENDING`); that proposal was never adopted and no such error code exists.

- Restore never copies or resumes the source version's job. Historical jobs stay unchanged.
- The restored version gets a new `processing_jobs` row (`PENDING`) in the same transaction that makes it `ACTIVE`; the AM-7 worker processes it. Store events are not involved.
- Traceability: job, then `version_id`, then the version row with `origin=RESTORE` and `restored_from_version`.
- Duplicate safety: one job per version (`processing_jobs.version_id` is unique). Retrying reuses that job and never inserts a second one. Each restore call creates one new version and so one job (restore is not idempotent, doc 05).

## 15.4 AM-3: withdrawn (2026-10-05)

The $0 AWS cost-policy block on Apply is withdrawn by AM-7: no real AWS is used, so the full simulated storage-class workflow applies.

## 15.5 AM-4: Clarifications (2026-10-05)

| Item | Decision | Affects |
|---|---|---|
| Example sizes | Test U1 keeps its 18 MiB input (pure engine test). Seed and demo files are real files between 128 KiB and 10 MiB | doc 05.4, 07.7, 10.2 |
| Folder names | No tracked folder named `lib/` (the Python `.gitignore` template ignores it); use `utils/` or `shared/` | doc 12.1 |
| Nullability | `access_logs.document_id`, `version_id`, `user_id`, `event_type`, `accessed_at` are NOT NULL; `processing_jobs.document_id` is NOT NULL with ON DELETE CASCADE; `access_logs.event_type` allows only `DOWNLOAD` | doc 04 |
| Permanent delete | A repeat after full success returns 404. A repeat after a partial failure (document still `DELETED`) retries the remaining storage cleanup, then removes the rows | doc 05.5 |
| Download link | Issuing the link makes no storage call. 410 `VERSION_EXPIRED` comes from the database `state`; only eligible versions are signed | doc 03 W3, 05.5 |
| Uploads in memory | Multipart bodies are parsed as a stream in memory. FastAPI's `UploadFile` is not used, because it writes parts over 1 MB to a temporary file on disk | doc 05.3, 09.1 |

## 15.6 AM-5: Password length under bcrypt (2026-10-05)

bcrypt stays the locked hashing algorithm (AGENTS.md, doc 04, 09.1, 12 T7). bcrypt only accepts 72 bytes, so a password must be **8 to 128 characters and at most 72 bytes in UTF-8**. A longer password gets 422 `VALIDATION_ERROR` with the message "Password must be at most 72 bytes when UTF-8 encoded". No pre-hashing, no other algorithm. ASCII passwords can therefore be at most 72 characters. Affects doc 05.5 (`POST /auth/register`).

## 15.7 AM-6: INTERNAL_ERROR (2026-10-05)

New error code `INTERNAL_ERROR` (500) for unexpected exceptions, in the standard error body with the generic message "Internal server error". The exception and the request method and path are logged server-side. Clients never see stack traces, exception types or exception text, and request bodies, headers and query strings are never logged. Affects doc 05.2.

## 15.8 AM-8: Security hardening decisions (T24, 2026-10-06)

Doc 09.1 lists the security topics without exact values for some of them. The T24 security pass fixed these values; the owner approved them on 2026-10-06. Affects doc 05.2, 09.1, 10.2 and 11.

| Topic | Decision |
|---|---|
| Request body cap | Every route except the two upload routes rejects a request body over 64 KiB, declared or streamed, with 413 `VALIDATION_ERROR` "Request body is too large". Real JSON bodies are under 1 KiB. The upload routes keep their own streaming cap (10 MiB plus 64 KiB multipart overhead, doc 05.3) |
| Security headers | Every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` (signed links carry their signature in the query string). API responses also: `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` and `Cache-Control: no-store`; a route's own value wins, so the signed route keeps `private, no-store`. `/docs`, `/redoc` and `/openapi.json` skip the CSP so the public API docs keep working. `Strict-Transport-Security: max-age=31536000` only when `APP_ENV=production`. The frontend's own headers are set on Vercel (T26) |
| Rate limits | Login 5/min per client IP and upload 20/min per user (doc 09.1, unchanged). **Added:** register 10/min per client IP, because each call runs bcrypt. A duplicate email still answers 409 `EMAIL_EXISTS` |
| Rate limiter scope | slowapi keeps its counters in memory in each process. The limits are exact only with one backend instance (the Render plan runs one). More instances would each allow the full budget; a shared store would be needed and is out of scope. Behind Render's proxy, uvicorn must run with `--proxy-headers` so limits key on the client address, not the proxy's (T26) |
| CORS origin | `FRONTEND_ORIGIN` is one explicit origin: never `*` or empty, and `https` in production (checked at startup) |
| Signed-link parameters | Only the canonical `expires` the signer writes is accepted (ASCII digits, at most 12, no leading zeros). The signature is compared as bytes. Anything else is 403 `ACCESS_DENIED`, never a server error |
| Integer parameters | `page`, `version` and `version_number` above 2147483647 (PostgreSQL `integer`) are 422 `VALIDATION_ERROR` |
| Access log | Query strings are removed from uvicorn's access-log lines, so signed links never reach the log (doc 09.1, AM-6) |
| Test S4 | The internal endpoint was removed by AM-7. S4 checks that no internal route exists and that every non-public route requires a token |

## 15.9 AM-9: A version row exists only after its store write (2026-10-06)

**Replaces:** the parts of AM-1 marked superseded above. Restores the doc 04 rule that `document_versions.s3_version_id` is NOT NULL, which AM-1 had relaxed.

**Why.** Doc 04 requires `s3_version_id` NOT NULL after commit, while the original W2 flushed the version row before the S3 call and kept the transaction open across it. AM-1 removed the open transaction but solved the conflict by making the column nullable and adding `PENDING`/`FAILED` version states. The owner rejected that: a version row must never exist without a simulated-store version id.

**Rule.** Every persisted `document_versions` row has a non-null `s3_version_id` naming a version in the simulated store (`sim_object_versions.version_id`, itself NOT NULL and unique).

**Upload (W2).**
1. Validate.
2. Transaction 1: insert `documents(PENDING)` and `flush()`; the partial unique index on `PENDING`/`ACTIVE` names rejects a clash with 409 `NAME_EXISTS` before storage; commit. No version row is written.
3. Under the document's advisory lock, store the object with no transaction open.
4. Transaction 2: insert v1 as `ACTIVE` with the returned `s3_version_id`, set `current_version_id`, insert its `PENDING` processing job, document `ACTIVE`; commit.
5. Store failure: the document becomes `FAILED` (name freed), no version row. Transaction 2 failure: delete that exact stored version (best effort), document `FAILED`.

**New version and restore (W5, W6).** Under the document's advisory lock: a check transaction validates state and inputs and writes nothing; the store call (PutObject, or CopyObject from the source version) runs with no transaction open; one finalize transaction allocates `version_number = max + 1`, inserts the `ACTIVE` version with its store id, makes it current and inserts its new `PENDING` job (AM-2). A store failure writes nothing; a finalize failure deletes the stored version it just created (it is the key's latest under the lock). Version numbers have no gaps.

**Apply (W11).** Unchanged (AM-1 implementation note T14): the existing row keeps its `version_number` and gets the copy's store id, class and `storage_class_changed_at`.

**Schema (doc 04, migration `0003`).** `document_versions.s3_version_id` NOT NULL; `state` is `ACTIVE` or `S3_MISSING` (default `ACTIVE`); the AM-1 CHECK `ck_versions_s3_id_when_stored` and the partial index on `PENDING` versions are dropped. The migration first deletes any rows left in the withdrawn `PENDING`/`FAILED` states; such rows were never current, listed or referenced by a job, access log or recommendation. Document states (`PENDING`, `ACTIVE`, `DELETED`, `FAILED`) are unchanged.

**Recovery.** A crash between the store write and transaction 2 leaves no version row. `reconcile` marks a `PENDING` document older than 1 hour `FAILED` (freeing its name), and the object the crashed write left is an unreferenced stored version, deleted by `reconcile --fix` after 1 hour as doc 09.3 originally specified. A stored object is never adopted into a version row after the fact.

**Worker.** Job error code `VERSION_UNAVAILABLE` (AM-7) is withdrawn for new jobs; a job whose version is not stored ends `FAILED` with `S3_MISSING`.

