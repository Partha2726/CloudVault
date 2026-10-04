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
