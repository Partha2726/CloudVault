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
