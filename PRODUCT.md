# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React 18, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query, Recharts, lucide-react (frontend); Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, slowapi, bcrypt, PyJWT, pypdf (backend); PostgreSQL 15+ (Neon in production) for application data and the simulated S3 store. No AWS account. Locked by `AGENTS.md`, not a greenfield choice.

## Users

Sole author (owner) as the only real end user — uploads, organizes, and manages their own documents. Secondary audience: a grader/professor evaluating the university assignment ("AWS Service Simulation & Enhancement") via live demo and viva. Not built for general public end users.

## Product Purpose

CloudVault is a functional simulation of Amazon S3. It reproduces selected S3 concepts and semantics locally using PostgreSQL-backed simulated object storage; a real AWS account is not required. It is a document manager where every file lives in a private, versioned simulated S3 bucket, with FastAPI + PostgreSQL holding application state (ownership, display names, version numbers, access history, recommendations). Exists to satisfy a 10-mark university assignment while being a defensible resume project. Success = all rubric categories (AWS understanding, core functionality, enhancement, UI/UX, deployment/GitHub, demonstration; the brief asks to *simulate* the chosen service) demonstrably met and explainable in a scripted 9-minute demo + viva.

## Positioning

A faithful, working simulation of S3 behavior (versioning, delete markers, storage classes, signed time-limited download links, lifecycle rules, object-created processing), each behavior modeled on and checked against the AWS documentation — not a static mock-up and not a fake AWS console. Differentiator is the *Intelligent Storage Optimization* engine: a deterministic, explainable, CloudVault-owned heuristic over application access logs that recommends storage-class changes. Explicitly not AWS Intelligent-Tiering, and the UI must say so.

## Operating Context

Every feature is labeled `[S3-SIM]` (CloudVault's simulation of a real S3 behavior), `[APP]` (CloudVault logic S3 does not provide), or `[UI]` (interface representation only) — an About page must carry these labels for the demo. Core workflows: register/login (JWT), upload through the backend (≤10 MiB, no multipart), signed-link download with access logging, soft delete + trash + undelete, version history with restore, S3 Inspector (simulated metadata/tags/storage class), dashboard with storage usage by class, storage recommendations (refresh/apply/dismiss, Apply changes the simulated class), background document processing with visible status. Deployment: Vercel (frontend), Render (backend + worker), Neon (DB + simulated store).

## Capabilities and Constraints

- Object key scheme: `documents/{owner_uuid}/{document_uuid}`; filename lives only in the DB; one key per document; simulated S3 versions = document versions.
- Simulated bucket always private; objects only reachable via 120 s version-bound HMAC-signed links to the app's own route.
- Uploads go through the backend, max 10 MiB, parsed in memory, never written to disk.
- Soft delete = simulated delete marker; permanent delete removes every version and marker by version id.
- Access history is application-recorded (`access_logs`); S3 has no native "last accessed" claim.
- Auth is email + password with JWT bearer only — no OAuth, roles, or sharing.
- Out of scope (do not build): public bucket or direct browser-to-S3 uploads, multipart upload, Object Lock, SSE-KMS, real Intelligent-Tiering integration, Glacier Flexible Retrieval/Deep Archive, sharing links, roles/admin, OAuth, email verification, password reset, CloudFront, Terraform, Kubernetes, SQS/SNS, microservices, CloudWatch dashboards, S3 access logs, CloudTrail data events, replication, AI/ML/embeddings/OCR/virus scanning/Bedrock/OpenAI.
- Secrets never committed; only `.env.example` with placeholders.
- Full spec lives at the repo root (`AGENTS.md` ground rules, `CLOUDVAULT_FULL_SPEC.md`, `docs/01`–`docs/14`, `docs/diagrams/`); treat as binding spec, not inspiration. Owner-approved changes in `docs/15-amendments.md` override docs 01–14. Working checklist: `IMPLEMENTATION_PLAN.md`.
- Never imply real AWS calls. UI, README and demo say "simulated S3" (AM-7).

## Brand Commitments

Name is "CloudVault." No logo, tagline, palette, or typography locked yet.

## Evidence on Hand

No real documents, testimonials, or production data yet — implementation is in progress (see `IMPLEMENTATION_PLAN.md`). Demo will use seeded/backdated data (Tier 2 "demo seed script"), not real customer evidence. Do not fabricate testimonials, pricing, or customer logos.

## Product Principles

1. Faithful simulation — every simulated S3 behavior is checked against the AWS documentation and recorded in `docs/VERIFIED.md`.
2. Never blur `[S3-SIM]` vs `[APP]` vs `[UI]` — label honestly everywhere, especially the Storage Optimization engine; never imply real AWS calls.
3. Security defaults are non-negotiable: private simulated bucket, no secrets to the browser, signed links only, no user filenames as keys/paths.
4. Build exactly to the locked spec in `docs/`; stop and ask rather than inventing architecture, endpoints, or thresholds.
5. Don't claim a feature (README, UI, demo) until it's implemented and tested.

## Accessibility & Inclusion

No formal accessibility standard required for this assignment; no product-specific accessibility requirement established beyond ordinary good practice.
