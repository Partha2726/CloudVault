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
