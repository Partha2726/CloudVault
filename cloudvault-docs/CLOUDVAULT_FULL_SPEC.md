# CloudVault: Full Specification (single file)

> Concatenation of `AGENTS.md`, `README.md` and `docs/01` to `docs/14`. Diagram images are referenced from `docs/diagrams/`.


---

# AGENTS.md: Instructions for any AI coding agent working on CloudVault

Read this file first, then `README.md`, then the docs in the order given in `README.md`.

## Ground rules (non-negotiable)

1. **The docs are the specification.** Do not invent architecture, endpoints, tables, columns, thresholds, error codes or AWS behavior that the docs do not define. If something is missing or contradictory, stop and ask the human. Do not guess.
2. **Never present application logic as native S3 behavior.** Every feature is one of:
   - `[AWS]` = real Amazon S3 / AWS feature
   - `[APP]` = CloudVault application logic built on top of S3
   - `[UI]` = interface representation only
3. **`VERIFY` markers.** Anything tagged `VERIFY` must be checked against official AWS documentation (docs.aws.amazon.com) before you write code that depends on it. Record the result in `docs/VERIFIED.md` (create it, one line per item: item, finding, source URL, date).
4. **Never put secrets in Git.** No AWS keys, JWT secrets, DB URLs or webhook secrets in any committed file. Only `.env.example` with placeholders is committed.
5. **Never expose AWS credentials to the browser.** The frontend only receives short-lived presigned GET URLs.
6. **The S3 bucket is always private.** Never disable Block Public Access. Never add a public bucket policy.
7. **User-supplied filenames never become S3 keys or local file paths.** Uploads are never written to local disk.
8. **Do not add** anything listed in `docs/01-overview-and-scope.md` under "Explicitly out of scope" (no multipart, KMS, Object Lock, Terraform, AI/ML, roles, sharing, etc.).
9. **Make targeted changes.** When modifying existing code, change only what the task requires and keep the existing style. Do not rewrite files wholesale.
10. **Work task by task** using `docs/12-repo-and-build-order.md`. Do not start a task before its prerequisites pass their acceptance checks. Run the listed tests for each task before moving on.
11. **Tests must not require AWS by default.** Tests that need real AWS are marked `@pytest.mark.aws` and run only when explicitly requested.
12. **Do not claim a feature in the README, UI or demo script unless it is implemented and tested.**

## Locked technology decisions

| Layer | Choice |
|---|---|
| Frontend | React 18, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query, Recharts, lucide-react |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, boto3, slowapi, bcrypt, PyJWT |
| Database | PostgreSQL 15+ (Docker locally, Neon in production) |
| AWS | S3 (private, versioned, SSE-S3), Lambda (one function), IAM, CloudWatch Logs |
| Deployment | Vercel (frontend), Render (backend), Neon (DB), AWS (S3 and Lambda) |
| Tests | pytest, moto (local S3 mock), httpx/TestClient |

## Definition of "done" for any task

- Code implemented exactly as specified.
- Listed tests written and passing.
- No new lint errors.
- No undocumented behavior added.
- Acceptance criteria in the task table are met.


---

# CloudVault: Implementation Documentation

> **CloudVault** is a document manager built on **real Amazon S3** (private, versioned bucket) with a FastAPI backend, PostgreSQL, an S3-event-driven Lambda, and a custom rule-based **Intelligent Storage Optimization** engine.
> It is a university assignment ("AWS Service Simulation & Enhancement", 10 marks) designed to also be a defensible resume project.

This documentation set is an **implementation-ready specification** for an AI coding agent or a human developer. Start with [`AGENTS.md`](AGENTS.md).

## Labels used everywhere

| Label | Meaning |
|---|---|
| `[AWS]` | A real Amazon S3/AWS capability |
| `[APP]` | CloudVault application logic built on S3 (never described as AWS behavior) |
| `[UI]` | A UI representation/simulation |
| `VERIFY` | Must be checked against official AWS docs before implementing |

## Reading order

| # | Document | Contents |
|---|---|---|
| 1 | [01-overview-and-scope.md](docs/01-overview-and-scope.md) | Executive summary, rubric mapping, scope tiers, exclusions |
| 2 | [02-s3-design.md](docs/02-s3-design.md) | S3 capability matrix, bucket/object/key design, lifecycle, IAM-relevant S3 behavior |
| 3 | [03-architecture-and-workflows.md](docs/03-architecture-and-workflows.md) | Logical + deployment diagrams, all 16 workflows |
| 4 | [04-database.md](docs/04-database.md) | ER diagram, every table, constraints, state machines |
| 5 | [05-api-contract.md](docs/05-api-contract.md) | Every REST endpoint, error codes, validation rules |
| 6 | [06-frontend-and-ui.md](docs/06-frontend-and-ui.md) | Screens, components, states, UX rules |
| 7 | [07-recommendation-engine.md](docs/07-recommendation-engine.md) | Heuristic thresholds, pseudocode, apply flow |
| 8 | [08-lambda-processing.md](docs/08-lambda-processing.md) | Event design, idempotency, retries, limits |
| 9 | [09-security-and-consistency.md](docs/09-security-and-consistency.md) | Security model, failure matrix, S3/DB consistency |
| 10 | [10-testing.md](docs/10-testing.md) | Strategy and full test matrix |
| 11 | [11-deployment-cost-iam-env.md](docs/11-deployment-cost-iam-env.md) | Deployment, cost control, IAM policies, `.env` |
| 12 | [12-repo-and-build-order.md](docs/12-repo-and-build-order.md) | Repo layout, phases, dependency graph, **task-by-task build order**, definition of done |
| 13 | [13-demo-viva-resume.md](docs/13-demo-viva-resume.md) | Demo script, viva Q&A, resume bullets |
| 14 | [14-risks-fallback-verify.md](docs/14-risks-fallback-verify.md) | Risks, fallback tiers, final scope, **VERIFY list** |

A single concatenated copy of everything is in [`CLOUDVAULT_FULL_SPEC.md`](CLOUDVAULT_FULL_SPEC.md) for agents that prefer one file.

## Diagrams

All diagrams exist as Mermaid source (`.mmd`, easiest for agents to read), PNG and SVG in [`docs/diagrams/`](docs/diagrams/).

| Diagram | Files |
|---|---|
| Logical architecture | `01-logical-architecture` |
| Deployment architecture | `02-deployment-architecture` |
| Upload sequence | `03-upload-sequence` |
| Versioning and delete semantics | `04-versioning-and-delete` |
| Recommendation decision flow | `05-recommendation-flow` |
| Apply-recommendation sequence | `06-apply-recommendation-sequence` |
| Lambda processing sequence | `07-lambda-processing-sequence` |
| Phase dependency graph | `08-dependency-graph` |
| ER diagram | `09-er-diagram` |
| State machines | `10-state-machines` |
| IAM and trust boundaries | `11-iam-trust-boundaries` |

To re-render after editing a `.mmd` file:

```bash
npm i -g @mermaid-js/mermaid-cli
mmdc -i docs/diagrams/01-logical-architecture.mmd -o docs/diagrams/01-logical-architecture.png -b white -s 2
```

## Key locked decisions (summary)

- Bucket is **private** with Block Public Access on. Browser never talks to S3 except through a **120 s, version-bound presigned GET URL**.
- **Uploads are proxied through the backend** (max 10 MiB, single `PutObject`). No multipart, no CORS on the bucket.
- S3 key is **`documents/{owner_uuid}/{document_uuid}`**. The filename lives only in the database.
- One S3 key per document. **S3 versions = document versions.**
- Soft delete creates an **S3 delete marker**. Permanent delete removes **every version and marker** by VersionId.
- Access history is **application-recorded** (`access_logs`). S3 does not provide an application-friendly last-accessed time, and we never claim it does.
- Recommendations are **CloudVault's own heuristic**, not AWS Intelligent-Tiering. No fake savings percentages.
- **Lambda is included** (S3 `ObjectCreated:Put` to Lambda to backend callback) with idempotent processing.
- Auth: email and password with JWT (Bearer header). No OAuth, roles or sharing.

## Status of verification

This specification was written without live access to AWS documentation. All AWS-specific claims that are not core, well-established S3 behavior are marked `VERIFY`. Resolve every `VERIFY` item (list in `docs/14-risks-fallback-verify.md`) before depending on it.


---

# 1. Overview and Scope

## 1.1 Executive summary

**What CloudVault is.** A document manager where every file lives in a private, versioned Amazon S3 bucket. A FastAPI backend and PostgreSQL hold application state: ownership, display names, version numbers, access history and recommendations.

**Why Amazon S3.** S3 has a small core model (bucket, object, key) and a rich set of real features (versioning, delete markers, storage classes, presigned URLs, event notifications, lifecycle rules) that can all be demonstrated live against real AWS.

**Real S3 functionality demonstrated `[AWS]`:**
- Private bucket with Block Public Access
- PUT, GET (via presigned URL), DELETE
- Versioning, delete markers, permanent deletion by VersionId
- User-defined metadata, object tags, SHA-256 checksum
- Storage classes (STANDARD, STANDARD_IA, GLACIER_IR) changed via `CopyObject`
- Lifecycle rules (noncurrent-version expiry)
- `ObjectCreated` event notifications triggering Lambda
- Least-privilege IAM, SSE-S3 default encryption

**Custom enhancement `[APP]`.** *Intelligent Storage Optimization*: a deterministic, explainable rule engine ("CloudVault's heuristic") that reads application-level access logs and recommends a storage class. It is **not** AWS Intelligent-Tiering and the UI says so.

**Why it fits the assignment.** It implements real S3 functions (stronger than a fake console), has a meaningful enhancement, a simple UI, and free/near-free deployment.

**Resume value.** Cloud storage design, two-system consistency handling, event-driven processing, IAM and security, and testing.

## 1.2 Assignment-to-implementation mapping

| Requirement (marks) | Implementation | Evidence during demo |
|---|---|---|
| AWS understanding (2) | In-app **S3 Inspector** shows live `HeadObject`, VersionId, storage class, tags, metadata. **About** page labels every feature `[AWS]` vs `[APP]`. | Explain bucket/object/key. Show AWS Console beside the app. Answer viva questions. |
| Core functionality (3) | Upload, presigned download, soft delete + trash, permanent delete, version list + restore, metadata, tags, storage class, all against real S3. | Upload, then see object + VersionId in Console. Upload v2, restore v1. Delete and show the delete marker under "Show versions". |
| Enhancement (2) | Storage Optimization page (rule-based recommendations with reasons and signals, "Apply" changes the real S3 storage class) plus Lambda document-processing pipeline. | Seeded old docs yield recommendations. Apply one, show storage class in Console. Show Lambda log and processing status. |
| UI/UX (1) | React + Tailwind, 6 screens with loading/empty/error states, confirm dialogs, toasts. | Walk through screens, show phone-width window. |
| Deployment and GitHub (1) | Vercel + Render + Neon + AWS. Clean repo, README, diagrams, `.env.example`. | Open public URL, show repo. |
| Demonstration (1) | Scripted 9-minute flow and viva sheet (doc 13). | Run script without improvising. |

## 1.3 Scope definition

### Must have (Tier 1)
- Minimal auth (register, login, JWT) so ownership is real
- Upload (proxied through backend, at most 10 MiB, validated)
- Document list with search, filter, sort
- Download via presigned GET URL, with access logging
- Soft delete, trash view, undelete
- Version history, upload new version, restore version
- S3 Inspector (live metadata, tags, storage class)
- Dashboard with storage usage by class
- Storage recommendations (refresh, apply, dismiss)
- Deployment, README, tests for the engine and core flows

### Should have (Tier 2)
- Lambda document processing with status shown in UI
- Permanent delete (all versions and markers)
- Reconciliation CLI (DB vs S3)
- Demo seed script (backdated data)
- Lifecycle rules and TLS-only bucket policy via setup script
- AWS integration test suite

### Nice to have (Tier 3, only if time permits)
- Processing retry endpoint/UI, optional pricing-based estimate (`pricing.json`), tag editing, inline PDF preview, dark mode, Playwright E2E, GitHub Actions lint/test

### Explicitly out of scope (DO NOT IMPLEMENT)
- Public bucket or direct browser-to-S3 uploads
- Multipart upload, Object Lock, SSE-KMS
- Integration with real S3 Intelligent-Tiering
- Glacier Flexible Retrieval and Deep Archive (asynchronous restore needed)
- Sharing links, roles/admin, OAuth, email verification, password reset
- CloudFront, Terraform, Kubernetes, SQS/SNS, microservices
- CloudWatch dashboards, S3 server access logs, CloudTrail data events
- Replication, AI/ML, embeddings, OCR, virus scanning, Bedrock/OpenAI

## 1.4 Tier model (fallback)

| Tier | Contents | If dropped |
|---|---|---|
| 1 Mandatory | Everything in "Must have" | Project fails |
| 2 Strongly recommended | Lambda, permanent delete, reconcile, seed, lifecycle, AWS tests | Move processing into backend or omit; still scores well |
| 3 Optional | See Tier 3 list | No impact on marks |


---

# 2. S3 Design

Labels: `[AWS]` real feature, `[APP]` our logic, `[UI]` representation.

## 2.1 S3 capability matrix

| Capability | Real AWS? | Used? | How CloudVault uses it / why not |
|---|---|---|---|
| Bucket | Yes | Yes | One private bucket per environment in `ap-south-1` |
| Object | Yes | Yes | One S3 key per document; each upload creates a new S3 object version |
| Object key | Yes | Yes | Opaque UUID path (section 2.3) |
| System metadata | Yes | Yes | `Content-Type`, `ContentLength`, `ETag`, `LastModified` shown in Inspector |
| User-defined metadata (`x-amz-meta-*`) | Yes | Yes | ASCII-only `cv-doc-id`, `cv-owner-id`. Cannot be edited after upload; changing needs a copy |
| Object tags | Yes | Yes | `project=cloudvault`, `env=<env>` for cost tracking and cleanup. No user data in tags |
| Versioning | Yes | Yes | Enabled at setup. Once enabled it can only be suspended, never turned off |
| Delete markers | Yes | Yes | Soft delete creates one; undelete removes it |
| Presigned URLs | Yes | Yes | GET only, 120 s expiry, bound to a VersionId |
| Storage classes | Yes | Yes | STANDARD, STANDARD_IA, GLACIER_IR only |
| Intelligent-Tiering | Yes | **No** | It is AWS's own automatic tiering with a per-object monitoring charge. Our heuristic is separate and says so |
| Lifecycle rules | Yes | Yes (small) | Noncurrent-version expiry, abort incomplete multipart, expired delete-marker cleanup. Not used for tiering because tiering here is per-object and driven by our access log |
| Event notifications | Yes | Yes | `s3:ObjectCreated:Put` to Lambda. Delivery is at-least-once, so Lambda is idempotent |
| IAM | Yes | Yes | Least-privilege backend user and Lambda role |
| Block Public Access | Yes | Yes | All four settings on |
| SSE-S3 encryption | Yes | Yes | Default encryption (`VERIFY` default behavior on new buckets) |
| SSE-KMS | Yes | **No** | Extra cost and key-policy complexity, no assignment value |
| CORS | Yes | **No** | Uploads are proxied; downloads are plain navigation to the presigned URL, so the browser never makes a cross-origin fetch to S3. Deliberate choice |
| Multipart upload | Yes | **No** | Needed for large files only. The 10 MiB cap makes single PUT sufficient. The lifecycle abort rule is a safety net |
| Object Lock | Yes | **No** | Irreversibility risk and scope creep |
| Additional checksums (SHA-256) | Yes | Yes | Backend sends SHA-256 on PUT; S3 verifies it (`VERIFY` boto3 parameter names) |
| Server access logs / CloudTrail data events | Yes | **No** | Delayed/best-effort or extra cost. We use an application access log |
| Storage Lens / Storage Class Analysis | Yes | **No** | Real AWS analytics tools. Ours is separate and says so |

## 2.2 Bucket configuration

| Item | Decision | Reason |
|---|---|---|
| Name | `cloudvault-{env}-{6 random lowercase alphanumerics}` | Bucket names are globally unique |
| Region | `ap-south-1` | Close to the developer; pricing differs by region (`VERIFY`) |
| Versioning | Enabled by `infrastructure/setup_s3.py` | Required for version history, soft delete, restore |
| Block Public Access | All 4 settings ON | Private by default |
| Bucket policy | Deny requests where `aws:SecureTransport` is false | TLS only |
| Default encryption | SSE-S3 (`VERIFY`) | Free, no key management |
| CORS | **Not configured** | See matrix |
| Metadata on objects | `cv-doc-id`, `cv-owner-id` (ASCII), `Content-Type` | Immutable without a copy; keep minimal |
| Tags on objects | `project=cloudvault`, `env=<env>` | Cost tracking/cleanup |
| Lifecycle | (1) abort incomplete multipart after 1 day; (2) expire noncurrent versions after 90 days; (3) remove expired delete markers | Caps version cost. `VERIFY` whether rules 2 and 3 can share one rule |
| Notification | `s3:ObjectCreated:Put`, prefix `documents/`, destination Lambda `cloudvault-processor` | `Copy` events (restore, tier change) deliberately not subscribed |

**Consequence of lifecycle rule (2):** old versions can disappear from S3 after 90 days while the DB still lists them. The app MUST handle this: HTTP 410 `VERSION_EXPIRED` and mark the version `S3_MISSING`.

## 2.3 Object key strategy

**Chosen format:** `documents/{owner_uuid}/{document_uuid}`

| Concern | Handling |
|---|---|
| Filename collisions | None (UUID keys) |
| Renaming | Changes only DB `display_name`; no S3 copy |
| Unicode, long names, path traversal | Filename never appears in the key or on local disk |
| Enumeration/privacy | Random UUIDs; filename leaks nowhere in S3 |
| Versioning | One key per document; S3 versions are the file's versions |
| DB references | `documents.s3_key` plus `document_versions.s3_version_id` |
| Per-user IAM prefix | Owner segment permits future prefix scoping |
| Content type | Stored as the object's `Content-Type`; no file extension in key |

**Rejected:** `users/{id}/{filename}` because it is user-controlled, collides on re-upload, and exposes filenames.

## 2.4 S3 behaviors baked into the design (VERIFY items flagged)

1. `[AWS]` `CopyObject` onto the same key in a versioned bucket creates a **new version**. `VERIFY`
2. The old version stays stored and billed until deleted. Therefore "apply recommendation" **deletes the old version after the copy**.
3. `HeadObject` does not return a storage class for STANDARD objects. The Inspector MUST display "STANDARD" when the field is absent. `VERIFY`
4. A plain `DeleteObject` (no VersionId) on a versioned bucket creates a delete marker and returns its VersionId. Data remains.
5. `DeleteObject` with a VersionId permanently removes exactly that version or marker.
6. Deleting the current delete marker by its VersionId makes the latest remaining version current again (this is how undelete works).
7. A presigned URL carries the permissions of the credentials that signed it, so the backend IAM user needs `s3:GetObjectVersion` for version-bound URLs.
8. Presigned URL generation is local signing (no S3 request is made).
9. Everything that looks like a folder in S3 is just a key prefix.

See also: [`diagrams/04-versioning-and-delete.png`](docs/diagrams/04-versioning-and-delete.png)

![Versioning and delete semantics](docs/diagrams/04-versioning-and-delete.png)

## 2.5 Delete semantics (exact definitions)

| Term | Definition in CloudVault |
|---|---|
| Normal (soft) delete | `DeleteObject` without VersionId: S3 adds a delete marker; DB `status=DELETED`; marker VersionId stored in `documents.delete_marker_version_id`; no data removed |
| Delete marker | Placeholder current version that makes the key appear deleted |
| Historical versions | All prior S3 versions, retained and billed until expired or permanently deleted |
| Undelete | Delete the stored marker by its VersionId; DB `status=ACTIVE` |
| Permanent delete | Allowed only when `status=DELETED`. List all versions and delete markers for the key and delete each by VersionId; only after S3 reports success, delete DB rows. On partial failure return 502 and keep the document `DELETED` so the call can be repeated safely |
| Restore | `CopyObject` from an old VersionId onto the same key, producing a **new** current version (old versions untouched). Allowed only when `status=ACTIVE` |


---

# 3. Architecture and Workflows

## 3.1 Logical architecture

![Logical architecture](docs/diagrams/01-logical-architecture.png)

Source: [`diagrams/01-logical-architecture.mmd`](docs/diagrams/01-logical-architecture.mmd)

## 3.2 Deployment architecture

![Deployment architecture](docs/diagrams/02-deployment-architecture.png)

Source: [`diagrams/02-deployment-architecture.mmd`](docs/diagrams/02-deployment-architecture.mmd)

**External request flow:** Browser to Vercel (static files) to Render API (JWT) to Neon and S3 (IAM user keys in Render env vars). Browser to S3 happens **only** through a short-lived presigned GET URL.

## 3.3 Trust boundaries

![IAM and trust boundaries](docs/diagrams/11-iam-trust-boundaries.png)

## 3.4 Feature classification

| Feature | Class |
|---|---|
| Versions, delete markers, presigned URLs, storage class, tags, event notifications | `[AWS]` |
| Version numbers, trash view, access log, recommendations, dashboard, duplicate detection | `[APP]` |
| Bucket-style file table and S3 Inspector panel | `[UI]` |

## 3.5 Conventions for all workflows

- Every mutating call on one document takes a Postgres row lock: `SELECT ... FOR UPDATE` on the `documents` row.
- Errors use `{"error":{"code","message","details"}}` (see doc 05).
- "Failure" below lists the main outcomes; the complete table is in doc 09.
- DB changes for uploads commit only after S3 succeeds (see doc 09 section 9.3).

## 3.6 Workflows

### W1. User opens application
- **Actor:** User. **Request:** `GET /api/auth/me`, then `GET /api/dashboard/summary`.
- **Backend:** verify JWT, aggregate. **AWS:** none. **DB:** read.
- **Success:** 200. **Failure:** 401, redirect to login.

### W2. Upload file (new document)
- **Actor:** User. **Request:** `POST /api/documents` (multipart).
- **Backend:** validate (doc 05 section 5.3); read at most 10 MiB into memory; compute SHA-256; open transaction; insert `documents` and `document_versions` (v1) and `flush()` so the partial unique index fires **before** S3; `PutObject`; set `s3_version_id`; insert `processing_jobs(PENDING)`; commit.
- **AWS:** `PutObject` (versioned; metadata, tags, SHA-256 checksum) returns VersionId. **DB:** rows exist only after commit.
- **Success:** 201 document JSON.
- **Failure:** 400/413/415/422 validation; 409 `NAME_EXISTS`; 502 S3 error (transaction rolled back, nothing stored). If the commit fails after the PUT, delete that exact S3 version (best effort).

![Upload sequence](docs/diagrams/03-upload-sequence.png)

### W3. Download file
- **Request:** `GET /api/documents/{id}/download?version=n` (default: current).
- **Backend:** check owner and `status=ACTIVE`; presign GET with VersionId and `ResponseContentDisposition=attachment; filename*=UTF-8''<encoded display_name>`; insert `access_logs` row.
- **AWS:** `generate_presigned_url` (local signing, no S3 call). **DB:** `access_logs` +1.
- **Success:** 200 `{url, expires_in}`. **Failure:** 404, 409 `DOCUMENT_DELETED`, 410 `VERSION_EXPIRED`. If the log insert fails, the download is refused (fail closed).

### W4. Delete file (soft)
- **Request:** `DELETE /api/documents/{id}`.
- **Backend:** lock row; `DeleteObject` **without** VersionId; set `status=DELETED`, `deleted_at`, `delete_marker_version_id`.
- **AWS:** delete marker created, no data removed. **DB:** status updated.
- **Success:** 204 (idempotent if already deleted). **Failure:** 502 then rollback.

### W5. Upload new version
- **Request:** `POST /api/documents/{id}/versions` (multipart).
- **Backend:** same as W2 under the document lock; `version_number = max+1`; if SHA-256 equals the current version return 200 `{duplicate:true}` and create nothing.
- **AWS:** `PutObject` on the same key returns a new VersionId. **DB:** new version row + processing job; `current_version_id` updated.
- **Success:** 201. **Failure:** 404, 409 `DOCUMENT_DELETED`, 413, 415, 502.

### W6. Restore version
- **Request:** `POST /api/documents/{id}/versions/{n}/restore`.
- **Backend:** lock; verify `ACTIVE` and source version `state=ACTIVE`; `CopyObject` from the old VersionId onto the same key; insert version row with `origin=RESTORE`, `restored_from_version=n`; copy the extraction fields from the source job if it succeeded (so no reprocessing is needed; Copy events are not subscribed).
- **AWS:** `CopyObject` creates a new current version; old versions untouched.
- **Success:** 201. **Failure:** 404 version, 410 expired, 409 deleted, 502.

### W7. Search
- **Request:** `GET /api/documents?q=&type=&storage_class=&status=&sort=&page=&page_size=`.
- **Backend:** SQL `ILIKE` on `display_name` and the current version's processing `text_excerpt`; always scoped by `owner_id`; paginated. **AWS:** none.
- **Success:** 200. **Failure:** 422 on bad params.

### W8. View metadata
- **Request:** `GET /api/documents/{id}` (DB fields) and `GET /api/documents/{id}/s3-info` (live).
- **AWS:** `HeadObject` and `GetObjectTagging` for the selected VersionId.
- **Success:** 200. **Failure:** 502 for the live call (DB data from `/documents/{id}` still returns).

### W9. Record access
- Happens inside W3. Event type `DOWNLOAD`, logged **when the presigned URL is issued**. S3 does not report it back; a leaked URL used elsewhere is not counted.

### W10. Generate storage recommendation
- **Request:** `POST /api/recommendations/refresh`.
- **Backend:** run the engine (doc 07) over the user's current versions of `ACTIVE` documents; mark previous `OPEN` rows `STALE`; insert new `OPEN` rows for each recommendation. **AWS:** none.
- **Success:** 200 list.

### W11. Apply storage recommendation
- **Request:** `POST /api/recommendations/{id}/apply`.
- **Backend:** lock document; re-run engine; if the result differs from the stored recommendation return 409 `STALE_RECOMMENDATION` (mark `STALE`); `CopyObject` onto the same key with the target `StorageClass`; update the version row (`s3_version_id`, `storage_class`, `storage_class_changed_at`); mark `APPLIED`; commit; then `DeleteObject` with the **old** VersionId (best effort; reconcile cleans leftovers).
- **Success:** 200. **Failure:** 409 stale, 502 S3.

![Apply recommendation sequence](docs/diagrams/06-apply-recommendation-sequence.png)

### W12. S3 event processing
- S3 sends `ObjectCreated:Put` (prefix `documents/`) to Lambda asynchronously. Delivery is at-least-once.

### W13. Lambda processing
- Lambda decodes the key (`unquote_plus`), skips objects over 5 MB, downloads the object, extracts, then `POST /api/internal/processing-results`. See doc 08.

![Lambda processing sequence](docs/diagrams/07-lambda-processing-sequence.png)

### W14. Failed upload
- Validation failure: no state changed. S3 failure: DB rolled back, nothing stored. Commit failure after a successful PUT: compensating delete of that S3 version; if that also fails, reconcile detects it.

### W15. Failed processing
- Deterministic failures (unsupported, too large, corrupt): reported as `SKIPPED` or `FAILED`; Lambda returns success. Transient failures (callback 5xx, 404, 409, network): Lambda raises so the platform retries (`VERIFY` async retry behavior). If retries are exhausted the job stays `PENDING`; the UI shows "Stalled" after 10 minutes.

### W16. Retry
- **Request:** `POST /api/documents/{id}/processing/retry?version=n` (Tier 3 feature).
- **Backend:** allowed if the job is `FAILED` or stalled `PENDING`; set `PENDING`, `attempts+1`; invoke Lambda asynchronously with a synthetic S3-shaped event.
- **Success:** 202. **Failure:** 409 if `SUCCEEDED`/`SKIPPED`, 502.


---

# 4. Database Design

PostgreSQL 15+, SQLAlchemy 2.x, Alembic. All timestamps are `timestamptz` in UTC. IDs are UUID v4 unless noted. Only the six tables below exist.

![ER diagram](docs/diagrams/09-er-diagram.png)

Source: [`diagrams/09-er-diagram.mmd`](docs/diagrams/09-er-diagram.mmd)

## users
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | varchar(254) | NOT NULL; unique index on `lower(email)` |
| password_hash | varchar(255) | NOT NULL (bcrypt) |
| created_at | timestamptz | default `now()` |

## documents
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| owner_id | uuid FK to users | NOT NULL, indexed |
| display_name | varchar(255) | NOT NULL, sanitized |
| s3_key | varchar(200) | NOT NULL, UNIQUE |
| status | varchar(10) | `ACTIVE` or `DELETED`, default `ACTIVE`, CHECK |
| current_version_id | uuid FK to document_versions | nullable (circular FK; use `use_alter=True`) |
| delete_marker_version_id | varchar(64) | nullable; S3 VersionId of the marker |
| deleted_at | timestamptz | nullable |
| created_at, updated_at | timestamptz | default `now()` |

- **Partial unique index:** `(owner_id, lower(display_name)) WHERE status='ACTIVE'`
- Index `(owner_id, status)`

## document_versions
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| document_id | uuid FK ON DELETE CASCADE | NOT NULL |
| version_number | int | NOT NULL, starts at 1 |
| s3_version_id | varchar(64) | NOT NULL after commit |
| size_bytes | bigint | NOT NULL, CHECK > 0 |
| content_type | varchar(100) | NOT NULL |
| sha256 | char(64) | NOT NULL |
| storage_class | varchar(20) | default `STANDARD` |
| storage_class_changed_at | timestamptz | default = `created_at` |
| origin | varchar(10) | `UPLOAD` or `RESTORE` |
| restored_from_version | int | nullable |
| state | varchar(12) | `ACTIVE` or `S3_MISSING`, default `ACTIVE` |
| created_at | timestamptz | default `now()` (seed script may backdate) |

- Unique `(document_id, version_number)`; unique `(document_id, s3_version_id)`; index `(document_id, created_at)`.

## access_logs
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| document_id | uuid FK ON DELETE CASCADE | |
| version_id | uuid FK to document_versions ON DELETE CASCADE | |
| user_id | uuid FK to users | |
| event_type | varchar(12) | default `DOWNLOAD` |
| accessed_at | timestamptz | default `now()` |

- Index `(version_id, accessed_at DESC)`.

## processing_jobs
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| version_id | uuid FK ON DELETE CASCADE | **UNIQUE** (idempotency anchor) |
| document_id | uuid FK | indexed |
| status | varchar(10) | `PENDING`, `SUCCEEDED`, `FAILED`, `SKIPPED` |
| attempts | int | default 0 |
| error_code | varchar(40) | nullable |
| error_message | varchar(500) | nullable |
| page_count, word_count | int | nullable |
| text_excerpt | text | nullable, at most 4000 chars |
| created_at, finished_at | timestamptz | `finished_at` nullable |

## storage_recommendations
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| version_id | uuid FK ON DELETE CASCADE | |
| current_class, recommended_class | varchar(20) | |
| rule_id | varchar(20) | e.g. `R3_TO_IA` |
| reason | text | human-readable |
| signals | jsonb | size, age_days, a30, a90, idle_days, days_in_class |
| status | varchar(10) | `OPEN`, `APPLIED`, `DISMISSED`, `STALE` |
| created_at, resolved_at | timestamptz | `resolved_at` nullable |

- **Partial unique index:** `(version_id) WHERE status='OPEN'`.

## Rejected tables (do not add)
Sessions, roles, per-class history, upload-attempts (idempotency comes from SHA-256 + name rule), tags (read live from S3).

## State machines

![State machines](docs/diagrams/10-state-machines.png)

Source: [`diagrams/10-state-machines.mmd`](docs/diagrams/10-state-machines.mmd)


---

# 5. API Contract

## 5.1 Conventions

- Base path `/api`. JSON unless stated. All IDs are UUIDs; non-UUID path IDs return 422.
- Auth: `Authorization: Bearer <JWT>` unless marked **Public**. JWT is HS256, 60 minutes.
- Another user's resource returns **404** (never 403) so existence is not leaked.
- Error body (all errors): `{"error":{"code":"STRING","message":"human text","details":{}}}`
- Pagination: `page` (1-based, default 1), `page_size` (default 25, max 100). Responses: `{"items":[...],"total":N,"page":P,"page_size":S}`.
- Timestamps are ISO 8601 UTC strings.

## 5.2 Error codes (closed set)

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Malformed request, bad UUID, bad parameter |
| `UNAUTHORIZED` | 401 | Missing/invalid/expired JWT or internal token, or bad login |
| `NOT_FOUND` | 404 | Resource missing or owned by someone else |
| `EMAIL_EXISTS` | 409 | Registration with an existing email |
| `EMPTY_FILE` | 400 | Zero-byte upload |
| `FILE_TOO_LARGE` | 413 | More than 10 MiB |
| `UNSUPPORTED_TYPE` | 415 | Extension not allowed or magic bytes mismatch |
| `INVALID_FILENAME` | 422 | Empty after sanitization, `.`/`..`, or over 150 chars |
| `NAME_EXISTS` | 409 | Active document with same name (case-insensitive) exists; `details.existing_document_id` |
| `DOCUMENT_DELETED` | 409 | Operation not allowed on a document in trash |
| `NOT_DELETED` | 409 | Undelete/permanent-delete on a document not in trash |
| `VERSION_NOT_FOUND` | 404 | No such version number |
| `VERSION_EXPIRED` | 410 | Version row exists but S3 no longer has it (lifecycle) |
| `STALE_RECOMMENDATION` | 409 | Engine result changed since recommendation was created |
| `JOB_NOT_RETRYABLE` | 409 | Job is `SUCCEEDED` or `SKIPPED` |
| `VERSION_NOT_REGISTERED` | 409 | Internal callback arrived before the upload committed (Lambda must retry) |
| `RATE_LIMITED` | 429 | Rate limit exceeded |
| `STORAGE_ERROR` | 502 | S3 failure (timeout, 5xx, other) |
| `STORAGE_FORBIDDEN` | 502 | S3 AccessDenied (logged server-side; generic message to client) |
| `DB_UNAVAILABLE` | 503 | Database unreachable |

## 5.3 Upload validation (all upload endpoints)

**Limits and checks, applied in this order:**
1. Read the stream in chunks and abort with 413 as soon as total bytes exceed **10 MiB (10,485,760)**. Never buffer more than 10 MiB + 1 byte.
2. Zero bytes: 400 `EMPTY_FILE`.
3. Sanitize filename (rules below). Failure: 422 `INVALID_FILENAME`.
4. Extension allowlist (case-insensitive): `.pdf .txt .md .csv .docx .png .jpg .jpeg`. Else 415 `UNSUPPORTED_TYPE`.
5. Magic bytes must match: PDF `%PDF-`; PNG `89 50 4E 47 0D 0A 1A 0A`; JPEG `FF D8 FF`; DOCX `PK\x03\x04`. Text types (`.txt .md .csv`) must decode as UTF-8 with no NUL bytes. Else 415.
6. Content type is **derived from the verified extension** via a fixed map. The client-supplied `Content-Type` is ignored.
7. Compute SHA-256 of the bytes.

**Filename sanitization (function `sanitize_filename`):**
1. Unicode-normalize to NFC.
2. Take only the last component after splitting on both `/` and `\`.
3. Remove control characters (Unicode category Cc) and NUL.
4. Strip leading/trailing whitespace.
5. Reject if empty, `.`, or `..`.
6. Reject if longer than 150 characters (422, do not truncate silently).
7. The sanitized result is used **only** as `display_name`. It is never part of an S3 key and never used as a filesystem path. Nothing is written to local disk.

**Duplicates:**
- Same sanitized name (case-insensitive) as an `ACTIVE` document, **same SHA-256 as its current version**: return 200 `{"duplicate":true,"document":{...}}`, no changes.
- Same name, different content on `POST /documents`: 409 `NAME_EXISTS` (client may then call the new-version endpoint).
- On `POST /documents/{id}/versions`: same SHA-256 as the current version returns 200 `{"duplicate":true}`; otherwise a new version is created.

## 5.4 Response shapes

```jsonc
// Document
{
  "id": "uuid", "display_name": "report.pdf", "status": "ACTIVE",
  "current_version": {
    "version_number": 2, "size_bytes": 18874368, "content_type": "application/pdf",
    "storage_class": "STANDARD", "created_at": "...", "origin": "UPLOAD", "state": "ACTIVE"
  },
  "version_count": 2,
  "processing": { "status": "SUCCEEDED", "page_count": 12, "word_count": 4210, "stalled": false },
  "created_at": "...", "updated_at": "...", "deleted_at": null
}

// Version
{ "version_number": 1, "size_bytes": 1234, "content_type": "application/pdf",
  "sha256": "hex", "storage_class": "STANDARD", "origin": "UPLOAD",
  "restored_from_version": null, "state": "ACTIVE", "is_current": false, "created_at": "..." }

// S3 info (live)
{ "bucket": "...", "key": "documents/<owner>/<doc>", "version_id": "...", "etag": "...",
  "content_length": 1234, "content_type": "application/pdf", "last_modified": "...",
  "storage_class": "STANDARD", "metadata": {"cv-doc-id":"...","cv-owner-id":"..."},
  "tags": {"project":"cloudvault","env":"dev"}, "source": "live-from-s3" }

// Recommendation
{ "id": "uuid", "document_id": "uuid", "display_name": "old-report.pdf", "version_number": 1,
  "current_class": "STANDARD", "recommended_class": "STANDARD_IA", "rule_id": "R3_TO_IA",
  "reason": "Low access frequency (1 in 90 days), idle 40 days",
  "signals": {"size_bytes":18874368,"age_days":120,"a30":0,"a90":1,"idle_days":40,"days_in_class":120},
  "estimate": null, "status": "OPEN", "created_at": "..." }
```

`estimate` is `null` unless `pricing.json` is configured (doc 07 section 7.5).

## 5.5 Endpoints

### Auth

| Route | Auth | Request | Success | Errors | Notes |
|---|---|---|---|---|---|
| `POST /auth/register` | Public | `{email, password}` (password at least 8 chars, max 128) | 201 `{id,email}` | 409 `EMAIL_EXISTS`, 422 | Email lowercased and trimmed |
| `POST /auth/login` | Public | `{email, password}` | 200 `{access_token, token_type:"bearer"}` | 401, 429 | Rate limit 5/min/IP. Same 401 for unknown email and wrong password |
| `GET /auth/me` | Yes | none | 200 `{id,email}` | 401 | |

### Documents

| Route | Purpose | Request | Success | Errors | Idempotency |
|---|---|---|---|---|---|
| `POST /documents` | Upload new document | multipart field `file` | 201 Document; 200 `{duplicate:true,document}` | 400, 413, 415, 422, 409 `NAME_EXISTS`, 502, 503 | Retry-safe via duplicate rule |
| `GET /documents` | List/search | `q, status(active\|deleted, default active), type, storage_class, sort(name\|updated\|size, prefix - for desc; default -updated), page, page_size` | 200 paginated Documents | 422 | Safe |
| `GET /documents/{id}` | Detail (versions summary, job status) | none | 200 Document | 404 | Safe |
| `GET /documents/{id}/s3-info` | Live S3 `HeadObject` + tags | `?version=n` optional | 200 S3 info | 404, 410, 502 | Safe |
| `GET /documents/{id}/versions` | Version list (newest first) | none | 200 `{items:[Version]}` | 404 | Safe |
| `POST /documents/{id}/versions` | Upload new version | multipart `file` | 201 Version; 200 `{duplicate:true}` | 404, 409 `DOCUMENT_DELETED`, 413, 415, 502 | Same-content retry is a no-op |
| `POST /documents/{id}/versions/{n}/restore` | Restore as new version | none | 201 Version | 404, 409 `DOCUMENT_DELETED`, 410, 502 | **Not idempotent**: each call creates a new version (documented) |
| `GET /documents/{id}/download` | Presigned URL + access log | `?version=n` default current | 200 `{url, expires_in:120}` | 404, 409 `DOCUMENT_DELETED`, 410, 502 | Each call logs |
| `DELETE /documents/{id}` | Soft delete | none | 204 | 404, 502 | Idempotent |
| `POST /documents/{id}/undelete` | Remove delete marker | none | 200 Document | 404, 409 `NOT_DELETED`, 409 `NAME_EXISTS` (name now taken), 502 | Safe to repeat; a second call returns 409 `NOT_DELETED` and changes nothing |
| `DELETE /documents/{id}/permanent` | Delete all versions and markers | `?confirm=true` required | 204 | 404, 409 `NOT_DELETED`, 422 if confirm missing, 502 (partial) | Idempotent, safe to repeat |
| `GET /documents/{id}/access-logs` | Access history | `page` | 200 paginated `{accessed_at, version_number, event_type}` | 404 | Safe |
| `GET /documents/{id}/processing` | Job per version | none | 200 `{items:[{version_number,status,attempts,error_code,page_count,word_count,stalled}]}` | 404 | Safe |
| `POST /documents/{id}/processing/retry` | Re-invoke Lambda (Tier 3) | `?version=n` | 202 | 404, 409 `JOB_NOT_RETRYABLE`, 502 | Repeat while `PENDING` is a no-op |

### Dashboard and recommendations

| Route | Purpose | Request | Success | Errors | Idempotency |
|---|---|---|---|---|---|
| `GET /dashboard/summary` | Totals | none | 200 `{document_count, current_bytes, total_bytes_all_versions, accesses_30d, bytes_by_class:{STANDARD,STANDARD_IA,GLACIER_IR}, open_recommendations, jobs_by_status:{...}}` | none | Safe |
| `GET /recommendations` | List | `?status=open\|applied\|dismissed\|stale` default open | 200 `{items:[Recommendation]}` | 422 | Safe |
| `POST /recommendations/refresh` | Recompute | none | 200 `{items:[Recommendation]}` | none | Same result for same data and clock |
| `POST /recommendations/{id}/apply` | Apply | none | 200 Recommendation | 404, 409 `STALE_RECOMMENDATION`, 502 | Already `APPLIED` returns 200 no-op |
| `POST /recommendations/{id}/dismiss` | Dismiss | none | 200 Recommendation | 404 | Idempotent |

### Internal and health

| Route | Auth | Request | Success | Errors |
|---|---|---|---|---|
| `POST /internal/processing-results` | Header `X-Internal-Token` (constant-time compare) | `{document_id, s3_version_id, status(SUCCEEDED\|FAILED\|SKIPPED), error_code?, error_message?, page_count?, word_count?, text_excerpt?}` | 200 `{"status":"updated"}`; 200 `{"status":"already_processed"}` if job not `PENDING` | 401; 409 `VERSION_NOT_REGISTERED` (so Lambda retries); 422 |
| `GET /health` | Public | none | 200 `{"status":"ok"}` after DB ping | 503 |

**Notes**
- The internal route is excluded from the public OpenAPI schema in production.
- Internal callback: `text_excerpt` truncated to 4000 chars server-side; `error_message` to 500.
- `stalled` = job `PENDING` and `created_at` older than 10 minutes.


---

# 6. Frontend and UI

## 6.1 Stack
React 18, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query (server state), Recharts, lucide-react. The JWT is kept in a small auth context backed by `sessionStorage`. A thin fetch wrapper (`src/api/client.ts`) attaches the token, parses the standard error shape, and redirects to login on 401. Never use `dangerouslySetInnerHTML`.

## 6.2 Screens (final list)

1. **Login/Register**
2. **Dashboard**
3. **Documents** (table + Trash tab)
4. **Document Details** (tabs: Overview, Versions, Access, S3 Inspector, Processing)
5. **Optimization**
6. **About** (`[AWS]` vs `[APP]` explainer, useful for the viva)

**Removed from the original idea:** Settings (nothing to set), standalone Version History and Processing Status pages (they are tabs).

## 6.3 Shared components
`AppShell`, `UploadDropzone`, `DocumentTable`, `StorageClassBadge`, `ProcessingBadge`, `ConfirmDialog`, `Toast`, `EmptyState`, `ErrorState`, `Skeleton`, `SourceBadge` (labels data as "S3" or "CloudVault").

## 6.4 State rules
- Every query has a skeleton (loading), an error state with a Retry button, and an empty state.
- Client-side validation (type, size) is a convenience only; the server is authoritative.
- After any mutation, invalidate the affected queries (`documents`, `document:{id}`, `dashboard`, `recommendations`).
- The 409 `NAME_EXISTS` response opens a dialog offering **Upload as new version** (calls the versions endpoint with `existing_document_id`).

## 6.5 Screen specifications

| Screen | Layout | Actions | Feedback | Loading / empty / error | Destructive confirmation |
|---|---|---|---|---|---|
| Login | Centered card | Login; switch to register | Inline field errors | Button spinner | n/a |
| Dashboard | 4 stat cards (documents, current storage, total incl. versions, accesses 30d); bar chart bytes by storage class; open-recommendations card; processing status counts | Click cards to navigate | n/a | Skeleton cards; empty: "Upload your first document" | n/a |
| Documents | Search bar, filters (type, class), dropzone above table. Columns: name, type, size, class badge, versions, processing badge, updated, row menu | Upload, download, details, delete. Trash tab: undelete, permanent delete | Toast "Uploaded v1" | Skeleton rows; empty state; 409 dialog | Delete: "Moves to trash (S3 delete marker)". Permanent: user types the filename to confirm |
| Document Details | Header (name, badges, actions) + tabs. **Versions:** table with Restore. **Access:** event list. **S3 Inspector:** key, VersionId, ETag, class, tags, metadata, badge "Live from S3". **Processing:** status, pages, words, Retry | Upload new version, restore, download, retry | Toasts | Per-tab skeletons; 502 shows "S3 unavailable, retry" | Restore dialog: "Creates a new version from vN" |
| Optimization | Banner: "CloudVault's heuristic, not AWS Intelligent-Tiering". Table: file, current to recommended, reason, signals, estimate (only if pricing present) | Refresh, Apply, Dismiss | Toast "Storage class changed to STANDARD_IA" | Empty: "No recommendations; files are new or already optimal" | Apply dialog: "Copies the object to the new class and removes the old version" |
| About | Static: architecture diagram and the S3-vs-app table | none | n/a | n/a | n/a |

## 6.6 Visual style
Neutral slate palette, one accent colour, rounded cards, generous whitespace, responsive down to phone width. **Do not** imitate the orange AWS Console look; it should read as a polished student cloud project.

## 6.7 Wording rules (honesty)
- Any text about recommendations MUST say "CloudVault's heuristic".
- Access counts MUST be labelled "recorded by CloudVault".
- Estimates, if shown, MUST state what they exclude (retrieval, requests, minimum duration, transfer).
- Never write that "AWS calculated" a recommendation.


---

# 7. Intelligent Storage Optimization (Recommendation Engine)

> **This is CloudVault's heuristic. It is not an AWS algorithm and it is not S3 Intelligent-Tiering.**
> The UI, README and demo MUST say so. CloudVault analyzes application-level access history and recommends a storage class.

## 7.1 Inputs (per current version of an `ACTIVE` document)

| Input | Source |
|---|---|
| `size_bytes` | `document_versions.size_bytes` |
| `storage_class` | `document_versions.storage_class` |
| `age_days` | now minus `document_versions.created_at` |
| `days_in_class` | now minus `storage_class_changed_at` |
| `a30`, `a90` | count of `access_logs` for the version in the last 30/90 days |
| `idle_days` | days since the later of last access and `created_at` |

**Access-history limitation.** S3 does not expose an application-friendly last-accessed timestamp for every object. CloudVault records an `access_logs` row each time it issues a presigned download URL. Use of a leaked URL elsewhere is not counted.

## 7.2 Thresholds (configurable via env, shown in UI)

| Name | Default | Env var | Rationale |
|---|---|---|---|
| `MIN_SIZE` | 131072 (128 KiB) | `REC_MIN_SIZE` | IA/GIR classes bill a minimum object size, so small files gain nothing (`VERIFY`) |
| `MIN_AGE_IA` | 30 days | `REC_MIN_AGE_IA_DAYS` | STANDARD_IA has a 30-day minimum storage duration (`VERIFY`) |
| `IA_MAX_ACCESSES_90D` | 2 | `REC_IA_MAX_ACCESSES_90D` | Definition of "rarely accessed" |
| `IA_MIN_IDLE` | 30 days | (constant = `MIN_AGE_IA`) | Avoid moving recently used files |
| `GIR_MIN_AGE` | 90 days | `REC_GIR_MIN_AGE_DAYS` | GLACIER_IR has a 90-day minimum storage duration (`VERIFY`) |
| `PROMOTE_ACCESSES_30D` | 3 | `REC_PROMOTE_ACCESSES_30D` | Frequent retrieval makes IA/GIR retrieval charges likely to outweigh storage savings |
| `COOLDOWN` | 30 days | `REC_COOLDOWN_DAYS` | Prevent flapping between classes |

These are heuristics for a student project; they are **not claimed to be optimal**.

## 7.3 Edge cases

| Case | Behavior |
|---|---|
| Recently uploaded (age under 30 days) | KEEP, reason `TOO_NEW` |
| Small file | KEEP, `SMALL_OBJECT` |
| Deleted document | Not evaluated |
| Noncurrent versions | Not evaluated (only the current version is eligible because apply replaces it) |
| Unsupported class (anything other than STANDARD, STANDARD_IA, GLACIER_IR) | KEEP, `UNSUPPORTED_CLASS` |
| Class changed recently | KEEP, `COOLDOWN` |
| Conflicting signals | Strict rule priority R1, R2, R3; first match wins |
| `state=S3_MISSING` version | Not evaluated |

## 7.4 Algorithm (pure function, `now` injected)

```text
function evaluate(v, now, cfg) -> Result(kind, target, rule_id, reason, signals)

  signals = {
    size: v.size_bytes, cls: v.storage_class,
    age_days: days(now - v.created_at),
    days_in_class: days(now - v.storage_class_changed_at),
    a30: count(access_logs where version=v and accessed_at >= now-30d),
    a90: count(access_logs where version=v and accessed_at >= now-90d),
    idle_days: days(now - max(last_access(v) or v.created_at, v.created_at))
  }

  if v.cls not in {STANDARD, STANDARD_IA, GLACIER_IR}:  return KEEP("UNSUPPORTED_CLASS")
  if v.size < cfg.MIN_SIZE:                              return KEEP("SMALL_OBJECT")
  if signals.age_days < cfg.MIN_AGE_IA:                  return KEEP("TOO_NEW")
  if signals.days_in_class < cfg.COOLDOWN:               return KEEP("COOLDOWN")

  # R1: promote hot data out of cold classes
  if v.cls in {STANDARD_IA, GLACIER_IR} and signals.a30 >= cfg.PROMOTE_ACCESSES_30D:
      return RECOMMEND(STANDARD, "R1_PROMOTE",
        "Accessed {a30} times in 30 days; retrieval charges likely outweigh storage savings")

  # R2: very cold data to Glacier Instant Retrieval
  if v.cls in {STANDARD, STANDARD_IA} and signals.age_days >= cfg.GIR_MIN_AGE
      and signals.a90 == 0:
      return RECOMMEND(GLACIER_IR, "R2_TO_GIR", "Not accessed in 90 days and older than 90 days")

  # R3: rarely accessed data to Standard-IA
  if v.cls == STANDARD and signals.a90 <= cfg.IA_MAX_ACCESSES_90D
      and signals.idle_days >= cfg.IA_MIN_IDLE:
      return RECOMMEND(STANDARD_IA, "R3_TO_IA",
        "Low access frequency ({a90} in 90 days), idle {idle_days} days")

  return KEEP("ACTIVE_USE")
```

![Recommendation decision flow](docs/diagrams/05-recommendation-flow.png)

**Properties (must hold):** deterministic; pure (no I/O inside `evaluate`; the access counts are passed in or loaded by the caller); explainable (reason text is built from signals); testable (tests in doc 10 U1 to U8); no machine learning.

**Evaluation order matters:** the four KEEP guards run first, then R1, R2, R3. Note R2 is checked before R3, so a file that qualifies for both gets GLACIER_IR.

## 7.5 Cost estimates (optional, Tier 3)

- **Never** display invented percentages or monetary savings.
- If `pricing.json` exists (filled by the developer from the official AWS S3 pricing page for the chosen region, containing `region`, `verified_on`, `source_url` and per-GB-month storage prices per class), the UI shows: *"Storage-only estimate ≈ size_GB × (price_current − price_target) per month; excludes retrieval, requests, minimum duration and data transfer."*
- If the file is missing, show only the qualitative impact. `estimate` in the API is `null`.

## 7.6 Apply flow (summary)
Lock document, re-evaluate, 409 `STALE_RECOMMENDATION` on mismatch, `CopyObject` to the same key with the new StorageClass (source = current VersionId), update DB, mark `APPLIED`, commit, then delete the old S3 version. See diagram `06-apply-recommendation-sequence` (doc 03, W11).

## 7.7 Demo data caveat
Real uploads are never 30+ days old at demo time, so `scripts/seed_demo.py` uploads real files to real S3 and **backdates `created_at` and access-log rows in the database only**. S3's own `LastModified` stays real. The demo and README MUST disclose this.


---

# 8. Event-Driven Processing (AWS Lambda)

## 8.1 Decision
**Option B: S3 triggers Lambda.** (Option A would be the backend processing files itself.)

**Why Lambda is justified:** it is the canonical S3 event-driven pattern; it demonstrates event delivery, at-least-once semantics, retries and idempotency; and it keeps document parsing off the small free-tier web server.
**Honest trade-off:** for an app this small, the backend alone could do the work. State this in the viva. If time runs short, Lambda is the first Tier 2 item to drop (move extraction into the backend).

## 8.2 Design

| Aspect | Design |
|---|---|
| Trigger | `s3:ObjectCreated:Put`, prefix `documents/`. Copy events (restore, tier change) are intentionally not subscribed |
| Event handling | For each record use `s3.bucket.name`, `s3.object.key` (**URL-decode with `unquote_plus`**), `s3.object.size`, `s3.object.versionId` (`VERIFY` presence for versioned buckets). Parse `document_id` as the last segment of the key |
| Size gate | If size is over **5 MB (5,242,880 bytes)**: report `SKIPPED` with `error_code=TOO_LARGE`; never download |
| Supported types | `pdf` (page count, words, excerpt via `pypdf`); `txt/md/csv` (words, excerpt); `docx` (zipfile + XML text, words, excerpt); `png/jpg`: `SKIPPED` with `NO_EXTRACTION`. Type decided from the object's `Content-Type` via `HeadObject` or the GetObject response |
| Memory safety | Download with a byte cap (read at most 5 MB + 1); never load unbounded data |
| Idempotency | Anchor = (`document_id`, `s3_version_id`). The backend applies a result only if the job is `PENDING`; otherwise it returns 200 `already_processed` |
| Retries | S3 invokes Lambda **asynchronously**; on function error the platform retries (default 2 more attempts; `VERIFY`). **Deterministic** outcomes (unsupported, too large, corrupt) are reported and Lambda **returns success**. **Transient** outcomes (callback 5xx/timeout, 409 `VERSION_NOT_REGISTERED`, 404) **raise** so the platform retries |
| Race | The event can arrive before the upload commits. The backend answers 409 `VERSION_NOT_REGISTERED`; Lambda raises and retries |
| Stalled jobs | `PENDING` for over 10 min is shown as "Stalled" and can be retried (Tier 3 endpoint) |
| Timeout / memory | 60 s timeout, 256 MB memory. Callback HTTP timeout 45 s (tolerates a Render cold start) |
| Logging | One JSON line per record to stdout (CloudWatch). Log group retention **7 days**. Never log file content, tokens or presigned URLs |
| Permissions | Execution role: CloudWatch Logs write + `s3:GetObject`, `s3:GetObjectVersion` on `documents/*`. Resource policy on the function allows `s3.amazonaws.com` to invoke it with `SourceArn`=bucket and `SourceAccount`=account |
| Callback auth | `X-Internal-Token` shared secret over HTTPS. Replays are harmless (idempotent) |
| Packaging | Pure-Python dependencies only (`pypdf`, stdlib) built via `lambda/build.sh` (`pip install -t build pypdf` then zip) to avoid native-wheel problems. Use a currently supported Python Lambda runtime (`VERIFY`) |

## 8.3 Processing result mapping

| Situation | Callback `status` | `error_code` |
|---|---|---|
| Extraction succeeded | `SUCCEEDED` | none |
| Object over 5 MB | `SKIPPED` | `TOO_LARGE` |
| Image types | `SKIPPED` | `NO_EXTRACTION` |
| Corrupt/unparseable file | `FAILED` | `CORRUPT` |
| Encrypted PDF | `FAILED` | `ENCRYPTED` |
| Unexpected exception while parsing | `FAILED` | `PARSE_ERROR` |
| Callback 5xx / timeout / 404 / 409 | (no callback result) raise for retry | n/a |

## 8.4 Sequence

![Lambda processing sequence](docs/diagrams/07-lambda-processing-sequence.png)

Source: [`diagrams/07-lambda-processing-sequence.mmd`](docs/diagrams/07-lambda-processing-sequence.mmd)

## 8.5 Lambda environment variables

`BACKEND_WEBHOOK_URL`, `INTERNAL_WEBHOOK_SECRET`, `MAX_PROCESS_BYTES=5242880`.


---

# 9. Security, Failure Modes and Consistency

## 9.1 Security architecture

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


---

# 10. Testing

## 10.1 Strategy

| Level | Scope | Needs AWS? |
|---|---|---|
| Unit | Recommendation engine (injected clock), filename sanitization, file-type validation, key generation, authorization helpers, presign argument construction | No |
| Integration (local) | FastAPI `TestClient` + Postgres test DB + `moto` for S3: upload, download, delete, versioning, metadata, access logging | No (moto may differ from real S3, so it is not the final word) |
| AWS integration | `pytest -m aws` against a **dedicated throwaway test bucket** with versioning on: real versioning and delete markers, presigned URL fetch, `CopyObject` storage-class change, HEAD behavior for STANDARD, Lambda invoke + callback | **Yes** (real credentials; never in default CI) |
| Lambda | Handler with sample S3 event JSON: URL-encoded keys, versionId, oversized object, corrupt PDF | No |
| End-to-end | Manual checklist on the deployed site mirroring the demo script (Playwright optional, Tier 3) | Yes |

Default `pytest` run MUST pass with no AWS credentials. AWS tests are skipped unless `-m aws` is passed.

## 10.2 Test matrix

| ID | Scenario | Input | Expected |
|---|---|---|---|
| U1 | Rule R3 positive | 120-day-old, 18 MB, STANDARD, 1 access in 90 d, idle 40 d | Recommend STANDARD_IA, rule R3 |
| U2 | Boundary age | 29 vs 30 days | 29: `TOO_NEW`; 30: eligible |
| U3 | Small file | 100 KiB, 200 days | `SMALL_OBJECT` |
| U4 | Promote | STANDARD_IA, 4 accesses in 30 d | Recommend STANDARD (R1) |
| U5 | Cooldown | class changed 10 days ago | `COOLDOWN` |
| U6 | Very cold | STANDARD, 100 d, 0 accesses | GLACIER_IR (R2) |
| U7 | Unsupported class | `DEEP_ARCHIVE` | `UNSUPPORTED_CLASS` |
| U8 | Recently accessed | idle 5 d | No recommendation (`ACTIVE_USE`) |
| V1 | Normal filename | `report.pdf` | Accepted |
| V2 | Path traversal | `../../etc/passwd.txt` | Reduced to `passwd.txt` (used only as display name) |
| V3 | Backslash path | `..\..\x.pdf` | Reduced to `x.pdf` |
| V4 | Control chars | `a\x00b.pdf` | Control chars removed |
| V5 | Very long name | 300 chars | 422 |
| V6 | Unicode name | `résumé 日本.pdf` | Accepted, NFC-normalized; key unaffected |
| V7 | Empty file | 0 bytes | 400 |
| V8 | Size boundary | 10485760 / 10485761 bytes | 201 / 413 |
| V9 | Wrong magic | `.pdf` containing text | 415 |
| V10 | Disallowed extension | `.exe` | 415 |
| I1 | Upload then list | valid pdf | 201; appears in list as v1 |
| I2 | Same name, same content | repeat | 200 `duplicate:true` |
| I3 | Same name, new content | different bytes | 409 `NAME_EXISTS` |
| I4 | New version | upload v2 | v2 current; v1 retained |
| I5 | Restore v1 | restore | New version 3 with v1 content |
| I6 | Soft delete | DELETE | Hidden from list; in Trash; marker exists |
| I7 | Undelete | undelete | Active again; marker removed |
| I8 | Permanent delete | after trash | All S3 versions and markers gone; DB rows gone |
| I9 | Download logs access | download | One `access_logs` row |
| I10 | Apply recommendation | apply R3 | Class `STANDARD_IA`; old S3 version deleted; DB version id updated |
| I11 | Stale recommendation | add access, then apply | 409 |
| S1 | Other user's document | `GET /documents/{id}` | 404 |
| S2 | No token | any protected route | 401 |
| S3 | Expired presigned URL | wait over 120 s | S3 denies |
| S4 | Internal endpoint without token | POST | 401 |
| S5 | Login brute force | 6 attempts/min | 429 |
| C1 | Concurrent version uploads | 2 parallel | Versions n and n+1, no error |
| C2 | Concurrent deletes | 2 parallel | Both 204, one marker |
| C3 | Same-name concurrent create | 2 parallel | One 201, one 409; no orphan S3 object |
| C4 | Duplicate Lambda event | send twice | Second returns `already_processed` |
| A1 | Real versioning (AWS) | put, put, delete | Two versions plus a marker |
| A2 | HEAD of STANDARD (AWS) | head | Storage class field absent |
| A3 | S3 event delivery (AWS) | upload | Lambda callback received, job `SUCCEEDED` |
| A4 | S3 error (moto) | injected 500 | 502, DB rolled back |
| L1 | Oversized object | 6 MB text | `SKIPPED/TOO_LARGE` |
| L2 | Corrupt PDF | bad bytes | `FAILED/CORRUPT`, Lambda returns success |
| L3 | URL-encoded key | `+` / `%20` in key | Decoded correctly |

## 10.3 Critical end-to-end flows (manual or Playwright)
1. Register, login, upload, see it in the list.
2. Upload v2, restore v1, verify version count and content.
3. Delete, see in Trash, undelete.
4. Download, check the access log entry.
5. Seed data, refresh recommendations, apply one, verify class in the AWS Console.
6. Upload a PDF, wait for processing status `SUCCEEDED` with page and word counts.


---

# 11. Deployment, Cost Control, IAM and Environment

## 11.1 Deployment architecture decision

| Option | Verdict |
|---|---|
| **Vercel (frontend)** | **Chosen.** Free static hosting, HTTPS, env vars, GitHub deploys (check Hobby plan terms; `VERIFY`) |
| **Render (backend)** | **Chosen.** Simple FastAPI deploy from GitHub, HTTPS, env vars. The free tier spins down when idle, causing a cold start of tens of seconds (`VERIFY`). Mitigation: warm it before the demo |
| **Neon (Postgres)** | **Chosen.** Free managed Postgres. Use `sslmode=require` and `pool_pre_ping=True` because compute can auto-suspend (`VERIFY`) |
| Render's own Postgres | Rejected: the free database may expire after a limited period (`VERIFY`) |
| Railway | Rejected: free usage is trial-based (`VERIFY`) |
| AWS-hosted backend (EC2, App Runner, ECS) | Rejected: higher cost and complexity, cost surprises |
| GitHub Pages | Works for the frontend only; no advantage over Vercel here |

**Process**
- Backend start command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` (do not rely on a paid pre-deploy feature; `VERIFY`).
- Frontend build variable: `VITE_API_BASE_URL`.
- Warm-up: call `/api/health` about 5 minutes before the demo.
- Fallback: demo locally against real S3 and show the deployed URL separately.

## 11.2 AWS cost control

Confirm all of the following against current AWS pricing and the account's free-tier/credit program (`VERIFY`). Do not claim anything is free without checking.

**What can incur charges:** S3 storage (GB-month), PUT/COPY/LIST requests, GET requests, data transfer out; storage-class changes use COPY requests; IA and GIR classes have per-GB retrieval charges, minimum storage duration and minimum billable object size; **every noncurrent version is billed until expired** (mitigated by lifecycle rule and by deleting the old version after a tier change); Lambda requests and duration; CloudWatch Logs ingestion/storage.

**Avoid:** KMS, CloudTrail data events, Storage Lens advanced, Intelligent-Tiering monitoring fees.

**Unexpected-cost risks:** forgotten versions, huge uploads (capped at 10 MiB), loops that call COPY, log groups without retention.

**Controls:** AWS Budget with a very low email alert threshold (`VERIFY` pricing); no root account for daily work, MFA on; 10 MiB cap and rate limits; log retention 7 days.

**Teardown after the demo/semester:**
1. Empty the bucket **including all versions and delete markers**, then delete the bucket.
2. Delete the Lambda function and its log group.
3. Delete the backend IAM user + access keys and the Lambda role.
4. Remove the Budget if no longer needed.

## 11.3 IAM design

![IAM and trust boundaries](docs/diagrams/11-iam-trust-boundaries.png)

### Backend IAM user `cloudvault-backend` (runtime)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow",
     "Action": ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketVersioning"],
     "Resource": "arn:aws:s3:::BUCKET"},
    {"Effect": "Allow",
     "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject",
                "s3:DeleteObjectVersion", "s3:PutObjectTagging", "s3:GetObjectTagging"],
     "Resource": "arn:aws:s3:::BUCKET/documents/*"},
    {"Effect": "Allow",
     "Action": "lambda:InvokeFunction",
     "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:cloudvault-processor"}
  ]
}
```
`s3:ListBucket` is also needed for the startup `HeadBucket` check (`VERIFY` exact permission for HeadBucket). Presigned URLs only work with the permissions of the signer, so `s3:GetObjectVersion` is required for version-bound URLs. `CopyObject` additionally needs read permission on the source (covered by `GetObject`/`GetObjectVersion`) and `PutObject` on the destination; add `s3:GetObjectVersionTagging` only if copying tags requires it (`VERIFY`).

### Lambda execution role `cloudvault-processor-role`
- CloudWatch Logs: the AWS managed basic execution policy, or an equivalent inline policy scoped to its own log group.
- `s3:GetObject`, `s3:GetObjectVersion` on `arn:aws:s3:::BUCKET/documents/*`.
- Resource-based policy on the function allowing `s3.amazonaws.com` to invoke it (`SourceArn` = bucket, `SourceAccount` = account id).

### Human/developer
- No root use. Use an IAM user or Identity Center with MFA.
- Setup scripts need permission to create the bucket, configure it, create IAM roles/users and create the Lambda function.
- `AdministratorAccess` is acceptable only transiently for first-time setup (document this in `infrastructure/README.md`). It is **never** given to the application.

## 11.4 Environment configuration

### `.env.example` (committed, placeholders only)
```dotenv
# ---- Backend (local development) ----
APP_ENV=development
DATABASE_URL=postgresql+psycopg://cloudvault:cloudvault@localhost:5432/cloudvault
JWT_SECRET=change-me-long-random
JWT_EXPIRE_MINUTES=60
FRONTEND_ORIGIN=http://localhost:5173
AWS_REGION=ap-south-1
S3_BUCKET=cloudvault-dev-xxxxxx
AWS_PROFILE=cloudvault-dev          # or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
LAMBDA_FUNCTION_NAME=cloudvault-processor
INTERNAL_WEBHOOK_SECRET=change-me
MAX_UPLOAD_BYTES=10485760
PRESIGN_EXPIRY_SECONDS=120
REC_MIN_SIZE=131072
REC_MIN_AGE_IA_DAYS=30
REC_GIR_MIN_AGE_DAYS=90
REC_IA_MAX_ACCESSES_90D=2
REC_PROMOTE_ACCESSES_30D=3
REC_COOLDOWN_DAYS=30
PRICING_FILE=./pricing.json         # optional

# ---- Frontend ----
VITE_API_BASE_URL=http://localhost:8000

# ---- Lambda (set in function configuration, not in Git) ----
BACKEND_WEBHOOK_URL=https://<render-app>/api/internal/processing-results
INTERNAL_WEBHOOK_SECRET=change-me
MAX_PROCESS_BYTES=5242880
```

### Production differences
- `APP_ENV=production`.
- `DATABASE_URL` from Neon with `sslmode=require`.
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` of the backend IAM user set in Render; **no** `AWS_PROFILE`.
- `FRONTEND_ORIGIN` = the Vercel URL.
- Strong random `JWT_SECRET` and `INTERNAL_WEBHOOK_SECRET` (different values).


---

# 12. Repository, Phases and Build Order

## 12.1 Repository structure

```text
cloudvault/
├── AGENTS.md
├── README.md
├── CLOUDVAULT_FULL_SPEC.md
├── frontend/                 # React + Vite + Tailwind (src/pages, components, api, hooks)
├── backend/
│   ├── app/
│   │   ├── main.py  config.py  db.py  models.py  schemas.py  security.py
│   │   ├── routers/          # auth, documents, versions, recommendations, dashboard, internal, health
│   │   ├── services/         # s3_service.py, document_service.py, recommendation_engine.py, validation.py
│   │   └── scripts/          # reconcile.py, seed_demo.py
│   ├── alembic/
│   ├── tests/                # unit/, integration/, aws/
│   ├── requirements.txt
│   └── Dockerfile (optional)
├── lambda/
│   ├── handler.py
│   ├── build.sh              # pip install -t build pypdf; zip
│   └── tests/
├── infrastructure/
│   ├── setup_s3.py           # bucket, versioning, BPA, SSE-S3, lifecycle, policy, notification
│   ├── policies/             # backend-iam.json, lambda-role.json, bucket-policy.json
│   └── README.md             # manual steps and teardown
├── docs/                     # this documentation + diagrams/
├── docker-compose.yml        # local Postgres only
├── .env.example
├── .gitignore
└── README.md
```

Single repo, no monorepo tooling. No Terraform: a Python setup script plus JSON policies is enough and easier to explain.

## 12.2 Phases

| Phase | Objective | Key tasks | Depends on | Acceptance |
|---|---|---|---|---|
| 0 | Freeze scope | Confirm this spec; AWS account safeguards (MFA, Budget) | none | Budget alert on |
| 1 | Scaffolding | Repo layout, FastAPI skeleton, Vite app, compose Postgres, config | 0 | `/health` OK; frontend runs |
| 2 | Database | Models, Alembic migration, constraints | 1 | `alembic upgrade head` creates all tables |
| 3 | S3 integration | `setup_s3.py`, `s3_service.py`, startup `HeadBucket` check | 1 | Real bucket private, versioned, lifecycle set |
| 4 | Core backend | Auth, upload, list, download, delete, undelete, permanent delete, access logging | 2, 3 | All core routes pass tests |
| 5 | Frontend core | Login, Documents, Details, Dashboard | 4 | Full flow in browser |
| 6 | Versioning | New version, restore, Versions tab | 4, 5 | Restore creates a new version |
| 7 | Access logging UI | Access tab, dashboard figures | 4 | Access events visible |
| 8 | Optimization | Engine, endpoints, page, seed script | 6, 7 | Apply changes real class |
| 9 | Lambda | Handler, packaging, S3 notification, callback endpoint, retry | 3, 4 | Job reaches `SUCCEEDED` |
| 10 | Security hardening | Rate limits, CORS, headers, validation review | 4 to 9 | Security checklist passes |
| 11 | Testing | Fill gaps, AWS test run | 4 to 10 | Suite green |
| 12 | Deployment | Vercel, Render, Neon, env vars, smoke test | 11 | Public URL works |
| 13 | Documentation | README, architecture, S3-vs-app, viva | 12 | Fresh clone follows README |
| 14 | Demo rehearsal | Seed data, run script twice | 13 | Script runs cleanly end to end |

## 12.3 Dependency graph

![Phase dependency graph](docs/diagrams/08-dependency-graph.png)

Source: [`diagrams/08-dependency-graph.mmd`](docs/diagrams/08-dependency-graph.mmd)

## 12.4 Definition of Done

The project is done only when every item is true **and demonstrable**:

- [ ] App runs locally from the README against a real S3 dev bucket.
- [ ] Upload, presigned download, soft delete, undelete and permanent delete work against real S3.
- [ ] Versioning: new version, restore and version list work; the AWS Console shows matching versions and delete markers.
- [ ] Access logging records downloads and appears in the UI.
- [ ] Recommendations generate, can be applied, and the real storage class changes in the Console; the old version is removed.
- [ ] Lambda processing works end to end (event, callback, status in UI).
- [ ] Bucket has Block Public Access on, no CORS, SSE-S3 default, lifecycle rules and bucket policy applied.
- [ ] Security checklist (doc 09 section 9.1) passes; no secrets in Git history.
- [ ] Unit and integration tests pass; the AWS test suite has been run at least once.
- [ ] Deployed frontend, backend and DB work over HTTPS; cold start documented.
- [ ] GitHub repo is clean (no `.env`, no build artifacts); README complete.
- [ ] Demo script has run end to end twice; seed script makes recommendations appear.
- [ ] Everything described in the README or demo is actually implemented.

## 12.5 Build order for a coding agent

Conventions: backend paths are under `backend/app/`, tests under `backend/tests/`. Tasks run strictly in order unless prerequisites say otherwise. Test IDs refer to doc 10.

### T1: Repo scaffold
- **Prereqs:** none
- **Create:** root files, `docker-compose.yml`, `.gitignore`, `.env.example`
- **Requirements:** layout per 12.1; Postgres service in compose; `.gitignore` covers `.env`, `node_modules`, `build/`, `__pycache__`, `*.zip`
- **Validation/acceptance:** `docker compose up` starts Postgres; `.env` is ignored by Git.

### T2: Backend skeleton
- **Prereqs:** T1
- **Create:** `main.py`, `config.py`, `db.py`, `routers/health.py`
- **Requirements:** settings from env (doc 11.4); `/api/health` pings the DB; global exception handler producing the standard error body (doc 05); CORS limited to `FRONTEND_ORIGIN`.
- **Acceptance:** `GET /api/health` returns 200.

### T3: Models and migration
- **Prereqs:** T2
- **Create:** `models.py`, `alembic/`
- **Requirements:** all six tables, indexes, CHECKs, partial unique indexes exactly as doc 04; circular FK via `use_alter`.
- **Validation:** `alembic upgrade head` succeeds on an empty DB; constraint tests (duplicate active name, duplicate open recommendation, duplicate job per version).

### T4: S3 setup script
- **Prereqs:** T1
- **Create:** `infrastructure/setup_s3.py`, `infrastructure/policies/*.json`, `infrastructure/README.md`
- **Requirements:** create bucket (region `ap-south-1`, correct `LocationConstraint`), enable versioning, Block Public Access (all 4), SSE-S3, lifecycle rules (doc 02.2), TLS-deny bucket policy; **idempotent**; prints manual IAM steps. Notification config is added in T17.
- **Acceptance:** re-running is safe; the Console shows all settings.

### T5: S3 service
- **Prereqs:** T2, T4
- **Create:** `services/s3_service.py`
- **Requirements:** boto3 client with SigV4, region, standard retries (3), connect timeout 5 s, read timeout 30 s. Functions: `put_object` (metadata, tags, SHA-256 checksum, returns VersionId), `copy_object` (source VersionId, optional StorageClass), `delete_current` (returns marker VersionId), `delete_version`, `delete_all_versions(key)`, `head`, `get_tags`, `list_versions(prefix)`, `presign_get(key, version_id, filename)`, startup `head_bucket`. Treat a missing `StorageClass` in HEAD as `STANDARD`. Map botocore errors to `STORAGE_ERROR` / `STORAGE_FORBIDDEN`.
- **Tests:** moto tests; `-m aws` A1, A2.

### T6: Validation service
- **Prereqs:** T2
- **Create:** `services/validation.py`
- **Requirements:** `sanitize_filename`, extension allowlist, magic-byte checks, UTF-8/NUL check, size-capped streaming read (413 at limit + 1), SHA-256, extension to content-type map (doc 05.3).
- **Tests:** V1 to V10.

### T7: Auth
- **Prereqs:** T3
- **Create:** `routers/auth.py`, `security.py`
- **Requirements:** bcrypt hashing, JWT (60 min), `get_current_user` dependency, rate limits (login 5/min/IP), generic 401 for bad login.
- **Tests:** S2, S5.

### T8: Document upload and list
- **Prereqs:** T5, T6, T7
- **Create/modify:** `routers/documents.py`, `services/document_service.py`
- **Requirements:** workflow W2; row-lock helper; compensation on failure; name rule + SHA-256 duplicate rule; list/search/filter/sort/pagination (doc 05).
- **Tests:** I1 to I3, C3, A4.

### T9: Download and access log
- **Prereqs:** T8
- **Modify:** `routers/documents.py`
- **Requirements:** W3; presign with VersionId and Content-Disposition; log insert fails closed; 409 and 410 handling.
- **Tests:** I9, S3.

### T10: Delete, undelete, permanent delete
- **Prereqs:** T8
- **Modify:** `routers/documents.py`
- **Requirements:** W4 and doc 02.5 semantics; permanent delete lists all versions and markers and deletes in batches, checks every per-key error, deletes DB rows only after full success.
- **Tests:** I6 to I8, C2.

### T11: Versions and restore
- **Prereqs:** T8
- **Create:** `routers/versions.py`
- **Requirements:** W5 and W6; 410 and `S3_MISSING` on missing S3 version.
- **Tests:** I4, I5, C1.

### T12: S3 Inspector API
- **Prereqs:** T8
- **Modify:** `routers/documents.py`
- **Requirements:** live `HeadObject` + tags; absent storage class means STANDARD; degrade gracefully on 502.
- **Tests:** moto + AWS.

### T13: Recommendation engine
- **Prereqs:** T3
- **Create:** `services/recommendation_engine.py`
- **Requirements:** doc 07 exactly; pure function; thresholds from config; optional `pricing.json` loader returning `null` when absent.
- **Tests:** U1 to U8.

### T14: Recommendation endpoints
- **Prereqs:** T13, T11
- **Create:** `routers/recommendations.py`
- **Requirements:** refresh/list/apply/dismiss; apply = lock, re-evaluate, copy, DB swap, then delete old version.
- **Tests:** I10, I11.

### T15: Dashboard API
- **Prereqs:** T8
- **Create:** `routers/dashboard.py`
- **Requirements:** aggregates per doc 05 (by class, totals, open recs, job counts).
- **Tests:** integration.

### T16: Lambda handler
- **Prereqs:** T5
- **Create:** `lambda/handler.py`, `lambda/build.sh`, `lambda/tests/`
- **Requirements:** doc 08 (decode event, size gate, extractors, callback with token, raise on transient errors, report deterministic failures).
- **Tests:** L1 to L3.

### T17: Lambda wiring
- **Prereqs:** T4, T16
- **Modify/create:** `infrastructure/`
- **Requirements:** deploy function, execution role, resource policy for S3 to invoke, S3 notification (`ObjectCreated:Put`, prefix `documents/`), log retention 7 days.
- **Tests:** A3 (AWS).

### T18: Processing endpoints
- **Prereqs:** T8, T16
- **Create/modify:** `routers/internal.py`, `routers/documents.py`
- **Requirements:** internal callback (token, idempotent, 409 `VERSION_NOT_REGISTERED`), processing status, optional retry via Lambda invoke.
- **Tests:** C4, S4.

### T19: Reconcile and seed scripts
- **Prereqs:** T8, T14
- **Create:** `scripts/reconcile.py`, `scripts/seed_demo.py`
- **Requirements:** reconcile per doc 09.3 with `--fix`; seed uploads real files and backdates `created_at` and access-log rows in the DB only.
- **Validation:** manual run; seed produces recommendations.

### T20: Frontend scaffold
- **Prereqs:** T2
- **Create:** `frontend/`
- **Requirements:** Vite, Tailwind, router, query client, API wrapper, auth context, shell.
- **Acceptance:** builds; login works.

### T21: Frontend core screens
- **Prereqs:** T8 to T10, T15, T20
- **Requirements:** Documents, Details, Dashboard with all states (doc 06).
- **Validation:** manual checklist.

### T22: Frontend versions, inspector, access, processing
- **Prereqs:** T11, T12, T18, T21
- **Requirements:** Restore, Inspector, Access list, Processing tab (+ retry if built).

### T23: Frontend optimization and About
- **Prereqs:** T14, T21
- **Requirements:** table, apply/dismiss dialogs, heuristic disclaimer, S3-vs-app table.

### T24: Security pass
- **Prereqs:** T8 to T18
- **Requirements:** CORS, rate limits, headers, error hygiene, no sensitive logs.
- **Tests:** S1 to S5.

### T25: Test completion
- **Prereqs:** T24
- **Requirements:** fill the doc 10 matrix; run `-m aws` once.
- **Acceptance:** suite green.

### T26: Deployment
- **Prereqs:** T25
- **Requirements:** Render, Vercel, Neon config; env vars; warm-up; smoke test (doc 11.1).
- **Acceptance:** the public flow works.

### T27: Documentation
- **Prereqs:** T26
- **Requirements:** README (setup, architecture, S3-vs-app, teardown), demo and viva sheets finalised.
- **Acceptance:** a fresh-clone walkthrough succeeds.

### T28: Demo rehearsal
- **Prereqs:** T27
- **Requirements:** run reconcile and seed; execute the doc 13 script twice.


---

# 13. Demonstration, Viva and Resume

## 13.1 Demo script (about 9 minutes)

| # | Step | Time | Show exactly |
|---|---|---|---|
| 1 | Problem | 0:30 | Documents need durable, versioned, private storage |
| 2 | What is S3 | 1:00 | Bucket, object, key, versioning, storage class; the About page |
| 3 | Architecture | 1:00 | Logical diagram; say what is `[AWS]` and what is `[APP]` |
| 4 | Upload | 0:45 | Upload a PDF in the app |
| 5 | S3 storage | 0:45 | In the Console show the private bucket and the object under `documents/...`; point out the key is a UUID |
| 6 | Versioning | 1:15 | Upload v2, restore v1, delete. Use "Show versions" to point out versions and the delete marker. Undelete |
| 7 | Download | 0:30 | Download; explain the 120 s presigned URL; show that the raw object URL without a signature fails |
| 8 | Access tracking | 0:30 | Access log; say it is application-recorded and why |
| 9 | Storage optimization | 1:15 | Optimization page; explain the rules labelled "CloudVault's heuristic"; **disclose that seeded documents have backdated creation dates** (S3 timestamps are real); apply one and show the storage class in the Console |
| 10 | Event processing | 0:45 | Lambda log + processing status with page and word counts |
| 11 | Enhancement recap | 0:15 | The optimizer is our logic on top of real S3 classes |
| 12 | Deployment | 0:30 | Public URL and GitHub repo |

Before the demo: warm the backend (`/api/health`), run `reconcile`, run `seed_demo`, and have the AWS Console open on the bucket with "List versions" on.

## 13.2 Viva preparation

### AWS / S3
- **What is S3?** A managed object store. Objects are stored in buckets and accessed through an API.
- **Object / bucket / key?** The object is data plus metadata. The bucket is a named, region-bound container. The key is the object's unique name within the bucket. "Folders" are only key prefixes.
- **Why S3?** Durable, scalable and the standard choice for file storage.
- **Storage classes?** Different price and retrieval trade-offs for the same data: STANDARD for frequent access; STANDARD_IA for infrequent access with retrieval charges; GLACIER_IR for rarely accessed data with millisecond retrieval. The colder archive classes require restores and are not used.
- **Versioning?** The bucket keeps every overwrite as a new version with a version ID.
- **Presigned URLs?** A URL signed with the signer's credentials that grants temporary access to one operation. It expires and carries the signer's permissions.
- **Why a private bucket?** Public buckets are an exposure risk. The backend checks ownership and issues URLs on demand.
- **Lifecycle rule?** A bucket rule that transitions or expires objects or versions by age or filter. We use it to expire old versions.
- **How does S3 trigger Lambda?** The bucket notification configuration sends events to the function, and S3 needs permission to invoke it. Delivery is at-least-once, so the handler is idempotent.
- **Delete with versioning enabled?** A plain delete adds a delete marker and keeps the data. Deleting with a VersionId permanently removes that version. Removing the marker makes the object visible again.

### Architecture
- **Why FastAPI?** Quick to build, typed validation, automatic API docs.
- **Why PostgreSQL?** Row locks, partial unique indexes, JSONB; a better production fit than SQLite.
- **Why not files in the database?** Binary data bloats the DB, scales poorly and costs more. S3 is built for objects.
- **Why S3 instead of local storage?** It survives restarts and redeploys (web hosts have ephemeral disks) and is durable.
- **Why Lambda? Why not?** It demonstrates S3's event-driven design and keeps parsing off the web server. For a tiny app the backend could do it alone, and we say so.
- **How do you handle failures?** Ordering, compensation and the reconcile script (doc 09.3).
- **How are credentials secured?** Server-side environment variables with least-privilege IAM; never sent to the browser.

### Enhancement
- **What exactly is it?** Storage recommendations from size, age and application-recorded access history, with one-click apply.
- **Is it an AWS feature?** No. S3 Intelligent-Tiering is a separate AWS feature. Ours is a transparent heuristic.
- **How is it calculated?** Deterministic rules (doc 07).
- **Why those thresholds?** They follow the minimum durations and sizes of the classes and a simple "rarely accessed" definition. They are configurable and not claimed to be optimal.
- **When access patterns change?** Rule R1 promotes frequently used data back to STANDARD; a cooldown prevents flapping.

### Security
- **Can users access another user's files?** No. Every query is owner-scoped and returns 404 for others.
- **Where are credentials?** In server environment variables.
- **Can the frontend access S3 directly?** Only via short-lived presigned download URLs.
- **What prevents malicious filenames?** Names are sanitized and never used for keys or paths.
- **How do presigned URLs work?** The signature is computed from request details and expiry with the signer's secret key; S3 recomputes and validates it.

## 13.3 Resume positioning

**Title:** CloudVault: Versioned Document Storage on Amazon S3

**One line:** A full-stack document manager using a private, versioned S3 bucket, with presigned-URL downloads, S3 event-triggered Lambda processing and a rule-based storage-class recommendation engine.

**Bullets (factually defensible only if implemented as specified):**
- Built a React/FastAPI/PostgreSQL application on a private, versioned Amazon S3 bucket, implementing upload, presigned-URL download, soft delete via delete markers, permanent delete and version restore with `CopyObject`.
- Designed a deterministic, unit-tested rule engine that recommends STANDARD, STANDARD_IA or GLACIER_IR from age, size and application-recorded access history, and applies changes with `CopyObject`.
- Implemented S3 `ObjectCreated` to Lambda document processing with idempotent callbacks, retry handling and stalled-job recovery.
- Handled S3/database consistency with per-document locking, compensating deletes and a reconciliation script; secured access with least-privilege IAM, per-user authorization and upload validation.

**Avoid these words** unless truly supported: scalable, enterprise-grade, highly available, AI-powered, production-ready.


---

# 14. Risks, Fallback, Final Scope and VERIFY List

## 14.1 Project risks

| Risk | Probability | Impact | Mitigation | Fallback |
|---|---|---|---|---|
| IAM/permission errors | High | Medium | Start from the doc 11 policies; run AWS tests early | Temporarily wider permissions in dev only, then tighten |
| Presigned URL / region issues | Medium | Medium | Region-specific client, SigV4; test early | Backend streams the download |
| S3 event wiring (permission, prefix) | Medium | Medium | `setup_s3.py` configures it; test with `lambda invoke` | Backend-only processing (drop Lambda, Tier 2) |
| Render cold start / Lambda callback timeout | High | Medium | 45 s callback timeout, retry, warm-up | Stalled + Retry UI |
| Deployment issues (CORS, env vars) | Medium | High | Deploy a thin slice by Phase 4 | Demo locally |
| DB/S3 inconsistency | Medium | Medium | Lock + compensation + reconcile | Manual cleanup |
| Unexpected AWS cost | Low | Medium | Budget alert, 10 MiB cap, teardown | Delete the bucket |
| Recommendation not demoable (no old data) | High | High | Seed script with backdated data, disclosed honestly | Show the unit-test table |
| Scope creep / time | High | High | Tier model | Drop Tier 3 |

## 14.2 Fallback tiers

- **Tier 1 (mandatory):** auth, upload, list, presigned download, soft delete + undelete, versions + restore, S3 Inspector, access log, dashboard, recommendations with apply, deployment, README.
- **Tier 2 (strongly recommended):** Lambda processing, permanent delete, reconcile script, seed script, lifecycle + bucket policy, AWS integration tests.
- **Tier 3 (optional):** processing retry, pricing estimates, tag editing, Playwright, dark mode, GitHub Actions, About page polish.

Dropping Tier 3 (and, in the worst case, Lambda from Tier 2, moving its work into the backend) still leaves a project that scores well against the rubric.

## 14.3 Final recommended scope

- **Stack:** React 18 + Vite + TypeScript + Tailwind; Python FastAPI + SQLAlchemy 2 + Alembic.
- **AWS services:** S3 (private, versioned, SSE-S3), Lambda (one function), IAM, CloudWatch Logs (7-day retention). Nothing else.
- **Database:** PostgreSQL (Neon in production, Docker locally), six tables (doc 04).
- **Features:** Tier 1 + Tier 2.
- **API:** REST under `/api` (doc 05). Uploads proxied through the backend. Downloads via presigned GET.
- **Deployment:** Vercel + Render + Neon + AWS. No Terraform. Setup via script and JSON policies.
- **Enhancement:** rule-based storage optimizer + S3-event Lambda pipeline.
- **Exclusions:** public bucket, direct-to-S3 browser uploads, multipart, KMS, Object Lock, Intelligent-Tiering integration, Glacier Flexible/Deep Archive, roles, sharing, AI.

## 14.4 Architecture audit: contradictions found and resolved

| Issue | Resolution |
|---|---|
| In a versioned bucket, applying a recommendation leaves the old version billed | Delete the old version after the copy |
| Restore and tier change both create `ObjectCreated:Copy` events | Subscribe to `Put` only |
| Objects uploaded during the demo are never old enough to be recommended | Disclosed backdating seed script (DB only) |
| Lifecycle expiry can remove versions the DB still lists | 410 `VERSION_EXPIRED` + `S3_MISSING` state; reconcile |
| A Lambda event can arrive before the DB commit | Backend returns 409 `VERSION_NOT_REGISTERED`, Lambda retries |
| S3 does not give application-friendly last-access time | Application-recorded `access_logs`, labelled as such |

## 14.5 VERIFY BEFORE IMPLEMENTATION

This specification was written without live access to AWS documentation. Resolve each item against official AWS documentation (and the relevant platform docs), then record the result in `docs/VERIFIED.md` (item, finding, source URL, date).

| # | Item | Where it matters |
|---|---|---|
| 1 | Minimum storage duration and minimum billable object size for STANDARD_IA and GLACIER_IR | Doc 07 thresholds |
| 2 | `HeadObject` omits the storage class for STANDARD objects | Inspector, T5, T12, A2 |
| 3 | `versionId` present in event records for versioned buckets; which events fire on `CopyObject` | Doc 08, T16, T17 |
| 4 | Async Lambda retry defaults; currently supported Python runtimes | Doc 08 |
| 5 | `NoncurrentVersionExpiration` and `ExpiredObjectDeleteMarker` in the same lifecycle rule | Doc 02, T4 |
| 6 | Default SSE-S3 encryption on new buckets; boto3 checksum parameters (SHA-256) | Doc 02, T4, T5 |
| 7 | `CopyObject` onto the same key to change storage class in a versioned bucket (and the VersionId returned) | W11, T14 |
| 8 | IAM actions needed for `HeadBucket` and `CopyObject` with tags | Doc 11 |
| 9 | Free-tier/credit terms for a new AWS account; Render, Neon and Vercel free-tier limits and behavior | Doc 11 |
| 10 | Regional pricing, only if `pricing.json` is used | Doc 07.5 |

Rule: if something is uncertain, do not invent an answer. Mark it `VERIFY BEFORE IMPLEMENTATION` in the code comment or PR and ask the human.
