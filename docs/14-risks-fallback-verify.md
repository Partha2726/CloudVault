# 14. Risks, Fallback, Final Scope and VERIFY List

## 14.1 Project risks

> **Amended:** AM-7: the AWS-specific risks (IAM, region, event wiring, AWS cost) no longer apply. See [doc 15](15-amendments.md).

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

> **Amended:** AM-7: replaced by `docs/VERIFIED.md`, which checks only the S3 behaviors the simulation copies. See [doc 15](15-amendments.md).

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
