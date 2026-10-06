# 1. Overview and Scope

> **Amended:** AM-7: CloudVault is a functional simulation of Amazon S3 backed by PostgreSQL; no real AWS account, bucket, Lambda or IAM is used. Read `[AWS]` as `[S3-SIM]`. See [doc 15](15-amendments.md).

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

> **Amended:** AM-7: demo evidence comes from the in-app S3 Inspector and the simulated store, not the AWS Console. Apply really changes the simulated storage class. See [doc 15](15-amendments.md).

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
