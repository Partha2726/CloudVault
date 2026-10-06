---
version: 1
slug: "frontend-src-pages-dashboardpage-tsx"
primary_target: "frontend/src/pages/DashboardPage.tsx"
related_targets: ["frontend/src/components/AppShell.tsx"]
---

# Dashboard surface brief

Scope: CloudVault dashboard (`/`), Operate mode. Audience: the owner managing their own documents, and a grader watching a 9-minute demo on a classroom projector. Job: see at a glance how much is stored, in which simulated storage class, what was accessed, what is processing, and whether CloudVault's heuristic has recommendations. Data: `GET /api/dashboard/summary` only (doc 05.5). Constraints: doc 06.5 contents (4 figures, bytes-by-class bar chart, open recommendations, processing counts; skeleton, empty, error states); wording rules doc 06.7; never imply real AWS; storage class names stay STANDARD / STANDARD_IA / GLACIER_IR.

## Direction contract

THESIS: The dashboard is a finding aid for the vault: a summary of holdings and a container list, not a wall of metric cards. It refuses the four-rounded-cards-and-a-chart console.

OWN-WORLD: Slate archive header (#2E3A40) over a cool box-board ground; white record panels with hairline rules and square 2px corners; Public Sans set like institutional record labels, uppercase tracked captions, tabular figures; data in slate, box-board blue-grey and pale stack grey; archival red only for failures and alerts; archival green for completed processing.

STORY: The visitor reads total holdings first, sees where bytes sit by class, notices processing state and open recommendations, and knows every figure is recorded by CloudVault from a simulated store.

FIRST VIEWPORT: Slate header with product name, nav and account. Page heading "Dashboard" (the spec screen name) with one line naming the holdings in the simulated store. A ruled summary strip of four figures (documents, current storage, total including versions, downloads in 30 days). Below, left two-thirds: the container list, storage classes as rows with square-ended bars on one shared byte scale and right-aligned figures. Right third: processing counts and open recommendations with the heuristic disclaimer.

FORM: Finding Aid, position 1 on the ordered list (IMPECCABLE'S PICK chosen by the user), seed key b1dae905.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
