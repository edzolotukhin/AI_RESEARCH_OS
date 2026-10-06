# UX-01B — Local acceptance evidence

## Baseline and design inventory

- Baseline branch: `acceptance/live-desk-research-01`; starting HEAD `a2dbdaebcfa2a8c7629dbb503958a30f59446fc4`; divergence `0/0`.
- Alembic began at the single head `023_ux01a_identity_membership`; no migration 024 was introduced.
- Approved implemented prototype sources and gaps are recorded in the architecture record. No conflicting tracked standalone prototype image was found.

## UX inventory and changes

- Login now uses the accepted navy/blue/card/form family while preserving UX-01A sessions and failure behavior.
- Projects remains the authenticated home. Cards show membership role, persisted method state, a bounded next action and a direct project action. The empty state explains creation/access semantics.
- Project Overview includes persistent Overview/method/Outputs/Activity navigation, role context, deterministic state and next actions. It explicitly preserves method isolation.
- VIEWER receives project and research visibility without add-method, edit-brief or access-management controls; server mutation remains denied.
- OWNER receives access management as a secondary project destination. Membership forms use existing form/button hierarchy and remain server-authorized.
- Outputs presents `Approved Version`, keeps source version under progressive disclosure, and provides a stable Activity anchor.
- Account and logout are consistently discoverable. Qualitative routes receive project shell context without changing transcript, coding, themes, review or report semantics.

## Automated evidence

- Focused shell/navigation/role, UX-01A identity, PF-01 workspace and PF-02 planning: 28 passed.
- Complete `tests/api/ui` browser-template/API group: 220 passed, 0 failures/errors.
- Focused UX-01A identity, OPS-01B upload/recovery, Qual prepared-transcript/audio and post-analysis security/privacy group: 22 passed, 0 failures/errors.
- Post-visual-correction UX-01B and Qual review/deliverable regression group: 18 passed, 0 failures/errors.
- UX-01B-specific checks cover shell context, deterministic next action, owner access placement, viewer control suppression plus server denial, project isolation and bounded architecture-vocabulary regression.
- No OpenAI, Tavily or AssemblyAI call is required or permitted.

## Visual comparison

Fresh graphical qualification used the official disposable Playwright `v1.62.1-noble` Chromium image with `restart=no`, two CPUs and 2 GB RAM. The container received only a task-owned directory containing synthetic rendered HTML/CSS plus a read-only local Playwright package; it had no repository, environment, Git, historical-volume or participant-data access. Synthetic memory-backed fixtures represented an owner project with Desk, Quantitative and Qualitative methods, researcher/viewer membership, sparse/blocked states, Desk evidence and review, Quant stages, Qual prepared transcripts/themes/review/approved version, Outputs and Activity.

Rendered desktop inspection at 1440×1000 covered Login, Projects, Project Overview, Desk Overview/Evidence/Review, Quant Overview/Analysis/Review, Qual workspace/Review/Approved Version, Outputs, Activity and Project Access. OWNER and VIEWER project views were separately rendered; RESEARCHER presentation was represented by the accepted Desk/Quant workspaces and membership state. Tablet-like inspection at 820×1000 covered Projects, Overview, Desk, Quant, Qual and Outputs/Activity. Automated layout measurement reported `bodyWidth == viewportWidth` for every narrow page inspected.

The source of truth was the accepted UI-01B/UI-02/UI-03, PF-01B/PF-03B and PRF-04 family implemented by `quantitative-product.css`, `desk-workbench.css`, `project-workspace.css` and routed method templates. Login, Projects, Overview, Desk, Quant, Outputs, Activity, role presentation and access management matched the persistent dark navigation, white content header, restrained status palette, compact card/form hierarchy and responsive fallbacks.

Initial inspection found one P1 defect: the Qual workspace remained visually raw, mixed product and implementation terminology, exposed technical record identifiers in the primary flow and used unstyled dense forms. The bounded correction applied the shared card/form hierarchy, Ukrainian product labels, explicit Approved Version wording, progressive disclosure for technical records and removal of a visible `authority` term from Outputs. Repeat desktop and 820 px rendering showed readable hierarchy, usable controls and no horizontal overflow. No P0 defects were found. No P1 defects remain. Minor English labels retained inside specialist Qual actions are classified P2 and deferred because they do not block pilot comprehension or expose authorization-sensitive behavior.

Temporary evidence was produced under `.ux01b-visual/` (representative names: `desktop-login.png`, `desktop-projects.png`, `desktop-overview-owner.png`, `desktop-desk-overview.png`, `desktop-quant-overview.png`, `desktop-qual-workspace-final.png`, `desktop-outputs-activity.png`, and corresponding `narrow-*` files). These task-owned screenshots and the disposable browser container are removed during final cleanup rather than committed.

The graphical gate is `PASS`: all mandatory surfaces were freshly rendered and inspected, role and empty/blocked states were coherent, the approved prototype family remained recognizable, and no unresolved P0/P1 defect remained. No live OpenAI, Tavily or AssemblyAI call occurred.

## Final canonical gate

The first post-visual run collected 3,220 tests and exposed one acceptance-tooling-only architecture failure: the temporary screenshot fixture under `tools/` imported `fastapi.testclient`, while the repository boundary permits FastAPI imports only under `api/`. The helper and all task-owned screenshots were removed during the required cleanup; the exact architecture test then passed 1/1. No product behavior was changed for that conflict.

The clean final canonical `python run_tests.py` gate passed: **3,220 tests run, 3,055 passed, 165 skipped, 0 failures, 0 errors**. Alembic remained at the single head `023_ux01a_identity_membership`; migration 024 remained absent.
