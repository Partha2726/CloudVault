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
