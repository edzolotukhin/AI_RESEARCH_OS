# UX-01B — Unified product shell

## Approved visual sources

UX-01B does not introduce a new visual system. The authoritative implemented prototype family is the accepted history and current files from `UI-01B`, `UI-02`, `UI-03`, `PF-01B`, `PF-03B`, and `PRF-04`:

- `api/static/quantitative-product.css`: dark persistent navigation, white top bar, restrained blue/green/orange status palette, compact panels, stage flow, responsive breakpoints; its comments identify the accepted product-fidelity and acceptance-polish layers.
- `api/static/desk-workbench.css`: matching shell, status, panel, empty, notice, report and narrow-layout patterns for Desk Research.
- `api/static/project-workspace.css` and `api/templates/projects/*`: accepted Projects, project cards, Project Overview, planning and Outputs patterns.
- `api/templates/quantitative/*`, `api/templates/research/workbench_*`, and their accepted browser tests: method workspace composition, status hierarchy, progressive details and outputs.

No tracked standalone screenshot or Figma artifact defines a different global shell. Login, role-specific states, access management and some empty/error/privacy states therefore extend the nearest accepted shell, card, form, notice and status patterns conservatively.

## Current-to-approved mapping

| Product surface | Approved pattern | UX-01B direction |
| --- | --- | --- |
| Login | project form card + navy/blue shell palette | branded focused sign-in card; authentication unchanged |
| Projects | PF-01B project list/cards | role and deterministic next action added |
| Project Overview | PF-01B context/design/method cards | persistent project navigation, role-aware controls, independent-method explanation |
| Desk Research | PF-03B workbench shell | retain workbench; link from project context; hide ARK internals |
| Quantitative Research | UI-01B/02/03 shell and stage flow | retain five routed screens and status treatment |
| In-Depth Interviews | project shell + accepted Qual workflow | provide project shell context; preserve transcript/coding/theme authority |
| Review / Approved Version | existing method review panels | researcher wording; source details remain progressive |
| Outputs / Activity | PRF-04 project method cards and timeline | first-class project navigation and activity anchor |
| Project access | project form/card patterns | secondary owner-only surface |

## Product model and state

The researcher model is `Projects → Project → Research Method → Work → Analysis → Review → Outputs`. Project Overview presents navigation and persisted lifecycle state only. It does not synthesize conclusions across methods.

Status and next-action presentation are derived from existing project, method, run, review and deliverable records. No frontend completion truth is stored. Project cards use the first non-complete method action as a bounded next action; completed projects point to outputs. Viewer/Researcher/Owner presentation derives from UX-01A membership and server authorization remains authoritative.

## Shell and navigation

The authenticated shell contains product identity, Projects, project context, configured methods, Outputs, Activity, account and logout. Owner-only access management is secondary. Deep method pages retain their accepted method shells and project return links; no frontend framework or rendering strategy changes.

## Terminology and trust

Normal product surfaces use research concepts rather than implementation concepts. Internal authority, adapter, orchestration, materialization and version-envelope terminology remains limited to code, API, logs and technical diagnostics. `Approved Revision` is presented as `Approved Version`; source identifiers are progressively disclosed where needed for provenance.

AI suggestions remain distinct from human review and approved results. Provenance remains visible in method details and source-detail disclosures, without placing internal IDs in routine project summaries.

## Security, privacy and authority boundary

Templates are projections over accepted domain state. UX-01B does not modify Desk, ARK, Quant, Qual, Review, deliverable or Activity authority. Server-side UX-01A membership enforcement, CSRF/origin checks, nested-resource protection and OPS-01B upload/provider/privacy controls remain unchanged. Viewer controls are removed from the main project surface in addition to server-side denial.

## Deferred

UX-01C operations visibility, UX-01D onboarding/help/feedback, notifications, collaboration, new methods, cross-method synthesis, mobile-specific product design and design-system/framework replacement remain deferred.
