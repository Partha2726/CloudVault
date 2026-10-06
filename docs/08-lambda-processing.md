# 8. Event-Driven Processing (AWS Lambda)

> **Amended:** AM-7: AWS Lambda is replaced by the durable `processing_jobs` queue and an in-process worker. The extraction rules, size gate, result mapping and idempotency below still apply; the callback, event delivery and AWS settings do not. Do not deploy a Lambda function, execution role, `lambda/build.sh` or S3 notification for CloudVault. See [doc 15](15-amendments.md).

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

![Lambda processing sequence](diagrams/07-lambda-processing-sequence.png)

Source: [`diagrams/07-lambda-processing-sequence.mmd`](diagrams/07-lambda-processing-sequence.mmd)

## 8.5 Lambda environment variables

`BACKEND_WEBHOOK_URL`, `INTERNAL_WEBHOOK_SECRET`, `MAX_PROCESS_BYTES=5242880`.
