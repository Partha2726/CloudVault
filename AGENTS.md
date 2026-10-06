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
