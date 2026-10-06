# CloudVault: Full Specification (single file)

> Concatenation of `AGENTS.md`, `README.md` and `docs/01` to `docs/15`. Diagram images are referenced from `docs/diagrams/`.


---

# AGENTS.md: Instructions for any AI coding agent working on CloudVault

Read this file first, then `README.md`, then the docs in the order given in `README.md`.

> **CloudVault is a functional simulation of Amazon S3. It reproduces selected S3 concepts and semantics locally using PostgreSQL-backed simulated object storage. A real AWS account is not required.** Owner-approved amendments in `docs/15-amendments.md` override docs 01 to 14. The working checklist is `IMPLEMENTATION_PLAN.md`.

## Ground rules (non-negotiable)

1. **The docs are the specification.** Do not invent architecture, endpoints, tables, columns, thresholds, error codes or simulated S3 behavior that the docs do not define. If something is missing or contradictory, stop and ask the human. Do not guess.
2. **Never present application logic as native S3 behavior, and never imply real AWS calls.** Every feature is one of:
   - `[S3-SIM]` = CloudVault's simulation of a real Amazon S3 behavior
   - `[APP]` = CloudVault application logic that S3 does not provide
   - `[UI]` = interface representation only
3. **`VERIFY` markers.** An S3 behavior the simulation copies must be checked against official AWS documentation (docs.aws.amazon.com) before you write code that depends on it. No AWS account is needed. Record the result in `docs/VERIFIED.md` (create it, one line per item: item, finding, source URL, date).
4. **Never put secrets in Git.** No JWT or signing secrets, DB URLs or other credentials in any committed file. Only `.env.example` with placeholders is committed.
5. **Never expose secrets to the browser.** The frontend only receives a JWT and short-lived HMAC-signed download links.
6. **The simulated bucket is always private.** Stored objects are reachable only through an owner check or a valid signed link; never add a public object route.
7. **User-supplied filenames never become object keys or local file paths.** Uploads and stored object bytes are never written to local disk.
8. **Do not add** anything listed in `docs/01-overview-and-scope.md` under "Explicitly out of scope" (no multipart, KMS, Object Lock, Terraform, AI/ML, roles, sharing, etc.).
9. **Make targeted changes.** When modifying existing code, change only what the task requires and keep the existing style. Do not rewrite files wholesale.
10. **Work task by task** using `docs/12-repo-and-build-order.md`. Do not start a task before its prerequisites pass their acceptance checks. Run the listed tests for each task before moving on.
11. **Tests need nothing but a local PostgreSQL.** No AWS, no network services.
12. **Do not claim a feature in the README, UI or demo script unless it is implemented and tested.**

## Locked technology decisions

| Layer | Choice |
|---|---|
| Frontend | React 18, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query, Recharts, lucide-react |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, slowapi, bcrypt, PyJWT, python-multipart, pypdf (processing) |
| Database | PostgreSQL 15+ (Docker locally, Neon in production) |
| Object storage | Simulated S3 in PostgreSQL behind an `ObjectStorage` interface (no AWS account) |
| Processing | Durable `processing_jobs` queue with an in-process worker (replaces Lambda) |
| Deployment | Vercel (frontend), Render (backend and worker), Neon (DB and simulated store) |
| Tests | pytest, httpx/TestClient, local PostgreSQL |

## Definition of "done" for any task

- Code implemented exactly as specified.
- Listed tests written and passing.
- No new lint errors.
- No undocumented behavior added.
- Acceptance criteria in the task table are met.

---

# CloudVault: Implementation Documentation

> **CloudVault is a functional simulation of Amazon S3. It reproduces selected S3 concepts and semantics locally using PostgreSQL-backed simulated object storage. A real AWS account is not required.**
>
> It is a document manager with a FastAPI backend, PostgreSQL, a simulated versioned S3 bucket, background document processing, and a custom rule-based **Intelligent Storage Optimization** engine.
> It is a university assignment ("AWS Service Simulation & Enhancement", 10 marks) designed to also be a defensible resume project.

This repository holds the application (`backend/`, `frontend/`) and its specification (`AGENTS.md`, this README, `docs/`). For agents, start with [`AGENTS.md`](AGENTS.md).

Docs 01 to 14 are the original specification and were written for a real AWS deployment (S3 bucket, IAM, Lambda, CloudWatch). They are kept as written. [`docs/15-amendments.md`](docs/15-amendments.md) records the owner-approved changes and overrides them wherever they disagree; AM-7 explains, requirement by requirement, why the real-AWS parts were replaced by the simulation. **Do not create an AWS account, bucket, IAM user, Lambda function or AWS Budget for CloudVault, and do not set any AWS variables.** Nothing in the code reads them.

## What is simulated and what is CloudVault's own

| | Responsibility | Where |
|---|---|---|
| `[S3-SIM]` | Private bucket with versioning always on; object versions and delete markers; plain delete adds a marker, delete by version id removes exactly that version or marker; copy onto the same key creates a new version and can set the storage class; HEAD omits the class for STANDARD; MD5 ETag; SHA-256 checksum verified on write; user metadata and tags; storage classes STANDARD, STANDARD_IA, GLACIER_IR; time-limited signed download links (403 when missing, altered or expired); lifecycle rules (noncurrent-version expiry, expired delete-marker removal) | `backend/app/storage/` (`ObjectStorage` interface, `PostgresObjectStorage`, table `sim_object_versions`), `backend/app/scripts/lifecycle.py`. Each behavior is checked against the AWS documentation in [`docs/VERIFIED.md`](docs/VERIFIED.md) |
| `[APP]` | Users and login; documents and display names; version numbers; trash view; duplicate detection; access history; processing jobs and text extraction; storage recommendations; dashboard; reconciliation between the application tables and the store | `backend/app/services/`, `backend/app/processing/`, `backend/app/scripts/reconcile.py`, six application tables (doc 04) |
| `[UI]` | Document table, Details tabs, S3 Inspector panel ("Live from simulated S3"), Optimization and About pages | `frontend/src/` |

The simulated store and the application tables live in the same PostgreSQL database but are separate: the store's tables have no foreign keys to the application's. Object bytes are kept in PostgreSQL and never written to local disk. The total stored size (all versions) is capped by `SIM_STORAGE_LIMIT_BYTES` (default 300 MiB, sized for a free database tier); a write past it fails with 507 `STORAGE_LIMIT_EXCEEDED`.

## Architecture

Browser (React SPA) → FastAPI backend (JWT) → PostgreSQL, which holds both the application tables and the simulated S3 store. The browser never reads the store directly: it asks the backend for a download link and fetches the bytes from the backend's own signed route `GET /api/sim-s3/{bucket}/{key}`. A background worker inside the backend process extracts text from new versions. There is no Lambda, no event bus and no other service.

The diagrams in `docs/diagrams/` show the **original** real-AWS design; the About page in the app draws the accepted architecture.

## Implemented features

- Register, log in (email and password, JWT, 60 minutes). Rate limits: login 5/min per IP, register 10/min per IP, upload 20/min per user.
- Upload through the backend: up to 10 MiB, `.pdf .txt .md .csv .docx .png .jpg .jpeg`, checked by extension and file signature; parsed in memory. Same name and same content returns the existing document; same name and new content offers "Upload as new version".
- Document list with search (name and extracted text), type and storage-class filters, sorting and paging; a Trash tab.
- Download through a 120-second, version-bound signed link; every issued link is recorded in the access history ("recorded by CloudVault").
- Soft delete (delete marker), undelete (marker removed), permanent delete (every version and marker removed, then the rows).
- Version history, upload of a new version, restore of an old version as a new current version.
- S3 Inspector: key, version id, ETag, size, type, last-modified, storage class, metadata and tags, read from the simulated store.
- Document processing: page count, word count and a text excerpt for PDF, text, Markdown, CSV and Word files; images are skipped; files over 5 MB are skipped; failed or stalled jobs can be retried.
- Dashboard: document count, current and total stored bytes, downloads in the last 30 days, bytes by storage class, open recommendations, processing status counts.
- Storage recommendations (refresh, apply, dismiss) with the reason and signals behind each one; Apply changes the simulated storage class.
- Scripts: `reconcile`, `lifecycle`, `seed_demo` (below).

Not implemented: cost estimates (the API's `estimate` field is always `null`), tag editing, inline preview, dark mode, committed browser tests, CI. Deployment (Vercel, Render, Neon) is the next task (T26) and has not been done yet.

## Data rules worth knowing

- Object key: `documents/{owner_uuid}/{document_uuid}`. The filename is only a display name in the database; it never becomes a key or a file path.
- One key per document; simulated S3 versions are the document's versions.
- **A version row exists only after its object is stored** (AM-9): an upload first records the document as `PENDING` (reserving its name), stores the object with no database transaction open, then inserts the version with the store's version id. `document_versions.s3_version_id` is therefore NOT NULL. If storing fails, the document is marked `FAILED` and no version row is written.
- **A restored version gets its own new processing job** (AM-2), which the worker processes like any upload; nothing is copied from the source version's job.
- Apply keeps the version's number and row; it copies the object to the new class, points the row at the copy and then deletes the old copy.

## Storage recommendations are a heuristic

Recommendations come from **CloudVault's heuristic**, a fixed set of rules over each current version's size, age, time in its class and the downloads CloudVault recorded. It is **not AWS Intelligent-Tiering**, not an AWS algorithm and not machine learning, and it is not claimed to be optimal. It shows no savings figures. The thresholds (doc 07.2, `REC_*` variables) follow the real classes' minimum storage durations and sizes only as a rationale; nothing is billed. Downloads made with a link outside CloudVault are not counted.

## Processing worker and cold starts

Processing runs from the `processing_jobs` table, which acts as a durable queue. Every new version (upload or restore) gets a `PENDING` job in the same transaction that makes the version available. A worker thread inside the backend process (`PROCESSING_WORKER_ENABLED`, polling every `PROCESSING_POLL_SECONDS`) claims one job at a time with a 120-second lease. A transient failure leaves the job `PENDING` for another delivery, up to 3 deliveries; the UI shows "Stalled" for a job still `PENDING` after 10 minutes, and Retry starts it again. Duplicate deliveries cannot overwrite a result, and a restart loses nothing.

Because the worker lives in the web process, it only runs while the backend runs. On a free hosting tier that stops idle services, jobs wait as `PENDING` until the next request wakes the backend, and the first request after an idle period is slow (a cold start). Warm the backend with `GET /api/health` before a demo. The actual cold-start time is measured during deployment (T26).

## Demo data is backdated

Real uploads are never weeks old at demo time, so `python -m app.scripts.seed_demo` uploads real sample files through the normal services and then **backdates** their creation dates, storage-class dates and download history, in the application tables and the simulated store alike. This is what makes recommendations appear. The script prints this disclosure, and the demo must state it.

## Run locally

Requirements: Python 3.11+, Node.js, Docker (for PostgreSQL only).

```bash
cp .env.example .env                 # set POSTGRES_PORT and the DATABASE_URL port if 5432 is taken
docker compose up -d                 # PostgreSQL 15

cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000   # worker starts with the app

cd ../frontend
npm install
npm run dev                          # http://localhost:5173
```

Optional demo data and maintenance (from `backend/`):

```bash
.venv/bin/python -m app.scripts.seed_demo [--email EMAIL] [--password PASSWORD] [--reset]
.venv/bin/python -m app.scripts.reconcile [--fix]
.venv/bin/python -m app.scripts.lifecycle [--now ISO-8601] [--dry-run]
```

Checks:

```bash
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests alembic
cd frontend && npm run build && npm run lint
python3 tools/build_full_spec.py     # after editing AGENTS.md, README.md or docs/NN-*.md
```

Tests need only the local PostgreSQL; each run recreates its own `<database>_test` database. The test-to-requirement map is [`docs/TEST_MATRIX.md`](docs/TEST_MATRIX.md).

## Labels used everywhere

| Label | Meaning |
|---|---|
| `[S3-SIM]` | CloudVault's simulation of a real Amazon S3 behavior |
| `[APP]` | CloudVault application logic that S3 does not provide (never described as S3 behavior) |
| `[UI]` | A UI representation |
| `VERIFY` | An S3 behavior the simulation copies; check it against the AWS documentation and record it in `docs/VERIFIED.md` (no AWS account needed) |

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
| 15 | [15-amendments.md](docs/15-amendments.md) | **Owner-approved changes that override docs 01 to 14** |

A single concatenated copy of everything is in [`CLOUDVAULT_FULL_SPEC.md`](CLOUDVAULT_FULL_SPEC.md) for agents that prefer one file.

The working build checklist (task status, pending spec amendments, open questions) is [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md). It never overrides the spec.

## Diagrams

These diagrams belong to the original real-AWS specification (see doc 15). All diagrams exist as Mermaid source (`.mmd`, easiest for agents to read), PNG and SVG in [`docs/diagrams/`](docs/diagrams/).

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

As amended by doc 15:

- **No real AWS.** Object storage is a PostgreSQL-backed S3 simulation behind an `ObjectStorage` interface.
- The simulated bucket is **private**. Objects are downloaded only through a **120 s, version-bound, HMAC-signed link** to the app's own route.
- **Uploads go through the backend** (max 10 MiB, parsed in memory). No multipart.
- Object key is **`documents/{owner_uuid}/{document_uuid}`**. The filename lives only in the database.
- One key per document. **Simulated S3 versions = document versions.** A version row is written only after its object is stored, so `document_versions.s3_version_id` is NOT NULL (AM-9).
- Soft delete creates a **simulated delete marker**. Permanent delete removes **every version and marker** by version id.
- Storage classes STANDARD, STANDARD_IA and GLACIER_IR are simulated; **Apply** changes the simulated class.
- Access history is **application-recorded** (`access_logs`). We never claim S3 provides it.
- Recommendations are **CloudVault's own heuristic**, not AWS Intelligent-Tiering. No fake savings percentages.
- **Document processing** runs from a durable `processing_jobs` queue with an in-process worker (it replaces the original Lambda design). A restored version gets its own new job (AM-2).
- Auth: email and password with JWT (Bearer header). No OAuth, roles or sharing.

## Status of verification

The S3 behaviors that the simulation copies are checked against the AWS documentation and recorded in `docs/VERIFIED.md` (AM-7). No AWS account is needed.

---

# 1. Overview and Scope

> **Amended:** AM-7: CloudVault is a functional simulation of Amazon S3 backed by PostgreSQL; no real AWS account, bucket, Lambda or IAM is used. Read `[AWS]` as `[S3-SIM]`. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: demo evidence comes from the in-app S3 Inspector and the simulated store, not the AWS Console. Apply really changes the simulated storage class. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: this chapter describes the S3 behaviors CloudVault simulates in PostgreSQL. There is no real bucket, IAM or `setup_s3.py`; bucket settings are fixed simulation rules. Do not create the bucket, policy, notification or lifecycle configuration described below in AWS. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: S3 calls go to the simulated `ObjectStorage`; Lambda is replaced by the durable `processing_jobs` queue and an in-process worker; presigned URLs are HMAC-signed links to the app's own route. Diagrams still show the original AWS design. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-1: no application transaction is held across a storage call; per-document advisory locks serialize writes. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-1 and AM-9: transaction 1 flushes and commits only the `PENDING` document (name reserved), the store write runs with no transaction open, and transaction 2 inserts v1 with the returned `s3_version_id`. See [doc 15](docs/15-amendments.md).
- **Actor:** User. **Request:** `POST /api/documents` (multipart).
- **Backend:** validate (doc 05 section 5.3); read at most 10 MiB into memory; compute SHA-256; open transaction; insert `documents` and `document_versions` (v1) and `flush()` so the partial unique index fires **before** S3; `PutObject`; set `s3_version_id`; insert `processing_jobs(PENDING)`; commit.
- **AWS:** `PutObject` (versioned; metadata, tags, SHA-256 checksum) returns VersionId. **DB:** rows exist only after commit.
- **Success:** 201 document JSON.
- **Failure:** 400/413/415/422 validation; 409 `NAME_EXISTS`; 502 S3 error (transaction rolled back, nothing stored). If the commit fails after the PUT, delete that exact S3 version (best effort).

![Upload sequence](docs/diagrams/03-upload-sequence.png)

### W3. Download file

> **Amended:** AM-4 and AM-7: no storage call here; the link is an HMAC-signed app URL; 410 comes from the database `state`. See [doc 15](docs/15-amendments.md).
- **Request:** `GET /api/documents/{id}/download?version=n` (default: current).
- **Backend:** check owner and `status=ACTIVE`; presign GET with VersionId and `ResponseContentDisposition=attachment; filename*=UTF-8''<encoded display_name>`; insert `access_logs` row.
- **AWS:** `generate_presigned_url` (local signing, no S3 call). **DB:** `access_logs` +1.
- **Success:** 200 `{url, expires_in}`. **Failure:** 404, 409 `DOCUMENT_DELETED`, 410 `VERSION_EXPIRED`. If the log insert fails, the download is refused (fail closed).

### W4. Delete file (soft)

> **Amended:** AM-1: the store call runs outside the transaction, under the document's advisory lock, recorded by `pending_op='DELETE'`. See [doc 15](docs/15-amendments.md).
- **Request:** `DELETE /api/documents/{id}`.
- **Backend:** lock row; `DeleteObject` **without** VersionId; set `status=DELETED`, `deleted_at`, `delete_marker_version_id`.
- **AWS:** delete marker created, no data removed. **DB:** status updated.
- **Success:** 204 (idempotent if already deleted). **Failure:** 502 then rollback.

### W5. Upload new version

> **Amended:** AM-1 and AM-9: under the document lock, the store write runs first with no transaction open; the version row is inserted afterwards with its `s3_version_id`. See [doc 15](docs/15-amendments.md).
- **Request:** `POST /api/documents/{id}/versions` (multipart).
- **Backend:** same as W2 under the document lock; `version_number = max+1`; if SHA-256 equals the current version return 200 `{duplicate:true}` and create nothing.
- **AWS:** `PutObject` on the same key returns a new VersionId. **DB:** new version row + processing job; `current_version_id` updated.
- **Success:** 201. **Failure:** 404, 409 `DOCUMENT_DELETED`, 413, 415, 502.

### W6. Restore version

> **Amended:** AM-1, AM-2 and AM-9: the restored version gets its own new `PENDING` job (the source job is not copied) and its row is inserted only after the copy succeeded. See [doc 15](docs/15-amendments.md).
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

> **Amended:** AM-1 and AM-7: Apply runs in full against the simulated store; the copy runs outside the transaction. See [doc 15](docs/15-amendments.md).
- **Request:** `POST /api/recommendations/{id}/apply`.
- **Backend:** lock document; re-run engine; if the result differs from the stored recommendation return 409 `STALE_RECOMMENDATION` (mark `STALE`); `CopyObject` onto the same key with the target `StorageClass`; update the version row (`s3_version_id`, `storage_class`, `storage_class_changed_at`); mark `APPLIED`; commit; then `DeleteObject` with the **old** VersionId (best effort; reconcile cleans leftovers).
- **Success:** 200. **Failure:** 409 stale, 502 S3.

![Apply recommendation sequence](docs/diagrams/06-apply-recommendation-sequence.png)

### W12. S3 event processing

> **Amended:** AM-7: replaced by the durable `processing_jobs` queue and in-process worker. See [doc 15](docs/15-amendments.md).
- S3 sends `ObjectCreated:Put` (prefix `documents/`) to Lambda asynchronously. Delivery is at-least-once.

### W13. Lambda processing
- Lambda decodes the key (`unquote_plus`), skips objects over 5 MB, downloads the object, extracts, then `POST /api/internal/processing-results`. See doc 08.

![Lambda processing sequence](docs/diagrams/07-lambda-processing-sequence.png)

### W14. Failed upload
- Validation failure: no state changed. S3 failure: DB rolled back, nothing stored. Commit failure after a successful PUT: compensating delete of that S3 version; if that also fails, reconcile detects it.

### W15. Failed processing
- Deterministic failures (unsupported, too large, corrupt): reported as `SKIPPED` or `FAILED`; Lambda returns success. Transient failures (callback 5xx, 404, 409, network): Lambda raises so the platform retries (`VERIFY` async retry behavior). If retries are exhausted the job stays `PENDING`; the UI shows "Stalled" after 10 minutes.

### W16. Retry

> **Amended:** AM-7: retry resets the job to `PENDING` (`attempts+1`, `deliveries=0`); the worker picks it up. See [doc 15](docs/15-amendments.md).
- **Request:** `POST /api/documents/{id}/processing/retry?version=n` (Tier 3 feature).
- **Backend:** allowed if the job is `FAILED` or stalled `PENDING`; set `PENDING`, `attempts+1`; invoke Lambda asynchronously with a synthetic S3-shaped event.
- **Success:** 202. **Failure:** 409 if `SUCCEEDED`/`SKIPPED`, 502.

---

# 4. Database Design

> **Amended:** AM-1, AM-4, AM-7 and AM-9: extra document status values, `pending_op` columns, NOT NULL foreign keys, integrity checks, `processing_jobs.claimed_at`/`deliveries`, and the simulated-store table `sim_object_versions`. `document_versions.s3_version_id` stays NOT NULL and version `state` stays `ACTIVE`/`S3_MISSING` as below (AM-9). See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-6 and AM-7: adds `INTERNAL_ERROR` (500), `ACCESS_DENIED` (403) and `STORAGE_LIMIT_EXCEEDED` (507); removes `VERSION_NOT_REGISTERED`. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-4: the multipart body is parsed as a stream in memory, never through a temporary file. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: S3 info comes from the simulated store with `source: "simulated-s3"`. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-5: passwords are 8 to 128 characters and at most 72 bytes in UTF-8. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: `POST /internal/processing-results` is removed; signed downloads are served by `GET /sim-s3/{bucket}/{key}`. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: the Inspector badge reads "Live from simulated S3"; About explains the simulation with `[S3-SIM]`/`[APP]`/`[UI]` labels; Apply works. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-1 and AM-7: Apply changes the simulated storage class; the copy runs outside the application transaction. See [doc 15](docs/15-amendments.md).
Lock document, re-evaluate, 409 `STALE_RECOMMENDATION` on mismatch, `CopyObject` to the same key with the new StorageClass (source = current VersionId), update DB, mark `APPLIED`, commit, then delete the old S3 version. See diagram `06-apply-recommendation-sequence` (doc 03, W11).

## 7.7 Demo data caveat
Real uploads are never 30+ days old at demo time, so `scripts/seed_demo.py` uploads real files to real S3 and **backdates `created_at` and access-log rows in the database only**. S3's own `LastModified` stays real. The demo and README MUST disclose this.

---

# 8. Event-Driven Processing (AWS Lambda)

> **Amended:** AM-7: AWS Lambda is replaced by the durable `processing_jobs` queue and an in-process worker. The extraction rules, size gate, result mapping and idempotency below still apply; the callback, event delivery and AWS settings do not. Do not deploy a Lambda function, execution role, `lambda/build.sh` or S3 notification for CloudVault. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: no AWS credentials exist; the secrets are `JWT_SECRET`, `SIM_SIGNING_SECRET` and the database URL. Downloads use HMAC-signed links. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-1: application transactions are not held across storage calls; advisory locks, `PENDING` documents and `pending_op` drive concurrency and recovery; a version row exists only after its store write (AM-9). See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: no AWS test suite and no `moto`; every test runs against local PostgreSQL, including the simulated store. See [doc 15](docs/15-amendments.md).

| Level | Scope | Needs AWS? |
|---|---|---|
| Unit | Recommendation engine (injected clock), filename sanitization, file-type validation, key generation, authorization helpers, presign argument construction | No |
| Integration (local) | FastAPI `TestClient` + Postgres test DB + `moto` for S3: upload, download, delete, versioning, metadata, access logging | No (moto may differ from real S3, so it is not the final word) |
| AWS integration | `pytest -m aws` against a **dedicated throwaway test bucket** with versioning on: real versioning and delete markers, presigned URL fetch, `CopyObject` storage-class change, HEAD behavior for STANDARD, Lambda invoke + callback | **Yes** (real credentials; never in default CI) |
| Lambda | Handler with sample S3 event JSON: URL-encoded keys, versionId, oversized object, corrupt PDF | No |
| End-to-end | Manual checklist on the deployed site mirroring the demo script (Playwright optional, Tier 3) | Yes |

Default `pytest` run MUST pass with no AWS credentials. AWS tests are skipped unless `-m aws` is passed.

## 10.2 Test matrix

> **Amended:** AM-7: A1 to A3 test the simulated store and worker; S3 tests an expired signed link (403); L1 to L3 test the worker's extraction; C4 tests duplicate processing. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: no AWS account, cost control, IAM or teardown applies. Deployment is Vercel, Render and Neon; the environment variables are listed in doc 15 and in the repo-root `.env.example`. The IAM policies, AWS Budget steps and AWS/Lambda variables below are the original specification only: do not create them for CloudVault. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-4 and AM-7: no tracked `lib/` folder; `lambda/` and `infrastructure/` are not used; storage lives in `backend/app/storage/`, processing in `backend/app/processing/`. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: read "real S3" and "AWS Console" as the simulated store and the in-app Inspector; Lambda items as the worker. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: T4, T5, T12 and T16 to T19 are redefined for the simulation in `IMPLEMENTATION_PLAN.md`; T17 (Lambda wiring) becomes the processing worker. The AWS steps in T4, T17 and T25 (`-m aws`), and the teardown in T27, are the original specification and are not performed. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: state that CloudVault simulates S3; show the in-app Inspector instead of the AWS Console and the worker's processing status instead of Lambda logs. Before the demo: warm `/api/health`, run `reconcile` and `seed_demo`, and disclose the backdated seed data; no AWS Console is needed. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: answer as "real S3 does X; CloudVault simulates it by Y". See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: describe the project as a functional S3 simulation; do not claim real S3 or Lambda use. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: the AWS-specific risks (IAM, region, event wiring, AWS cost) no longer apply. See [doc 15](docs/15-amendments.md).

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

> **Amended:** AM-7: replaced by `docs/VERIFIED.md`, which checks only the S3 behaviors the simulation copies. See [doc 15](docs/15-amendments.md).

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

---

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
