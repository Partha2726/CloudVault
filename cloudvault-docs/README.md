# CloudVault: Implementation Documentation

> **CloudVault** is a document manager built on **real Amazon S3** (private, versioned bucket) with a FastAPI backend, PostgreSQL, an S3-event-driven Lambda, and a custom rule-based **Intelligent Storage Optimization** engine.
> It is a university assignment ("AWS Service Simulation & Enhancement", 10 marks) designed to also be a defensible resume project.

This documentation set is an **implementation-ready specification** for an AI coding agent or a human developer. Start with [`AGENTS.md`](AGENTS.md).

## Labels used everywhere

| Label | Meaning |
|---|---|
| `[AWS]` | A real Amazon S3/AWS capability |
| `[APP]` | CloudVault application logic built on S3 (never described as AWS behavior) |
| `[UI]` | A UI representation/simulation |
| `VERIFY` | Must be checked against official AWS docs before implementing |

## Reading order

| # | Document | Contents |
|---|---|---|
| 1 | [01-overview-and-scope.md](docs/01-overview-and-scope.md) | Executive summary, rubric mapping, scope tiers, exclusions |
| 2 | [02-s3-design.md](docs/02-s3-design.md) | S3 capability matrix, bucket/object/key design, lifecycle, IAM-relevant S3 behavior |
| 3 | [03-architecture-and-workflows.md](docs/03-architecture-and-workflows.md) | Logical + deployment diagrams, all 16 workflows |
| 4 | [04-database.md](docs/04-database.md) | ER diagram, every table, constraints, state machines |
| 5 | [05-api-contract.md](docs/05-api-contract.md) | Every REST endpoint, error codes, validation rules |
| 6 | [06-frontend-and-ui.md](docs/06-frontend-and-ui.md) | Screens, components, states, UX rules |
| 7 | [07-recommendation-engine.md](docs/07-recommendation-engine.md) | Heuristic thresholds, pseudocode, apply flow |
| 8 | [08-lambda-processing.md](docs/08-lambda-processing.md) | Event design, idempotency, retries, limits |
| 9 | [09-security-and-consistency.md](docs/09-security-and-consistency.md) | Security model, failure matrix, S3/DB consistency |
| 10 | [10-testing.md](docs/10-testing.md) | Strategy and full test matrix |
| 11 | [11-deployment-cost-iam-env.md](docs/11-deployment-cost-iam-env.md) | Deployment, cost control, IAM policies, `.env` |
| 12 | [12-repo-and-build-order.md](docs/12-repo-and-build-order.md) | Repo layout, phases, dependency graph, **task-by-task build order**, definition of done |
| 13 | [13-demo-viva-resume.md](docs/13-demo-viva-resume.md) | Demo script, viva Q&A, resume bullets |
| 14 | [14-risks-fallback-verify.md](docs/14-risks-fallback-verify.md) | Risks, fallback tiers, final scope, **VERIFY list** |

A single concatenated copy of everything is in [`CLOUDVAULT_FULL_SPEC.md`](CLOUDVAULT_FULL_SPEC.md) for agents that prefer one file.

## Diagrams

All diagrams exist as Mermaid source (`.mmd`, easiest for agents to read), PNG and SVG in [`docs/diagrams/`](docs/diagrams/).

| Diagram | Files |
|---|---|
| Logical architecture | `01-logical-architecture` |
| Deployment architecture | `02-deployment-architecture` |
| Upload sequence | `03-upload-sequence` |
| Versioning and delete semantics | `04-versioning-and-delete` |
| Recommendation decision flow | `05-recommendation-flow` |
| Apply-recommendation sequence | `06-apply-recommendation-sequence` |
| Lambda processing sequence | `07-lambda-processing-sequence` |
| Phase dependency graph | `08-dependency-graph` |
| ER diagram | `09-er-diagram` |
| State machines | `10-state-machines` |
| IAM and trust boundaries | `11-iam-trust-boundaries` |

To re-render after editing a `.mmd` file:

```bash
npm i -g @mermaid-js/mermaid-cli
mmdc -i docs/diagrams/01-logical-architecture.mmd -o docs/diagrams/01-logical-architecture.png -b white -s 2
```

## Key locked decisions (summary)

- Bucket is **private** with Block Public Access on. Browser never talks to S3 except through a **120 s, version-bound presigned GET URL**.
- **Uploads are proxied through the backend** (max 10 MiB, single `PutObject`). No multipart, no CORS on the bucket.
- S3 key is **`documents/{owner_uuid}/{document_uuid}`**. The filename lives only in the database.
- One S3 key per document. **S3 versions = document versions.**
- Soft delete creates an **S3 delete marker**. Permanent delete removes **every version and marker** by VersionId.
- Access history is **application-recorded** (`access_logs`). S3 does not provide an application-friendly last-accessed time, and we never claim it does.
- Recommendations are **CloudVault's own heuristic**, not AWS Intelligent-Tiering. No fake savings percentages.
- **Lambda is included** (S3 `ObjectCreated:Put` to Lambda to backend callback) with idempotent processing.
- Auth: email and password with JWT (Bearer header). No OAuth, roles or sharing.

## Status of verification

This specification was written without live access to AWS documentation. All AWS-specific claims that are not core, well-established S3 behavior are marked `VERIFY`. Resolve every `VERIFY` item (list in `docs/14-risks-fallback-verify.md`) before depending on it.
