# 9. Security, Failure Modes and Consistency

## 9.1 Security architecture

> **Amended:** AM-7: no AWS credentials exist; the secrets are `JWT_SECRET`, `SIM_SIGNING_SECRET` and the database URL. Downloads use HMAC-signed links. See [doc 15](15-amendments.md).

| Topic | Decision |
|---|---|
| AWS credentials | Never in the frontend. Backend uses an **IAM user's access keys** (Render is not AWS, so no instance role) held in Render environment variables. Local dev uses a named AWS profile or env vars. Lambda uses its execution role |
| Least privilege | See doc 11 section 11.3. No admin keys at runtime |
| Private bucket | Block Public Access on. Only presigned URLs grant temporary access |
| Presigned URLs | GET only, 120 s, VersionId-bound, issued only after an ownership check. Anyone holding the URL can use it until it expires |
| Authentication | Email + password (bcrypt), JWT HS256 (60 min), Bearer header only, so **CSRF does not apply** (no cookies) |
| Authorization | Every query scoped by `owner_id`. Other users' resources return 404 |
| Path traversal / filenames | Filenames never become keys or file paths. Nothing written to disk |
| MIME validation | Allowlist + magic bytes; client `Content-Type` ignored |
| Size limits | 10 MiB enforced server-side while streaming |
| CORS (API) | Allow only `FRONTEND_ORIGIN`; restrict methods and headers. Bucket has no CORS |
| SQL injection | SQLAlchemy parameterized queries only; no string-built SQL |
| XSS | React escaping; no `dangerouslySetInnerHTML`; extracted text rendered as plain text; downloads use `attachment` disposition |
| Rate limiting | `slowapi`: login 5/min/IP, upload 20/min/user (in-memory, per instance) |
| Secrets | Env vars only. `.env` gitignored, `.env.example` committed |
| Logging | Never log passwords, tokens, presigned URLs or file contents |
| Internal endpoint | Constant-time token comparison; hidden from public OpenAPI in production |
| Bucket policy | Deny non-TLS requests |

## 9.2 Failure modes and edge cases

| Scenario | Expected behavior | HTTP | DB state | S3 state |
|---|---|---|---|---|
| Empty upload | Reject | 400 `EMPTY_FILE` | none | none |
| Unsupported type | Reject | 415 | none | none |
| Oversized file | Reject while reading | 413 | none | none |
| Duplicate upload (same name and SHA) | Return existing doc | 200 `duplicate:true` | unchanged | unchanged |
| Same filename, different content | Offer "new version" | 409 `NAME_EXISTS` | unchanged | unchanged |
| Malformed request (no file, bad JSON) | Reject | 422 | none | none |
| Invalid bucket / misconfig | Fail loudly at startup (`HeadBucket`) and per request | 502 `STORAGE_ERROR` | rolled back | none |
| Invalid document ID | Reject | 422 (non-UUID) or 404 | none | none |
| Deleted document | Block download, version upload, restore | 409 `DOCUMENT_DELETED` | unchanged | delete marker present |
| Expired presigned URL | S3 denies; user requests a new URL | (S3 403) | none | none |
| S3 timeout | botocore standard retry (at most 3 attempts), then fail | 502 | rolled back | none or orphan (compensated) |
| S3 permission denied | Log, fail | 502 `STORAGE_FORBIDDEN` | rolled back | none |
| Database unavailable | Fail before any S3 write | 503 `DB_UNAVAILABLE` | none | none |
| Lambda failure | Retries, then job stays `PENDING` ("Stalled") | n/a | job `PENDING` | object unaffected |
| Duplicate Lambda event | No-op | 200 `already_processed` | unchanged | unchanged |
| Interrupted upload | Request aborts, txn rolls back | n/a | none | none, or orphan version (reconcile) |
| Concurrent upload, same document | Serialized by row lock: versions n, n+1; later lock wins as current | 201/201 | both rows | both versions |
| Concurrent new docs, same name | Second hits partial unique index before S3 PUT | 409 | one row | one object |
| Concurrent delete | Serialized; second is a no-op | 204/204 | `DELETED` | one marker |
| Restore on a deleted document | Rejected until undeleted | 409 | unchanged | unchanged |
| Nonexistent version | Reject | 404 `VERSION_NOT_FOUND` | none | none |
| Version expired by lifecycle | Mark `S3_MISSING`, reject | 410 | `S3_MISSING` | version gone |
| Corrupted or missing metadata | Inspector shows "unavailable"; DB is authoritative | 200 | unchanged | unchanged |
| Orphaned S3 object (no DB row) | Reconcile reports; `--fix` deletes if older than 1 hour | n/a | none | orphan |
| Orphaned DB record (S3 missing) | Reconcile marks `S3_MISSING` | n/a | `S3_MISSING` | none |
| Invalid/stale recommendation | Reject | 409 `STALE_RECOMMENDATION` | rec marked `STALE` | unchanged |
| Access to another user's document | Treat as nonexistent | 404 | none | none |

## 9.3 Consistency and recovery

> **Amended:** AM-1: application transactions are not held across storage calls; advisory locks, `PENDING` documents and `pending_op` drive concurrency and recovery; a version row exists only after its store write (AM-9). See [doc 15](15-amendments.md).

**Principle:** the DB is the source of truth for what the app shows; S3 is the source of truth for bytes. The two cannot share a transaction, so we use **ordering + compensation + reconciliation**. No distributed locking.

| Situation | Handling |
|---|---|
| S3 succeeds, DB fails | In the exception handler delete that exact S3 version (best effort). If that fails, reconcile finds the unreferenced version later |
| DB succeeds, S3 fails | Cannot happen for uploads: DB changes commit only after S3 succeeds (transaction held open across the PUT). For deletes and restores S3 is called first inside the transaction; failure rolls back |
| Commit fails after an S3 mutation (delete/copy) | DB view stays as before. Reconcile reports mismatches. Downloads are signed with explicit VersionIds so they keep working |
| Retry strategy | boto3 standard retry mode, 3 attempts. Clients may retry per the idempotency column in doc 05 |
| Cleanup | Orphaned versions older than 1 hour removed by `reconcile --fix` |
| Reconciliation | `python -m app.scripts.reconcile [--fix]`, run manually before the demo. Lists S3 versions under `documents/`, compares to DB. Reports unreferenced versions (deletable), `ACTIVE` rows missing from S3 (set `S3_MISSING`), and `ACTIVE` documents whose current S3 object is a delete marker (report only) |
| Processing jobs | `PENDING` over 10 minutes shows "Stalled"; retry resets and re-invokes |
| Held locks | The row lock is held across the S3 call (acceptable at this scale). Set DB statement/pool timeouts and short S3 timeouts (connect 5 s, read 30 s) |

**Concurrency rules (deterministic, no overengineering):**
- Per-document mutations: `SELECT ... FOR UPDATE` on the `documents` row.
- Same-name creation: the partial unique index is hit by `flush()` before the S3 PUT.
- Repeated requests: follow the idempotency behavior in doc 05.
- Lambda duplication: processing job uniqueness plus the `PENDING`-only update rule.
