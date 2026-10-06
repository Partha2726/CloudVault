# 10. Testing

## 10.1 Strategy

> **Amended:** AM-7: no AWS test suite and no `moto`; every test runs against local PostgreSQL, including the simulated store. See [doc 15](15-amendments.md).

| Level | Scope | Needs AWS? |
|---|---|---|
| Unit | Recommendation engine (injected clock), filename sanitization, file-type validation, key generation, authorization helpers, presign argument construction | No |
| Integration (local) | FastAPI `TestClient` + Postgres test DB + `moto` for S3: upload, download, delete, versioning, metadata, access logging | No (moto may differ from real S3, so it is not the final word) |
| AWS integration | `pytest -m aws` against a **dedicated throwaway test bucket** with versioning on: real versioning and delete markers, presigned URL fetch, `CopyObject` storage-class change, HEAD behavior for STANDARD, Lambda invoke + callback | **Yes** (real credentials; never in default CI) |
| Lambda | Handler with sample S3 event JSON: URL-encoded keys, versionId, oversized object, corrupt PDF | No |
| End-to-end | Manual checklist on the deployed site mirroring the demo script (Playwright optional, Tier 3) | Yes |

Default `pytest` run MUST pass with no AWS credentials. AWS tests are skipped unless `-m aws` is passed.

## 10.2 Test matrix

> **Amended:** AM-7: A1 to A3 test the simulated store and worker; S3 tests an expired signed link (403); L1 to L3 test the worker's extraction; C4 tests duplicate processing. See [doc 15](15-amendments.md).

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
