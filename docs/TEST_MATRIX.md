# Test matrix (T25 traceability)

Every test ID of doc 10.2 and every per-task test of doc 12 / `IMPLEMENTATION_PLAN.md`, mapped to the automated test that covers it. Paths are under `backend/tests/`. Status is the result of the full run on 2026-10-06 after AM-9 (570 passed, 0 failed). Amendments are in `docs/15-amendments.md`.

## Doc 10.2 matrix

| ID | Behavior | Test | Status | Amended? |
|---|---|---|---|---|
| U1 | R3 positive (120 days, 18 MiB, 1 access/90 d, idle 40 d) | `unit/test_recommendation_engine.py::test_u1_r3_positive` | pass | no (AM-4 keeps the 18 MiB input) |
| U2 | Age boundary 29/30 days | `unit/test_recommendation_engine.py::test_u2_boundary_age` | pass | no |
| U3 | Small file, `SMALL_OBJECT` | `::test_u3_small_file` | pass | no |
| U4 | Promote to STANDARD (R1) | `::test_u4_promote` | pass | no |
| U5 | Cooldown | `::test_u5_cooldown` | pass | no |
| U6 | Very cold to GLACIER_IR (R2) | `::test_u6_very_cold` | pass | no |
| U7 | Unsupported class | `::test_u7_unsupported_class` | pass | no |
| U8 | Recently accessed, `ACTIVE_USE` | `::test_u8_recently_accessed` | pass | no |
| V1-V7, V9, V10 | Filename sanitization, empty file, magic bytes, extension allowlist | `unit/test_validation.py::test_v1_*` to `test_v10_*` | pass | no |
| V8 | 10485760 / 10485761 bytes | `unit/test_validation.py::test_v8_size_boundary_stream`, `integration/test_documents.py::test_v8_size_boundary_over_http` | pass | no |
| I1 | Upload then list (v1; filename never in the key) | `integration/test_documents.py::test_i1_upload_then_list` | pass | AM-7 (simulated store) |
| I2 | Same name, same content: 200 duplicate | `::test_i2_same_name_same_content_is_duplicate` | pass | no |
| I3 | Same name, new content: 409 `NAME_EXISTS` | `::test_i3_same_name_new_content_is_name_exists` | pass | no |
| I4 | New version; v1 kept | `integration/test_versions.py::test_i4_new_version_becomes_current_and_v1_is_kept` | pass | AM-1 |
| I5 | Restore v1 as v3 | `::test_i5_restore_creates_new_version_with_old_content` | pass | AM-2 (own job) |
| I6 | Soft delete adds marker | `integration/test_deletion.py::test_i6_soft_delete_hides_document_and_adds_marker` | pass | AM-1 |
| I7 | Undelete removes marker | `::test_i7_undelete_removes_marker_and_restores_current_version` | pass | AM-1 |
| I8 | Permanent delete removes everything | `::test_i8_permanent_delete_removes_everything` | pass | AM-4 (repeat semantics) |
| I9 | Download logs one access | `integration/test_download.py::test_i9_download_logs_one_access` | pass | AM-4 (no storage call) |
| I10 | Apply changes the simulated class; old version gone | `integration/test_recommendations.py::test_i10_apply_changes_simulated_class` | pass | AM-7 (AM-3 withdrawn) |
| I11 | Stale after new accesses: 409 | `::test_i11_stale_after_new_accesses` | pass | no |
| S1 | Other user's document: 404 on every route, same body as a missing id | `integration/test_security.py::test_s1_*` (6 tests) | pass | no |
| S2 | No token: 401 on every protected route (from the OpenAPI schema) | `integration/test_security.py::test_s2_*`, `integration/test_auth.py::test_s2_missing_or_malformed_token` | pass | no |
| S3 | Expired link denied, cannot be replayed or extended | `integration/test_security.py::test_s3_expired_link_is_denied_and_cannot_be_replayed`, `integration/test_download.py::test_expired_link_is_403` | pass | AM-7 (signed link, 403) |
| S4 | Internal endpoint without token | `integration/test_security.py::test_s4_no_internal_processing_endpoint` | pass | AM-7/AM-8: endpoint removed; test asserts it does not exist |
| S5 | Login brute force: 6th attempt 429 | `integration/test_auth.py::test_s5_login_brute_force_rate_limited`, `integration/test_security.py::test_s5_*` (incl. register limit) | pass | AM-8 (register limit added) |
| C1 | Concurrent version uploads: n and n+1 | `integration/test_version_concurrency.py::test_c1_competing_uploads_serialize_into_n_and_n_plus_1` | pass | AM-1 (advisory lock) |
| C2 | Concurrent deletes: both 204, one marker | `integration/test_deletion.py::test_c2_competing_deletes_create_exactly_one_marker` | pass | AM-1 |
| C3 | Same-name concurrent create: one 201, one 409, no orphan | `integration/test_document_concurrency.py::test_c3_same_name_concurrent_create` | pass | no |
| C4 | Duplicate processing is a no-op | `integration/test_worker.py::test_c4_duplicate_delivery_cannot_overwrite_the_result` | pass | AM-7 (duplicate delivery replaces duplicate Lambda event) |
| A1 | Versioning: put, put, delete gives two versions and a marker | `integration/test_storage.py::test_put_put_delete_gives_two_versions_and_a_marker` | pass | AM-7 (simulated store, no AWS) |
| A2 | HEAD omits the class for STANDARD | `integration/test_storage.py::test_head_omits_storage_class_for_standard` | pass | AM-7 |
| A3 | Upload to processed result | `integration/test_worker.py::test_a3_upload_to_processed_result_over_the_api` (T25), `::test_processes_a_pending_job`, `::test_worker_runs_inside_the_app` | pass | AM-7 (job row triggers the worker; no S3 event, no Lambda callback) |
| A4 | Storage error: 502, nothing visible | `integration/test_documents.py::test_a4_storage_error_marks_document_failed` | pass | AM-1/AM-7/AM-9 (document marked `FAILED`, no version row; injected store error replaces moto) |
| L1 | 6 MB text: `SKIPPED/TOO_LARGE` | `unit/test_extract.py::test_l1_oversized_object_is_skipped_without_parsing`, `integration/test_worker.py::test_oversized_object_is_skipped_without_reading` | pass | AM-7 (worker) |
| L2 | Corrupt PDF: `FAILED/CORRUPT` | `unit/test_extract.py::test_l2_corrupt_pdf_fails_deterministically` | pass | AM-7 |
| L3 | URL-encoded key decoded | `integration/test_download.py::test_l3_encoded_characters_in_names_never_reach_the_key` (T25), `integration/test_security.py::test_signed_route_path_manipulation` | pass | AM-7: no S3 event keys exist; keys are generated. Test checks `+`/`%20` names never reach the key and survive the signed link |

## Per-task tests (doc 12, `IMPLEMENTATION_PLAN.md`)

| Task | Required | Tests |
|---|---|---|
| T3 schema | constraints; models match migration; downgrade/upgrade; AM-9 NOT NULL `s3_version_id` | `integration/test_schema.py`, `integration/test_sim_store_schema.py`, `integration/test_version_invariant.py` |
| T5 store | A1, A2, VERIFIED behaviors | `integration/test_storage.py` |
| T7 auth | S2, S5, duplicate email, AM-5 72-byte rule | `integration/test_auth.py` |
| T8 upload | I1-I3, C3, A4, V8 HTTP, pool not exhausted | `integration/test_documents.py`, `integration/test_document_concurrency.py` |
| T9 download | I9, S3, tampered link, other version id | `integration/test_download.py` |
| T10 delete | I6-I8, C2, every failure point, roll-forward | `integration/test_deletion.py` |
| T11 versions | I4, I5, C1, restore job rules (AM-2) | `integration/test_versions.py`, `integration/test_version_concurrency.py` |
| T12 Inspector | shape, STANDARD class, 404/410, owner scoping | `integration/test_s3_inspector.py` |
| T13 engine | U1-U8 plus boundaries | `unit/test_recommendation_engine.py` |
| T14 recommendations | I10, I11, Apply recovery states A-D | `integration/test_recommendations.py`, `integration/test_recommendation_concurrency.py` |
| T15 dashboard | aggregates, owner scoping | `integration/test_dashboard.py` |
| T16 extraction | L1, L2, encrypted PDF, docx, image | `unit/test_extract.py` |
| T17 worker | lease reclaim, C4, deliveries cap, two workers, restart | `integration/test_worker.py` |
| T18 processing API | status, stalled, retry, 409/410 | `integration/test_processing_api.py` |
| T19 scripts | reconcile, lifecycle, seed | `integration/test_scripts.py` |
| T24 security | S1-S5, CORS, headers, body caps, signed-route abuse, logs | `integration/test_security.py`, `unit/test_config.py`, `unit/test_signing.py` |

## Cross-phase invariants

| Invariant | Covered by |
|---|---|
| Owner isolation | `test_security.py::test_s1_*`, owner tests in every integration file |
| Upload to processing | `test_worker.py::test_a3_upload_to_processed_result_over_the_api` |
| Version creation, restore | `test_versions.py`, `test_version_concurrency.py` |
| Version row only after its store write (AM-9) | `test_version_invariant.py::test_schema_column_is_not_null`, `::test_no_version_row_exists_during_any_store_write`, `::test_apply_keeps_the_row_and_swaps_its_store_id` |
| Restore: new `PENDING` job, worker completes it (AM-2) | `test_version_invariant.py::test_restore_gets_a_new_pending_job_that_the_worker_processes` |
| Delete, undelete, permanent delete | `test_deletion.py` (incl. interrupted operations) |
| Recommendation to Apply, Apply recovery | `test_recommendations.py::test_i10_*`, `test_state_a_*` to `test_state_d_*` |
| Worker recovery | `test_worker.py::test_crashed_delivery_is_reclaimed_after_the_lease`, `::test_restart_loses_no_job` |
| Reconciliation, lifecycle | `test_scripts.py` |
| Signed downloads | `test_download.py`, `test_security.py` |
| S3 Inspector | `test_s3_inspector.py` |
| Dashboard aggregation | `test_dashboard.py` |
| Frontend/backend integration | Browser runs (Playwright, not in the repo; doc 10.1 makes them optional Tier 3): Documents (22 checks), Details (23), Optimization/About (16), each at desktop and 390 px. Doc 10.3 flows 1-6 are covered by these runs; flow 5 reads the class in the S3 Inspector instead of the AWS Console (AM-7) |

## Not automated

- Doc 10.1 "AWS integration" (`-m aws`) and the Lambda handler suite: withdrawn by AM-7. No AWS code exists to test.
- Doc 10.3 end-to-end flows are browser runs, not committed tests (doc 10.1: Playwright optional).
