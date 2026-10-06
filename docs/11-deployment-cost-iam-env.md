# 11. Deployment, Cost Control, IAM and Environment

> **Amended:** AM-7: no AWS account, cost control, IAM or teardown applies. Deployment is Vercel, Render and Neon; the environment variables are listed in doc 15 and in the repo-root `.env.example`. The IAM policies, AWS Budget steps and AWS/Lambda variables below are the original specification only: do not create them for CloudVault. See [doc 15](15-amendments.md).

## 11.1 Deployment architecture decision

| Option | Verdict |
|---|---|
| **Vercel (frontend)** | **Chosen.** Free static hosting, HTTPS, env vars, GitHub deploys (check Hobby plan terms; `VERIFY`) |
| **Render (backend)** | **Chosen.** Simple FastAPI deploy from GitHub, HTTPS, env vars. The free tier spins down when idle, causing a cold start of tens of seconds (`VERIFY`). Mitigation: warm it before the demo |
| **Neon (Postgres)** | **Chosen.** Free managed Postgres. Use `sslmode=require` and `pool_pre_ping=True` because compute can auto-suspend (`VERIFY`) |
| Render's own Postgres | Rejected: the free database may expire after a limited period (`VERIFY`) |
| Railway | Rejected: free usage is trial-based (`VERIFY`) |
| AWS-hosted backend (EC2, App Runner, ECS) | Rejected: higher cost and complexity, cost surprises |
| GitHub Pages | Works for the frontend only; no advantage over Vercel here |

**Process**
- Backend start command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` (do not rely on a paid pre-deploy feature; `VERIFY`).
- Frontend build variable: `VITE_API_BASE_URL`.
- Warm-up: call `/api/health` about 5 minutes before the demo.
- Fallback: demo locally against real S3 and show the deployed URL separately.

## 11.2 AWS cost control

Confirm all of the following against current AWS pricing and the account's free-tier/credit program (`VERIFY`). Do not claim anything is free without checking.

**What can incur charges:** S3 storage (GB-month), PUT/COPY/LIST requests, GET requests, data transfer out; storage-class changes use COPY requests; IA and GIR classes have per-GB retrieval charges, minimum storage duration and minimum billable object size; **every noncurrent version is billed until expired** (mitigated by lifecycle rule and by deleting the old version after a tier change); Lambda requests and duration; CloudWatch Logs ingestion/storage.

**Avoid:** KMS, CloudTrail data events, Storage Lens advanced, Intelligent-Tiering monitoring fees.

**Unexpected-cost risks:** forgotten versions, huge uploads (capped at 10 MiB), loops that call COPY, log groups without retention.

**Controls:** AWS Budget with a very low email alert threshold (`VERIFY` pricing); no root account for daily work, MFA on; 10 MiB cap and rate limits; log retention 7 days.

**Teardown after the demo/semester:**
1. Empty the bucket **including all versions and delete markers**, then delete the bucket.
2. Delete the Lambda function and its log group.
3. Delete the backend IAM user + access keys and the Lambda role.
4. Remove the Budget if no longer needed.

## 11.3 IAM design

![IAM and trust boundaries](diagrams/11-iam-trust-boundaries.png)

### Backend IAM user `cloudvault-backend` (runtime)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow",
     "Action": ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketVersioning"],
     "Resource": "arn:aws:s3:::BUCKET"},
    {"Effect": "Allow",
     "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject",
                "s3:DeleteObjectVersion", "s3:PutObjectTagging", "s3:GetObjectTagging"],
     "Resource": "arn:aws:s3:::BUCKET/documents/*"},
    {"Effect": "Allow",
     "Action": "lambda:InvokeFunction",
     "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:cloudvault-processor"}
  ]
}
```
`s3:ListBucket` is also needed for the startup `HeadBucket` check (`VERIFY` exact permission for HeadBucket). Presigned URLs only work with the permissions of the signer, so `s3:GetObjectVersion` is required for version-bound URLs. `CopyObject` additionally needs read permission on the source (covered by `GetObject`/`GetObjectVersion`) and `PutObject` on the destination; add `s3:GetObjectVersionTagging` only if copying tags requires it (`VERIFY`).

### Lambda execution role `cloudvault-processor-role`
- CloudWatch Logs: the AWS managed basic execution policy, or an equivalent inline policy scoped to its own log group.
- `s3:GetObject`, `s3:GetObjectVersion` on `arn:aws:s3:::BUCKET/documents/*`.
- Resource-based policy on the function allowing `s3.amazonaws.com` to invoke it (`SourceArn` = bucket, `SourceAccount` = account id).

### Human/developer
- No root use. Use an IAM user or Identity Center with MFA.
- Setup scripts need permission to create the bucket, configure it, create IAM roles/users and create the Lambda function.
- `AdministratorAccess` is acceptable only transiently for first-time setup (document this in `infrastructure/README.md`). It is **never** given to the application.

## 11.4 Environment configuration

### `.env.example` (committed, placeholders only)
```dotenv
# ---- Backend (local development) ----
APP_ENV=development
DATABASE_URL=postgresql+psycopg://cloudvault:cloudvault@localhost:5432/cloudvault
JWT_SECRET=change-me-long-random
JWT_EXPIRE_MINUTES=60
FRONTEND_ORIGIN=http://localhost:5173
AWS_REGION=ap-south-1
S3_BUCKET=cloudvault-dev-xxxxxx
AWS_PROFILE=cloudvault-dev          # or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
LAMBDA_FUNCTION_NAME=cloudvault-processor
INTERNAL_WEBHOOK_SECRET=change-me
MAX_UPLOAD_BYTES=10485760
PRESIGN_EXPIRY_SECONDS=120
REC_MIN_SIZE=131072
REC_MIN_AGE_IA_DAYS=30
REC_GIR_MIN_AGE_DAYS=90
REC_IA_MAX_ACCESSES_90D=2
REC_PROMOTE_ACCESSES_30D=3
REC_COOLDOWN_DAYS=30
PRICING_FILE=./pricing.json         # optional

# ---- Frontend ----
VITE_API_BASE_URL=http://localhost:8000

# ---- Lambda (set in function configuration, not in Git) ----
BACKEND_WEBHOOK_URL=https://<render-app>/api/internal/processing-results
INTERNAL_WEBHOOK_SECRET=change-me
MAX_PROCESS_BYTES=5242880
```

### Production differences
- `APP_ENV=production`.
- `DATABASE_URL` from Neon with `sslmode=require`.
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` of the backend IAM user set in Render; **no** `AWS_PROFILE`.
- `FRONTEND_ORIGIN` = the Vercel URL.
- Strong random `JWT_SECRET` and `INTERNAL_WEBHOOK_SECRET` (different values).
