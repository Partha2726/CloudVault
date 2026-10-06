# 6. Frontend and UI

## 6.1 Stack
React 18, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query (server state), Recharts, lucide-react. The JWT is kept in a small auth context backed by `sessionStorage`. A thin fetch wrapper (`src/api/client.ts`) attaches the token, parses the standard error shape, and redirects to login on 401. Never use `dangerouslySetInnerHTML`.

## 6.2 Screens (final list)

1. **Login/Register**
2. **Dashboard**
3. **Documents** (table + Trash tab)
4. **Document Details** (tabs: Overview, Versions, Access, S3 Inspector, Processing)
5. **Optimization**
6. **About** (`[AWS]` vs `[APP]` explainer, useful for the viva)

**Removed from the original idea:** Settings (nothing to set), standalone Version History and Processing Status pages (they are tabs).

## 6.3 Shared components
`AppShell`, `UploadDropzone`, `DocumentTable`, `StorageClassBadge`, `ProcessingBadge`, `ConfirmDialog`, `Toast`, `EmptyState`, `ErrorState`, `Skeleton`, `SourceBadge` (labels data as "S3" or "CloudVault").

## 6.4 State rules
- Every query has a skeleton (loading), an error state with a Retry button, and an empty state.
- Client-side validation (type, size) is a convenience only; the server is authoritative.
- After any mutation, invalidate the affected queries (`documents`, `document:{id}`, `dashboard`, `recommendations`).
- The 409 `NAME_EXISTS` response opens a dialog offering **Upload as new version** (calls the versions endpoint with `existing_document_id`).

## 6.5 Screen specifications

> **Amended:** AM-7: the Inspector badge reads "Live from simulated S3"; About explains the simulation with `[S3-SIM]`/`[APP]`/`[UI]` labels; Apply works. See [doc 15](15-amendments.md).

| Screen | Layout | Actions | Feedback | Loading / empty / error | Destructive confirmation |
|---|---|---|---|---|---|
| Login | Centered card | Login; switch to register | Inline field errors | Button spinner | n/a |
| Dashboard | 4 stat cards (documents, current storage, total incl. versions, accesses 30d); bar chart bytes by storage class; open-recommendations card; processing status counts | Click cards to navigate | n/a | Skeleton cards; empty: "Upload your first document" | n/a |
| Documents | Search bar, filters (type, class), dropzone above table. Columns: name, type, size, class badge, versions, processing badge, updated, row menu | Upload, download, details, delete. Trash tab: undelete, permanent delete | Toast "Uploaded v1" | Skeleton rows; empty state; 409 dialog | Delete: "Moves to trash (S3 delete marker)". Permanent: user types the filename to confirm |
| Document Details | Header (name, badges, actions) + tabs. **Versions:** table with Restore. **Access:** event list. **S3 Inspector:** key, VersionId, ETag, class, tags, metadata, badge "Live from S3". **Processing:** status, pages, words, Retry | Upload new version, restore, download, retry | Toasts | Per-tab skeletons; 502 shows "S3 unavailable, retry" | Restore dialog: "Creates a new version from vN" |
| Optimization | Banner: "CloudVault's heuristic, not AWS Intelligent-Tiering". Table: file, current to recommended, reason, signals, estimate (only if pricing present) | Refresh, Apply, Dismiss | Toast "Storage class changed to STANDARD_IA" | Empty: "No recommendations; files are new or already optimal" | Apply dialog: "Copies the object to the new class and removes the old version" |
| About | Static: architecture diagram and the S3-vs-app table | none | n/a | n/a | n/a |

## 6.6 Visual style
Neutral slate palette, one accent colour, rounded cards, generous whitespace, responsive down to phone width. **Do not** imitate the orange AWS Console look; it should read as a polished student cloud project.

## 6.7 Wording rules (honesty)
- Any text about recommendations MUST say "CloudVault's heuristic".
- Access counts MUST be labelled "recorded by CloudVault".
- Estimates, if shown, MUST state what they exclude (retrieval, requests, minimum duration, transfer).
- Never write that "AWS calculated" a recommendation.
