# CloudVault Implementation Plan

> **CloudVault is a functional simulation of Amazon S3. It reproduces selected S3 concepts and semantics locally using PostgreSQL-backed simulated object storage. A real AWS account is not required.**

Working checklist for building CloudVault. It is not the specification.

**Order of authority:** `docs/15-amendments.md` (owner-approved changes, AM-1 to AM-9) overrides `docs/01`-`docs/14` and `docs/diagrams/`; those override this file. `AGENTS.md` ground rules apply throughout. If the spec is silent or contradictory: stop and ask the owner.

## Ground rules applied on every task

- Label features `[S3-SIM]` / `[APP]` / `[UI]`. Never present app logic as S3 behavior; never imply real AWS calls.
- Every S3 behavior the simulation copies is checked against docs.aws.amazon.com and recorded in `docs/VERIFIED.md` before code depends on it. No AWS account.
- No secrets in Git (only `.env.example`). Only a JWT and signed download links reach the browser. The simulated bucket is private.
- Filenames are display names only: never object keys, never disk paths. Uploads and object bytes never touch local disk.
- No application transaction or row lock is held across a storage call; per-document advisory locks serialize writes (AM-1).
- Out of scope (doc 01.3): multipart, KMS, Object Lock, Intelligent-Tiering integration, Glacier Flexible/Deep Archive, sharing, roles, OAuth, email verification, password reset, CloudFront, Terraform, K8s, SQS/SNS, microservices, AI/ML/OCR. Also (AM-7): any real AWS service, boto3, moto.
- Tests need only a local PostgreSQL.
- One task at a time; prerequisites must pass acceptance first.
- Do not claim a feature in README/UI/demo until it is implemented and tested.

## Status tracker

Status: `todo`, `blocked`, `in-progress`, `done`.

| Task | Status | Waiting on |
|---|---|---|
| Amendments AM-1..AM-9 | done (doc 15) | |
| V Verify simulated S3 behaviors (`docs/VERIFIED.md`) | done (10 confirmed, 2 partly) | |
| T1 Repo scaffold | done | |
| T2 Backend skeleton | done | |
| T3 Models and migration | done | |
| T4 Simulated store schema | done | |
| T5 ObjectStorage + simulated backend + signed links | done | |
| T6 Validation | done | |
| T7 Auth (AM-5) | done | |
| T8 Upload and list | done | |
| T9 Download and signed route | done | |
| T10 Delete family | done | |
| T11 Versions and restore | done | |
| T12 S3 Inspector API | done | |
| T13 Engine | done | |
| T14 Rec endpoints (Apply works) | done | |
| T15 Dashboard | done (API; dashboard screen pulled forward from T21) | |
| T16 Extraction module | done | |
| T17 Processing worker (durable queue) | done | |
| T18 Processing endpoints | done | |
| T19 Scripts: reconcile, lifecycle, seed | done | |
| T20 Frontend scaffold | done (login verified in the browser during T15/T21) | |
| T21 Core screens | done | |
| T22 Details tabs | done | T11, T12, T18, T21 |
| T23 Optimization + About | done | T14, T21 |
| T24 Security pass | done | T8-T18 |
| T25 Test completion | done | T24 |
| T26 Deployment | todo | T25 |
| T27 Documentation | done except deployment facts (cold-start time, public URLs) | T26 |
| T28 Demo rehearsal | done (local) | T27 |

Next: T26 deployment (T28 rehearsal done locally first).

## Decision log

Full text in `docs/15-amendments.md`.

| Date | Decision |
|---|---|
| 2026-10-04 | Spec moved to repo root |
| 2026-10-04 | Apply keeps `version_number`; updates `s3_version_id`, `storage_class`, `storage_class_changed_at` on the existing row; deletes the old stored version after commit (best effort) |
| 2026-10-05 | AM-1: PENDING, storage call, ACTIVE/FAILED; no transaction across storage calls; per-document session advisory lock held for the whole operation, connection always returned to the pool; Neon direct connection; concurrency tests for competing uploads and deletes |
| 2026-10-05 | AM-2: restore gets its own new PENDING job |
| 2026-10-05 | AM-3 withdrawn by AM-7 (no cost-policy block) |
| 2026-10-05 | AM-4: seed sizes, no `lib/` folders, NOT NULL FKs, permanent-delete repeats, download link makes no storage call, uploads parsed in memory |
| 2026-10-05 | AM-5: bcrypt stays; passwords 8-128 characters and at most 72 UTF-8 bytes, else 422 |
| 2026-10-05 | AM-6: `INTERNAL_ERROR` (500) |
| 2026-10-05 | AM-7: functional S3 simulation in PostgreSQL: `ObjectStorage` interface, HMAC-signed links, durable job queue with in-process worker, lifecycle script, full simulated storage-class workflow, `[S3-SIM]` labels, `docs/VERIFIED.md`, total storage limit |
| 2026-10-06 | AM-8: T24 security values (body cap, headers, register limit, limiter scope, CORS origin, signed-link parameters, integer bounds, access-log query stripping) |
| 2026-10-06 | AM-2 confirmed by the owner: a restored version gets a new `PENDING` job; nothing is inherited from the source job; no 409 for a `PENDING` source |
| 2026-10-06 | AM-9: a version row is inserted only after its store write; `document_versions.s3_version_id` NOT NULL; version states `ACTIVE`/`S3_MISSING`; migration `0003`; reconcile no longer adopts stored objects into versions; `VERSION_UNAVAILABLE` withdrawn |
| 2026-10-06 | Superseded: the first plan draft (2026-10-04) read the spec as a real-AWS build. Its Phase 0 items are void under AM-7: blocker A3 (Free Tier / paid storage-class cost conflict) rejected as inapplicable, and the AWS safeguards step (named profile `cloudvault-dev`, `aws sts get-caller-identity`, Zero Spend Budget, Free Tier alerts) dropped. CloudVault makes no AWS API calls and has no boto3, real bucket, AWS credentials, profile, billing, Free Tier or pricing dependency. Do not ask the owner for AWS account or budget setup. Draft items A1 (restore job) and A2 (W2 order vs NOT NULL) are resolved by AM-2 (confirmed) and AM-9 (replacing AM-1's nullable column) |

## V. Verify simulated S3 behaviors (`docs/VERIFIED.md`, before T5)

One line per item: behavior, finding, AWS documentation URL, date. Only behaviors the simulation copies:
1. Delete without a version id on a versioning-enabled bucket adds a delete marker and returns its version id.
2. Delete with a version id permanently removes that version or marker; removing the current marker makes the previous version current.
3. GET/HEAD of a key whose current version is a delete marker returns 404; GET/HEAD naming a delete marker's version id returns 405.
4. Copying an object onto its own key in a versioned bucket creates a new version; the storage class can be set in the copy.
5. HEAD omits the storage-class header for STANDARD objects.
6. ETag of a single-part upload (non-KMS) is the hex MD5 of the bytes.
7. A SHA-256 checksum sent on upload is verified; mismatch is rejected.
8. An expired presigned URL is refused with 403 AccessDenied.
9. NoncurrentVersionExpiration counts days from when a version became noncurrent; ExpiredObjectDeleteMarker removes a marker with no noncurrent versions behind it.
10. STANDARD_IA / GLACIER_IR minimum storage duration (30 / 90 days) and minimum billable object size (128 KB), the rationale of the doc 07.2 thresholds.
11. Object tag limit (10 per object) and user-metadata size limit (2 KB), if the store enforces them.
12. Platform terms used in deployment: Neon free-tier storage cap (sets `SIM_STORAGE_LIMIT_BYTES`), Render free-tier spin-down, Vercel Hobby.

## Phase 1: Scaffolding

### T1 Repo scaffold (AM-7 cleanup in progress)
- `backend/`, `frontend/`, `docker-compose.yml` (Postgres 15, host port `${POSTGRES_PORT:-5432}`), `.env.example`, `.gitignore`.
- AM-7: remove `lambda/` and `infrastructure/` placeholders; `.env.example` lists only the AM-7 variables.
- Accept: `docker compose up -d` healthy; `.env`, `node_modules`, `frontend/dist`, `*.nosync` ignored.

### T2 Backend skeleton (AM-7 config in progress)
- `config.py`: AM-7 variables (`STORAGE_BACKEND`, `SIM_BUCKET_NAME`, `SIM_STORAGE_LIMIT_BYTES`, `SIM_SIGNING_SECRET`, `PUBLIC_API_BASE_URL`, `PRESIGN_EXPIRY_SECONDS`, `PROCESSING_WORKER_ENABLED`, `PROCESSING_POLL_SECONDS`, `MAX_PROCESS_BYTES`) plus app, DB, JWT, upload and REC thresholds. No AWS variables. Production validator: strong (32+ chars), distinct `JWT_SECRET` and `SIM_SIGNING_SECRET`; `sslmode=require`; `https` `PUBLIC_API_BASE_URL`.
- Requirements: no `boto3`, no `moto`; `pytest.ini` has no `aws` marker.
- Done already: DB engine (pre-ping, timeouts, UTC), standard error body, 422/401/404/405/429/503 mapping, `INTERNAL_ERROR` middleware (AM-6), CORS, public API docs, `GET /api/health`.
- Startup store check (simulated HeadBucket) runs in the app lifespan.

## Phase 2: Database

### T3 Models and migration (done)
- Six application tables (doc 04 + AM-1 + AM-4), migration `0001`, full constraint tests, models-vs-migration check.
- AM-9 (2026-10-06): migration `0003` makes `document_versions.s3_version_id` NOT NULL, limits version `state` to `ACTIVE`/`S3_MISSING` (default `ACTIVE`), drops `ck_versions_s3_id_when_stored` and the partial index on `PENDING` versions, after deleting rows in the withdrawn states. Verified on a clean database and over 0002 data with `PENDING`/`FAILED` rows (removed, stored rows kept), downgrade and re-upgrade.

### T4 Simulated store schema (migration `0002`)
- `sim_object_versions`: `id` bigserial PK; `bucket` varchar(63); `key` varchar(1024); `version_id` varchar(64) UNIQUE (random, opaque); `is_delete_marker` bool; `data` bytea (NULL for markers); `size_bytes` bigint (0 for markers); `content_type`; `etag` (quoted hex MD5); `checksum_sha256` (base64); `storage_class` (CHECK STANDARD/STANDARD_IA/GLACIER_IR; NULL for markers); `metadata` jsonb; `tags` jsonb; `last_modified` timestamptz. Index `(bucket, key, id DESC)`; CHECKs tying marker rows to NULL data and class. The latest version of a key is its highest `id`.
- `processing_jobs`: add `claimed_at` (nullable timestamptz) and `deliveries` (int, default 0, CHECK >= 0); index `(status, created_at)` where `status='PENDING'`.
- Doc 04 note: these are simulated-S3 tables; no FK to application tables (S3 does not know the app).
- Tests: constraints; models match migration; downgrade/upgrade.

## Phase 3: Storage layer

### T5 ObjectStorage interface, simulated backend, signed links (`backend/app/storage/`)
- `ObjectStorage` protocol (no backend-specific types): `put_object`, `copy_object(key, source_version_id, storage_class=None)`, `delete_object` (returns marker version id), `delete_version`, `delete_all_versions(key)` (per-version results), `head_object`, `get_object`, `get_object_tagging`, `list_object_versions(prefix)`, `check()` (startup). Typed errors: `NoSuchKey`, `NoSuchVersion`, `MethodNotAllowed` (delete marker), `BadDigest`, `StorageLimitExceeded`, generic `StorageFailure`.
- `PostgresObjectStorage`: each call in its own short transaction on its own session; semantics per `docs/VERIFIED.md`; metadata `cv-doc-id`/`cv-owner-id`, tags `project=cloudvault`, `env=<APP_ENV>`; verifies SHA-256; ETag = quoted MD5; `head_object` returns `storage_class=None` for STANDARD; total-size limit enforced under a transaction-level advisory lock so concurrent writes cannot overshoot; never loads `data` except in `get_object`/`copy_object`.
- `build_key(owner_id, document_id)` = `documents/{owner_uuid}/{document_uuid}`.
- Signed links (`storage/signing.py`): `sign_download(bucket, key, version_id, filename, now)` and `verify(...)`; HMAC-SHA256 with `SIM_SIGNING_SECRET`, constant-time compare, expiry `PRESIGN_EXPIRY_SECONDS`; `filename*=UTF-8''<percent-encoded>` disposition.
- Error mapping for routers: `StorageLimitExceeded` gives 507 `STORAGE_LIMIT_EXCEEDED`; `StorageFailure` gives 502 `STORAGE_ERROR`; `NoSuchVersion` makes callers mark the version `S3_MISSING` (state) and answer 410 `VERSION_EXPIRED` (error code, doc 05.2).
- Dependency injection: a `get_storage()` provider so tests and a future S3 adapter can swap implementations.
- Tests (replace doc 10 A1/A2): put, put, delete gives two versions plus a marker; undelete by removing the marker; HEAD of STANDARD has no class; copy with class creates a new version; checksum mismatch rejected; storage limit; signed-link valid/expired/tampered; list versions.

## Phase 4: Core backend

### T6 Validation (done)
- `read_upload` (streaming, in memory, capped) and `validate_upload`. Routers never use `UploadFile`/`File()`.

### T7 Auth (`routers/auth.py`, `security.py`)
- Register: email trimmed and lowercased (max 254, basic format check), password 8-128 characters and at most 72 UTF-8 bytes (AM-5; 422 `VALIDATION_ERROR` "Password must be at most 72 bytes when UTF-8 encoded"), bcrypt; 201 `{id,email}`; 409 `EMAIL_EXISTS` (catch the unique-index violation too).
- Login: 200 `{access_token, token_type:"bearer"}`; identical 401 `UNAUTHORIZED` for unknown email and wrong password (compare against a dummy hash for unknown emails); slowapi 5/min/IP; 429 `RATE_LIMITED` in the standard body.
- `GET /auth/me`. JWT HS256, `sub` = user id, `exp` = 60 min. `get_current_user` returns 401 for missing, malformed, expired or unknown-user tokens.
- Tests: S2, S5, happy paths, duplicate email (case-insensitive), password bounds incl. the 72-byte rule with multi-byte characters.
- Then check T20 acceptance (login in the browser).

### T8 Upload and list (`routers/documents.py`, `services/document_service.py`)
- W2 per AM-1 and AM-9 with `read_upload` + `validate_upload`; duplicate rule (200 `{duplicate:true, document}`); 409 `NAME_EXISTS` with `details.existing_document_id`. Transaction 1 flushes and commits only the `PENDING` document; the finalize transaction inserts v1 with the store's version id, sets `current_version_id`, inserts the `PENDING` job and makes the document `ACTIVE`. Storage failure marks the document `FAILED` and writes no version row.
- `document_lock(document_id)` (`app/locks.py`): dedicated AUTOCOMMIT connection from a separate small lock pool (so lock waiters and main-pool waiters cannot deadlock), `pg_advisory_lock(key)`, no transaction open, `pg_advisory_unlock` in `finally`, connection invalidated if release cannot be confirmed; key = signed 64-bit BLAKE2b of a namespace plus the document UUID. Callers must commit/close their session before taking the lock.
- Known limit (by design, AM-1): if the process dies between transaction 1 and the store write, the `PENDING` document keeps its name reserved until `reconcile` (T19) marks it `FAILED` after 1 h; a same-name upload meanwhile gets 409.
- Upload rate limit 20/min/user.
- `GET /documents` (q with escaped ILIKE, status, type, storage_class, sort, pagination) and `GET /documents/{id}`; only `ACTIVE`/`DELETED`; response per doc 05.4; `stalled` = `PENDING` older than 10 min.
- Tests: I1-I3, C3, A4 (storage failure leaves the document `FAILED`, no version row, nothing exposed), V8 at HTTP level, pool not exhausted after many locked operations.

### T9 Download and signed route
- W3: owner + `ACTIVE` (409 `DOCUMENT_DELETED`); `?version=n`; 404 `VERSION_NOT_FOUND`; a version in state `S3_MISSING` gives 410 `VERSION_EXPIRED`; sign (no storage call); insert `access_logs` and commit before returning; 200 `{url, expires_in}`.
- `GET /api/sim-s3/{bucket}/{key:path}`: no login; verify signature and expiry (403 `ACCESS_DENIED`); `get_object` by version (404 if gone); attachment disposition, `nosniff`, `no-store`.
- `GET /documents/{id}/access-logs`.
- Tests: I9, S3 (expired link 403), tampered link 403, other version id 403.

### T10 Delete, undelete, permanent delete
- Under the document lock with `pending_op`, as in AM-1; semantics per doc 02.5 and AM-4.
- Implemented (`app/services/deletion_service.py`). Notes recorded in doc 15 AM-1: a leftover `pending_op` seen under the lock is rolled forward or dropped from the store's actual state before the operation runs (a crashed process releases its session lock, so it cannot be live); a failed final transaction leaves `pending_op` for that roll-forward; undelete of a document with `pending_op='PURGE'` is refused with 409 `DOCUMENT_DELETED`.
- Leftover `pending_op='APPLY'` is now recovered by T14's rules (doc 15 AM-1, T14 note) before any T10/T11 operation.
- Tests: I6-I8, C2 (competing deletes: both 204, one marker).

### T11 Versions and restore
- Versions list; W5 (C1 competing uploads: versions n and n+1, store order matches DB order); W6 with a new `PENDING` job (AM-2); `NoSuchVersion` marks the version `S3_MISSING` and answers 410 `VERSION_EXPIRED`.
- Tests: I4, I5, C1, restore job rules.
- Implemented (`app/services/version_service.py`). Version numbers: `max(version_number) + 1`, allocated in the finalize transaction after the store write (AM-9; no gaps), while holding the document lock and the row lock; store write and finalize share one lock, so store order equals DB order. A failed store write or finalize writes no version row. Restore copies with no storage class (STANDARD). Upload rate limit is one shared 20/min/user budget across `POST /documents` and `POST /documents/{id}/versions` (doc 09.1 names a single upload limit).
- Open question for the owner: a new version's content type comes from the uploaded file's extension (doc 05.3), and the document keeps its display name, so `notes.txt` uploaded as a new version of `report.pdf` is accepted as text/plain under the name `report.pdf`. The spec does not say whether a new version must keep the document's type.

### T12 S3 Inspector API
- `GET /documents/{id}/s3-info?version=n`: `head_object` + `get_object_tagging`; doc 05.4 shape with `source:"simulated-s3"`; absent class shown as STANDARD.
- Implemented with exactly the doc 05.4 fields (the store still keeps and verifies the SHA-256 checksum; it is not part of the API). Trashed documents can be inspected (doc 05.5 lists no 409). A version the store no longer holds is marked `S3_MISSING` and answered 410 `VERSION_EXPIRED`.

## Phase 6-8: Recommendations and dashboard

### T13 Engine (done)
- Pure `evaluate`, U1-U8 and boundary tests; optional pricing loader (`storage_gb_month` per class).

### T14 Recommendation endpoints
- Refresh, list, dismiss; Apply per W11 + AM-1: lock, already `APPLIED` no-op, re-evaluate (409 `STALE_RECOMMENDATION`), `pending_op='APPLY'`, `copy_object` with the target class, update the version row, `APPLIED`, delete the old stored version.
- Tests: I10 (simulated class changes, old version gone), I11.
- Implemented (`app/services/recommendation_service.py`, `app/services/apply_recovery.py`). Decisions: applying a `DISMISSED` or `STALE` recommendation, or one whose document was trashed, returns 409 `STALE_RECOMMENDATION`; a source version missing from the store returns 410 `VERSION_EXPIRED` (version marked `S3_MISSING`, recommendation `STALE`); `dismiss` changes only `OPEN` recommendations and returns others unchanged; `estimate` is always `null` (doc 07.5 has no pricing format yet). Recovery states A-D are recorded in doc 15 (AM-1, T14 note).

### T15 Dashboard
- Aggregates per doc 05; owner-scoped; `ACTIVE` documents and versions.
- Implemented (`app/services/dashboard_service.py`). `bytes_by_class` sums every stored (`ACTIVE`) version, so its total equals `total_bytes_all_versions`; trashed documents and `S3_MISSING` versions are excluded; `jobs_by_status` always carries all four statuses.
- Dashboard screen (doc 06.5, part of T21) built now at the owner's request with Impeccable: visual world "Finding Aid" (DESIGN.md, `.impeccable/surfaces/`). The Documents and Optimization screens are not built yet, so dashboard figures do not link to them; T21/T23 add those links and the empty state's upload action.

## Phase 9: Processing

### T16 Extraction module (`backend/app/processing/extract.py`)
- Pure functions over bytes + content type: size gate 5 MB (`SKIPPED/TOO_LARGE`), pdf via pypdf (encrypted: `FAILED/ENCRYPTED`), txt/md/csv, docx (zipfile + XML), images `SKIPPED/NO_EXTRACTION`, corrupt `FAILED/CORRUPT`, other `FAILED/PARSE_ERROR`; excerpt at most 4000 chars.
- Implemented (`app/processing/extract.py`). Additions: a .docx whose `word/document.xml` expands past 50 MB is `SKIPPED/TOO_LARGE` (zip-bomb guard); an unknown content type is `SKIPPED/NO_EXTRACTION`; error messages never carry parser internals. Doc 10 L3 (URL-encoded event keys) does not apply after AM-7 (no event keys).
- Tests: L1 (6 MB text), L2 (corrupt PDF), encrypted PDF, docx, image.

### T17 Processing worker (`backend/app/processing/worker.py`)
- Started in the app lifespan when `PROCESSING_WORKER_ENABLED`; stops cleanly on shutdown. Poll loop: claim one job (`PENDING`, `deliveries < 3`, lease free or older than 120 s) with `FOR UPDATE SKIP LOCKED`, set `claimed_at`, `deliveries+1`, commit; read the version's bytes from storage; run T16; write the result only `WHERE status='PENDING' AND claimed_at = <ours>`; transient errors leave the job for the next lease.
- Tests: restart safety (claimed job with expired lease is reclaimed), C4 duplicate processing no-op, deliveries cap, deterministic outcomes, two workers never take the same job.
- Implemented (`app/processing/worker.py`, started in the app lifespan). Finish matches `status='PENDING'` plus this delivery's `claimed_at` and `deliveries`, so a stale or duplicate delivery is a no-op. Additions recorded in doc 15 AM-7: job `error_code` `S3_MISSING` (stored version gone; the version is marked `S3_MISSING`) and `VERSION_UNAVAILABLE` (withdrawn by AM-9: a version is always stored or `S3_MISSING`). If the version row's store id changed during a delivery (concurrent Apply), the lease is released and the job re-read instead of marking it missing. The size gate uses the stored size, so oversized objects are never read.

### T18 Processing endpoints
- `GET /documents/{id}/processing`; Tier 3 retry (`FAILED` or stalled `PENDING`; `PENDING`, `attempts+1`, `deliveries=0`, clear lease/result fields; 202; `SUCCEEDED`/`SKIPPED` 409 `JOB_NOT_RETRYABLE`).
- Implemented (`app/services/processing_service.py`). Decisions: `?version` is optional (default: current version); retry returns the job item; retry restarts the job's `created_at` so the 10-minute stall clock starts over (otherwise a retried job would read as stalled at once); a version in state `S3_MISSING` returns 410 `VERSION_EXPIRED`; a retry while an old delivery is in flight wins (that delivery's finish no longer matches).

### T19 Scripts
- `python -m app.scripts.reconcile [--fix]`: compare the simulated store with application tables (unreferenced versions; missing versions become `S3_MISSING`; `ACTIVE` documents whose latest stored version is a marker; stale `PENDING` documents and `pending_op`).
- Required reconcile test (carried over from T8): an upload that died after transaction 1 leaves a `PENDING` document reserving its name; after 1 h `reconcile --fix` marks it `FAILED` and a same-name upload then succeeds. Under AM-9 a stored object left by the crash is never adopted; it is an unreferenced version, removed by `--fix` after 1 h.
- `python -m app.scripts.lifecycle [--now] [--dry-run]`: AM-7 rules from stored timestamps.
- `python -m app.scripts.seed_demo`: real files of 128 KiB-10 MiB through the service; backdates application and simulated-store timestamps consistently (disclosed); may place objects in STANDARD_IA/GLACIER_IR through the simulated copy so R1/R2/R3 all appear.
- Implemented (`app/scripts/`). Reconcile changes each document under its advisory lock; a stale `PENDING` document is marked `FAILED` (AM-9; before AM-9 a stale `PENDING` version could be finalized from a matching stored object, now withdrawn). Lifecycle applies NoncurrentVersionExpiration to object versions only and removes a delete marker once it is the key's only entry; it also takes the document lock per key. Seed creates the demo user (`--email`, `--password`, `--reset`) and prints the backdating disclosure.

## Phase 5-8: Frontend

### T20 Scaffold (done except login check)

### T21 Core screens
- Dashboard, Documents (search, filters, dropzone, table, Trash), shared components, all loading/empty/error states, 409 "Upload as new version" dialog, delete and permanent-delete confirmations; download navigates to the signed link.
- Implemented (`frontend/src/pages/DocumentsPage.tsx`, shared `Button`, `StorageClassBadge`, `ProcessingBadge`, `ConfirmDialog`, `ToastProvider`/`useToast`, `RowMenu`, `Pagination`, `UploadDropzone`, `DocumentTable`, `api/documents.ts`, `utils/vocab.ts`). Search, filters, sort and page live in the URL and go to `GET /documents`. Uploads run one at a time; a 409 `NAME_EXISTS` pauses the queue for the "Upload as new version" choice (uses `details.existing_document_id` and `POST /documents/{id}/versions`). Verified end to end in a browser (23 checks, desktop and phone).
- Deferred by plan: document names link to Details in T22 (`SourceBadge` arrives with the Inspector); the dashboard recommendations card links to Optimization in T23. No upload progress percentage: `fetch` reports none; the dropzone shows the file in flight and the queue length. A 10 MiB pre-check in the browser is a convenience only (doc 06.4).

### T22 Details tabs
- Overview, Versions (Restore), Access ("recorded by CloudVault"), S3 Inspector ("Live from simulated S3"), Processing (Stalled, Retry).
- Implemented (`frontend/src/pages/DocumentDetailsPage.tsx`, `pages/details/{Overview,Versions,Access,Inspector,Processing}Tab.tsx`, `Panel.tsx`; shared `SourceBadge`, `UnavailableState`, `Tabs`, `FieldList`; `utils/download.ts`, `utils/invalidate.ts`). Route `/documents/:id`; tab and Inspector version live in the URL (`?tab=inspector&version=n`). Document names in the Documents table link here.
- Uses existing endpoints only: `GET /documents/{id}`, `/versions`, `POST /versions/{n}/restore`, `/download?version=n`, `/access-logs?page`, `/s3-info?version=n`, `/processing`, `POST /processing/retry?version=n`, plus upload-version, delete, undelete and permanent delete. Every query for a document sits under `['document', id]`; each mutation (and each download, which adds an access row) invalidates that prefix, the documents list and the dashboard. No optimistic updates, no polling (Processing has a manual Refresh).
- States: 404/422 document -> "Document not found"; other errors -> error state with Retry. Inspector 410 `VERSION_EXPIRED` -> "no longer in the simulated store"; 404 -> "Version not found"; 502 and other errors -> "S3 unavailable, retry". Retry 409 `JOB_NOT_RETRYABLE` and 410 surface as toasts followed by a refetch. Version actions are disabled for versions missing from storage and (download/restore) while the document is in the trash; the Inspector still reads trashed documents.
- Verified end to end against the real backend (23 browser checks: restore, version-bound download by URL `versionId` and bytes, access rows, Inspector current/older/410/404/502, failed and stalled retry through the worker, 409, trash/restore/purge, not-found, 500, empty access, 390 px with no horizontal scroll). The T21 Documents e2e was rerun (pagination block skipped: its 30-document fixture account no longer exists; `Pagination` unchanged).
- Tabs wrap onto a second row below 640 px so every tab stays visible (affects the Documents/Trash tabs too, which fit on one row).

### T23 Optimization and About
- Banner "CloudVault's heuristic, not AWS Intelligent-Tiering"; table; Refresh/Apply/Dismiss; Apply dialog. About: "CloudVault is a functional simulation of Amazon S3", architecture, `[S3-SIM]`/`[APP]`/`[UI]` table.
- Implemented (`frontend/src/pages/OptimizationPage.tsx`, `AboutPage.tsx`, `api/recommendations.ts`, `components/RecommendationStatusBadge.tsx`; nav and dashboard link in `AppShell`/`DashboardPage`). Uses only `GET /recommendations?status`, `POST /recommendations/refresh`, `POST /recommendations/{id}/apply` and `/dismiss`; nothing is calculated in the browser. State tabs Open/Applied/Dismissed/Stale live in `?status=`; only OPEN rows offer Apply and Dismiss, the others show their outcome (Stale with a hollow swatch and an explanation, never as a failure). Apply opens the doc 06.5 dialog; success toasts "Storage class changed to X"; 409 `STALE_RECOMMENDATION`, 410 `VERSION_EXPIRED` and 404 surface as toasts and the lists refetch. After every mutation `['recommendations']`, `['dashboard']`, `['documents']` (and `['document', id]` after Apply) are invalidated; no optimistic updates. `estimate` is never shown (always null).
- About is static: the AM-7 disclosure, an architecture diagram drawn from AM-7 (the doc 02 diagrams still show real AWS), the label table, and a feature table listing only implemented features, plus what is not simulated.
- On phones the main nav moves to its own row under the brand so all four screens stay visible; the Documents nav item is now active on Details pages too.
- Verified end to end against the real backend with `seed_demo` accounts (empty states for all tabs, Refresh, Apply with store check, Dismiss, stale through a concurrent new version, superseded by Refresh, already APPLIED elsewhere, 410 missing source, list and Refresh errors, Dashboard links, About, 390 px). T21 and T22 e2e rerun after the shell change.

## Phase 10-11: Hardening and tests

### T24 Security pass
- CORS, rate limits, security headers, error hygiene, signed-route abuse (tampering, path tricks), no sensitive logs, owner scoping (404, never 403 for other users' resources). Tests S1-S5.
- Implemented (`app/http_hardening.py`, `tests/integration/test_security.py`, 74 tests). Fixes found by the audit:
  - Signed route: an `expires` longer than Python's int-string limit and a non-ASCII `signature` raised and returned 500. `verify_download` now accepts only the canonical expiry (ASCII digits, at most 12, no leading zeros) and compares signatures as bytes; both cases are 403 `ACCESS_DENIED`.
  - `page`, `version` and `version_number` above the PostgreSQL `integer` range overflowed in the database (500). They now have `le=2147483647` and return 422.
  - JSON routes buffered any body size before validation. Non-upload routes now cap request bodies at 64 KiB (declared or streamed): 413 `VALIDATION_ERROR` "Request body is too large". The two upload routes keep their own streaming cap (10 MiB + multipart overhead).
  - uvicorn's access log printed signed-URL query strings (signature included), against doc 09.1 and AM-6. A log filter installed by `create_app` drops query strings from access-log lines.
  - No security headers were sent. Every response now carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; API responses also `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` and `Cache-Control: no-store` (a route's own value wins, so the signed route keeps `private, no-store`); `/docs`, `/redoc` and `/openapi.json` skip the CSP so Swagger UI works; HSTS only in production.
  - Configuration: `FRONTEND_ORIGIN` may never be `*` or empty, and must be `https` in production.
- Verified unchanged: CORS allows only `FRONTEND_ORIGIN` (no credentials, methods GET/POST/DELETE, headers Authorization/Content-Type); login 5/min/IP and upload 20/min/user; bcrypt rules (AM-5); JWT pinned to HS256 with `exp`/`iat`/`sub` required; cross-owner requests on every document, version, processing, access-log, Inspector, download, delete/restore/purge and recommendation route return the same 404 body as a random id, and change nothing.
- Follow-up (2026-10-06): register limited to 10/min per client IP (bcrypt cost); 409 `EMAIL_EXISTS` unchanged. All T24 values recorded and approved as AM-8 in doc 15, including the in-memory limiter's single-instance limit. Reliability: the security, rate-limit and concurrency set ran 10 consecutive times clean (169 tests each), logs kept.
- S4 under AM-7: the internal endpoint no longer exists; the test asserts no `internal` route exists and that `POST /api/internal/processing-results` is 404. S2 enumerates every operation from the OpenAPI schema, so a new route without auth fails the test.

### T25 Test completion
- Fill doc 10.2 as amended (A-tests against the simulated store, L-tests against T16/T17).
- Done: `docs/TEST_MATRIX.md` maps every doc 10.2 ID and every per-task test to its test. Two gaps closed: A3 (upload to processed result over the API, AM-7) and L3 (encoded characters in names never reach the key, AM-7). Full run 568 passed; recovery/concurrency/security set repeated 5 times clean. After AM-9 (2026-10-06): 570 passed; security + concurrency/recovery set (208 tests) repeated 5 times clean; new `test_version_invariant.py` checks the NOT NULL column, the database state inside every version-creating store write, Apply, and restore -> new PENDING job -> worker SUCCEEDED; browser run of upload, worker, new version, restore (row menu dialog), Inspector, signed download (unsigned 403), access log, trash/undelete and permanent delete with no console errors or server 5xx.

## Phase 12-14: Ship

### T26 Deployment
- Neon (direct connection string, `sslmode=require`), Render (start: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`; worker runs in-process), Vercel (`VITE_API_BASE_URL`, SPA rewrite). Distinct strong secrets; `FRONTEND_ORIGIN` = Vercel URL; `PUBLIC_API_BASE_URL` = Render URL. Smoke test.

### T27 Documentation
- README: the simulation statement, setup, architecture, `[S3-SIM]`-vs-app table, heuristic disclaimer, seed backdating disclosure, cold start note. Only implemented features.
- Done 2026-10-06 ahead of T26 at the owner's request: README rewritten as the project README (simulation statement, `[S3-SIM]`/`[APP]`/`[UI]` responsibilities, architecture, implemented and not-implemented features, AM-2 and AM-9 rules, heuristic disclaimer, worker and cold-start behavior, seed backdating disclosure, local setup, scripts, checks), keeping the spec reading order. AM-7 notes on doc 02, 08, 11, 12, 13 now say plainly not to create AWS resources. Fresh-copy walkthrough of the README setup passed (venv install, migrate, health, seed, reconcile, lifecycle dry run, frontend install/build/lint). Still due after T26: measured cold-start time and the public URLs in the README; the original T27 "teardown" item does not apply (AM-7).


### T28 Demo rehearsal
- Warm `/api/health`, run reconcile, lifecycle (dry run), seed; run the doc 13 script (as amended) twice.
- Rehearsed locally 2026-10-06 from an empty database: compose up, `alembic upgrade head`, uvicorn (worker on), Vite, health, reconcile (clean), lifecycle `--dry-run` (nothing to do), `seed_demo`. Browser walkthrough of the full demo ran twice: login, dashboard, upload, Details tabs, worker result, signed download (unsigned URL 403), trash and restore, Refresh (R1/R2/R3), Apply R3 with the class checked in the Inspector, About; 390 px for every screen; no console errors, no backend tracebacks or 5xx, no query strings or secrets in logs. Fixed: the Processing tab's Refresh now reloads the whole document (the header badge stayed "Pending"), and "1 pages"/"1 words" plurals. Left in a pristine seeded state (`seed_demo --reset`); deployment-day rehearsal still due after T26.

## Local environment notes

- **Backend:** Python 3.12 venv in `backend/.venv.nosync`, symlinked as `backend/.venv`. System `python3` is 3.14; do not use it.
- **Commands:** `cd backend && .venv/bin/pytest -q` and `.venv/bin/ruff check app tests alembic`; `cd frontend && npm run build && npm run lint`; `python3 tools/build_full_spec.py` after editing any spec file.
- **Postgres:** native Postgres holds ports 5432/5433; local `.env` sets `POSTGRES_PORT=55432` and a matching `DATABASE_URL`.
- **Tests** create and migrate `<db>_test` and refuse non-local DB hosts.
- **Frontend env:** Vite reads `VITE_*` from the repo-root `.env`.
- **iCloud:** `~/Desktop` is iCloud-synced; evicted ("dataless") files make reads hang. Backend venv uses a `.nosync` name; `frontend/node_modules` carries `com.apple.fileprovider.ignore#P` (re-apply after `npm ci`). Check `find . -flags +dataless` if something hangs.

## Working protocol per task

1. Re-read the doc sections the task cites, then doc 15.
2. Check prerequisites in the tracker.
3. Implement only what the task lists.
4. Write the listed tests; run backend `pytest` + `ruff`, frontend `build` + `lint`.
5. Update the tracker.

## Final checklist
Doc 12.4 Definition of Done as amended by doc 15 (simulated store and in-app Inspector in place of real S3 and the AWS Console).
