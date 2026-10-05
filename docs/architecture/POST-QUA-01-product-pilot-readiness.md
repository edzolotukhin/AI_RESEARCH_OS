# POST-QUA-01 — Product and pilot readiness

Status: canonical audit checkpoint after remote acceptance of Desk, Quantitative,
and Qualitative IDI. Baseline: `acceptance/live-desk-research-01` at
`2a1eb95737e0fce6a6399753026a54d5cad14946`, upstream divergence `0/0`,
Alembic head `022_qua04_report_deliverables`. Exact GitHub Actions run
`37294185353` completed successfully.

## Executive verdict

AI Research OS is **not ready today for use by 2–4 real colleagues with real
research data**. The three method architectures are accepted and technically
substantial, but the repository is still an internal/developer-operated product.
The blocking gap is the pilot envelope around those methods: individual browser
authentication, project membership and attribution, production-safe deployment,
backups, and a coherent guided UI.

This is not a recommendation for enterprise infrastructure. A controlled pilot
becomes reasonable after two bounded phases:

1. **UX-01 — Pilot Product Experience**: one coherent shell and guided workflow,
   individual login, minimal roles/membership, safe errors, onboarding and feedback.
2. **OPS-01 — Pilot Production Readiness**: private HTTPS deployment, secrets,
   persistent storage, backup/restore, operational health, logs and minimal admin.

The accepted method cores should not be redesigned. Desk can be piloted first after
these gates; Quant and Qual IDI can follow in the same pilot with stricter data and
privacy handling.

## Evidence and current product shape

The audit inspected the actual FastAPI routers, Jinja templates, CSS/JavaScript,
application services, PostgreSQL models, Docker assets, worker, provider adapters,
download paths and accepted architecture records. No live provider calls or full
test rerun were performed.

Material repository facts:

- `/ui` redirects to `/ui/projects`; projects, method workspaces and Outputs are
  rendered server-side.
- API authentication is bearer API-key based. The UI does not authenticate a
  browser user; `resolve_ui_principal()` obtains one server-side
  `UI_INTERNAL_API_KEY` (or fallback bootstrap key) for every UI request.
- Authorization is fail-closed and owner-scoped: project-derived resources resolve
  through `AuthorizationService.require_project()`, and foreign/unknown resources
  are presented as not found. There is no project membership, invitation or role
  model.
- PostgreSQL persists workflow state, Qual private bytes and PDF/PPTX bytes.
  Quant raw/protected data uses a shared named Docker volume. Checksums and immutable
  source bindings are strong, but there is no repository-operated backup/restore
  policy or tested production recovery procedure.
- The stock Compose exposes API `8000` and PostgreSQL `5432`, embeds development
  database credentials, uses `restart: unless-stopped`, and has no reverse proxy,
  TLS, production hostname policy or secret store.
- Worker leases, retries, durable jobs, readiness checks and immutable downloads are
  mature. Operator visibility and user-facing recovery remain thin.

## Readiness by method

### Desk Research

**Core readiness: accepted. Pilot product readiness: conditional.** The real path
from project/design through bounded research, Evidence, Findings/Insights, Review,
Approved Revision, Report and PDF/PPTX exists. The Desk workbench has the most
developed progress views. Remaining user risks are hidden prerequisites, research
terminology, long-running provider states, insufficient-research explanations and
recovery actions. A researcher still needs an operator to configure providers and
interpret some blocked/failure states.

### Quantitative Research

**Core readiness: accepted. Pilot product readiness: conditional with higher data
controls.** SAV/XLSX upload, QC, weighting, design approval, deterministic analysis,
Results, Findings/Insights, Review, revisions and deliverables exist. The UI exposes
the architecture's many authority layers more directly than a normal researcher
needs. Upload validation is bounded (20 MiB read ceiling; canonical service checks
format and size), filenames are normalized before storage, and the protected data
volume is shared by API/worker. Pilot copy must translate dataset authority, QC,
analysis plan and result states into tasks and plain-language decisions. Backup and
access control are P0 because real datasets may contain respondent data.

### Qualitative IDI

**Core readiness: accepted. Pilot product readiness: conditional with the highest
privacy and complexity risk.** Participant, consent, session, prepared transcript or
audio, transcript authority, coding, AI proposals, Themes, Findings/Insights,
Review, Report and outputs are implemented. The single detail page exposes many
forms and states with little progressive disclosure. Audio versus prepared
transcript, transcription status, transcript correction, codebook/coding, proposal
acceptance and Themes require guided stages. File kinds and sizes are bounded, but
the upload route reads the body before the service size rejection, MIME is not an
authoritative content check, and private bytes reside in PostgreSQL. Real participant
data must not enter a pilot before individual access, retention rules, backup and
privacy instructions are operational.

## Researcher and information architecture verdict

A new colleague cannot reliably start from first login because there is no real
first-login flow. The product opens at Projects under a preconfigured server
identity. Project creation and method entry exist, but the three methods use visibly
different navigation models:

- Desk uses a dedicated workbench with overview/design/evidence/results/report.
- Quant uses overview/data/analysis/results/report.
- Qual uses a long project-scoped detail workspace with many operation forms.
- Shared Project Outputs and Activity sit at project level.

The simplest coherent model is:

`Projects → Project overview → Method workspace → Work → Analysis → Review → Outputs`

This is a presentation hierarchy, not a merger of method semantics. The project
shell should own breadcrumbs, method switcher, progress, Activity and Outputs.
Each method should project its canonical states into the same small set of user
stages while retaining method-specific pages beneath them.

## Visual and design-system audit

Reusable foundations exist: app/project base templates, cards, buttons, forms,
status and empty-state partials, workbench macros, Project Outputs components and
method-specific stylesheets. They are **usable but inconsistent**. Desk, Quant and
Qual were built in phases and differ in page width, navigation, density, status
language, form grouping and action hierarchy.

Minimum pilot design system:

- one app shell, project header, breadcrumb and method navigation;
- primary/secondary/danger button rules and consistent disabled/loading behavior;
- form field, validation summary and upload component;
- status chip vocabulary plus one shared workflow-progress component;
- standard empty, blocked, loading, success and recoverable-error panels;
- provenance summary/details pattern;
- confirmation pattern for approval, replacement and finalization actions.

No component framework migration is required before pilot.

## Workflow, status, AI and trust UX

Users need to see five things on every method page: current stage, completed stages,
next required action, optional actions and the reason a stage is blocked. Internal
states should remain in the domain but map to a smaller vocabulary:

| User label | Typical internal states |
| --- | --- |
| Draft | draft, prepared, pending input |
| In progress | running, processing, claimed |
| Needs your action | review_required, approval_required, changes_required |
| Blocked | validation/readiness/governance prerequisite not met |
| Failed — retry available | recoverable provider/render/job failure |
| Complete | completed, approved, finalized, generated |

The UI must visibly distinguish **AI suggestion**, **researcher-edited draft**,
**researcher decision**, and **canonical approved result**. Provenance should be
progressively disclosed: human-readable source/dataset/transcript support first,
exact IDs/checksums/spans in an audit details panel. Current authority is strong;
the presentation is often too technical.

## Authentication, users and collaboration

Current authentication is production-capable for machine/API clients, not for a
multi-person browser pilot. API keys are hashed, revocable and persisted; API
authorization is owner-scoped. Missing browser-product capabilities are login,
logout, password or external identity, recovery, session expiry, individual user
identity and secure browser sessions.

Minimum pilot role model:

- **Owner/Admin** — provisions/deactivates users, sees health and failed jobs;
- **Research Lead** — creates projects, manages membership, approves/finalizes;
- **Researcher** — works on assigned projects and proposes/edits research outputs.

This can be implemented with users, project memberships and three role values. No
organization hierarchy or fine-grained enterprise RBAC is needed. Before pilot,
every mutation, review and approval must be attributed to the signed-in user.
Optimistic concurrency/conflict messages are required for shared editing; real-time
co-editing is not.

## Privacy, data isolation and file safety

The application-level owner fence and derived-resource authorization are strong,
but the shared UI principal defeats person-level isolation. With individual API
principals, projects are isolated by owner only; there is no safe collaboration
grant. This is a P0 pilot blocker, not an accepted limitation.

PII-sensitive surfaces include Quant respondent datasets and protected derivatives;
Qual participant metadata, consent, audio, transcripts, excerpts and exports; Desk
uploaded/private source material; provider prompts/payloads; temporary renderer and
import files; and database backups. The pilot needs a written data classification,
allowed-data rule, retention/deletion process, and provider disclosure.

Upload protections are uneven. Quant has extension, byte-size and importer-level
validation. Qual allowlists DOCX/TXT and common audio/video suffixes with 5/10/100
MiB limits, but reads uploads without a router-level cap and largely trusts suffix
plus supplied media type. Before real data, use bounded streaming/body enforcement,
magic/content validation, safe generated storage names and explicit rejection copy.
Malware scanning can be a documented pilot limitation if uploads are restricted to
trusted colleagues and the server is isolated; it becomes required before broader
external uploads.

Downloads are a relative strength: project authorization, opaque IDs, checksum and
byte-size validation, immutable identities, correct media types and private/no-store
semantics are present. Ensure all Qual UI export responses receive the same filename
sanitization and cache policy as API/download routes.

## Providers

| Provider | Purpose | Pilot need | Data/privacy and failure notes |
| --- | --- | --- | --- |
| OpenAI | design, extraction/analysis/report/review and optional method AI | Required for live Desk; optional/bounded in parts of Quant/Qual | Research text may leave the deployment. Bounded calls/retries exist; obtain approval and disclose data categories. Never send raw respondent/participant material unless the pilot policy explicitly permits it. |
| Tavily | Desk web discovery | Required for live Desk discovery | Queries and topic context leave the deployment. Bounded candidates/timeouts exist; expose rate-limit/provider failure as recoverable. |
| AssemblyAI | Qual audio transcription | Required only for the audio path | Audio/participant speech leaves the deployment. Prepared Transcript path should be the privacy-minimizing pilot default unless processing terms are approved. |

Provider keys belong in deployment secrets, not Compose defaults or user-visible
configuration. Provider failures are generally bounded and durable, but the UI must
translate timeout/rate-limit/provider failure into stage, retry eligibility and
operator contact without showing payloads or technical exceptions.

## Production and deployment verdict

The stock Compose is a reproducible development deployment, not a safe Internet
deployment. P0 production gaps are individual auth, TLS/reverse proxy, non-default
database credentials, removal of the host PostgreSQL port, secret injection, backup
and restore, and durable capacity monitoring. CORS is not broadly enabled, which is
a safe default. Cookie/CSRF/trusted-host/proxy behavior is absent because browser
sessions are absent; UX-01/OPS-01 must add and configure them together.

Minimum pilot topology:

`Internet/VPN → HTTPS reverse proxy → API/UI → PostgreSQL`

`                                      ↘ worker`

with one private Docker network, no public PostgreSQL port, one persistent database
volume, one persistent Quant protected-artifact volume, deployment secrets, and
host-level encrypted backups. A single server is appropriate for 2–4 colleagues.
Recommended starting estimate: **4 vCPU, 16 GiB RAM, 100–200 GiB encrypted SSD**,
with disk alerts. Use **8 vCPU / 32 GiB** if concurrent local PDF/PPTX rendering,
large SAV/XLSX imports or audio handling is routine. These are estimates; the
repository provides bounds and single-worker behavior but no production load test.

## PostgreSQL, artifacts and recovery

Alembic is mature and CI-tested through head 022. PostgreSQL is the canonical store
for workflow state, Qual private bytes and deliverables; Quant protected data is on
a named volume. Container restart/redeploy is survivable when volumes are retained.
Host loss, volume corruption and operator error are not covered by an operational
backup system.

Minimum pilot backup policy:

- nightly encrypted `pg_dump` plus daily snapshot/copy of Quant protected storage;
- retain 14 daily and 8 weekly copies in a different failure domain;
- back up deployment configuration without secret values and document secret
  recovery separately;
- verify backup completion daily;
- perform and document one full restore into an isolated environment before pilot,
  then monthly during pilot;
- restore DB and protected files as one consistency set; generated deliverables can
  be restored from DB but must not be silently regenerated as historical identity.

## Workers, logs and observability

Durable worker leases, checkpoints, bounded retries, ambiguous-call fencing and
restart recovery are accepted. Remaining operational gaps are a small operator view
for queued/running/failed/stale jobs, safe retry eligibility, worker heartbeat and
disk/database health. One worker is enough initially; concurrency should remain
bounded and measured.

Logging already favors IDs/outcomes and includes redaction tests, but there is no
central pilot logging policy. Production logs must exclude transcript/audio content,
respondent values, source bodies, prompts/provider bodies, API keys and Authorization
headers. Keep event name, project/run/job correlation IDs, stage, safe error code,
duration and provider category. Retain operational logs 30 days unless incident
policy requires longer.

Minimum observability: `/health` and `/ready`, worker health/last heartbeat,
PostgreSQL health and backup age, queue depth/oldest job, failed jobs, disk usage,
provider and render failure counts, and one alert path to the owner. Enterprise APM
is unnecessary.

## Admin, onboarding, help, feedback and telemetry

Minimum admin surface: list/disable users, list projects and members, inspect health,
see failed/stuck jobs and trigger only explicitly safe retries. Direct DB access is
not an acceptable routine pilot operation.

Minimum onboarding: welcome page, data/privacy notice, create-project walkthrough,
plain-language method cards, a five-stage progress guide and a short “AI suggestion
versus approved result” explanation. Add contextual help and a support link rather
than a large manual.

Feedback should capture user, timestamp, page/stage, severity and free-text report;
screenshot upload must be opt-in with a warning not to expose research content.
Privacy-safe telemetry events may include login outcome, project/method created,
stage entered/completed/blocked, action attempted/succeeded/failed, job duration,
provider category/error code, output generated/downloaded and feedback submitted.
Never capture titles, brief text, queries, document/transcript/dataset contents,
participant identifiers or generated research prose.

## Pilot readiness matrix

| Area | Current state/evidence | Risk | Priority | Required action | Phase |
| --- | --- | --- | --- | --- | --- |
| Research workflows | Three methods remotely accepted E2E | Core is strong; product guidance differs | P1 | Preserve cores; add common stage projection | UX-01 |
| UI/UX | Real routes exist; three navigation idioms | Developer knowledge and dead ends | P1 | Shared shell, progress, states, confirmations | UX-01 |
| Authentication | Bearer keys; one server-side UI key | No individual browser identity | **P0** | Login/logout/session/recovery and user attribution | UX-01 |
| Authorization | Owner-scoped fail-closed services | No membership or role grants | **P0** | Project memberships and 3 roles | UX-01 |
| Multi-user | API principals exist; UI collapses users | Unsafe collaboration/attribution | **P0** | Individual users, attribution, conflict UX | UX-01 |
| Privacy | Strong provenance; real PII surfaces | No pilot policy/retention process | **P0** | Data policy, consent/provider rules, deletion SOP | OPS-01 |
| Secrets | `.env` ignored; API keys hashed | Compose dev credentials; no secret operation | **P0** | Generated credentials and deployment secrets | OPS-01 |
| Providers | Bounded adapters and retries | Data transfer/cost/failure not productized | P1 | Allowlisted usage, disclosures, budgets, error UX | OPS-01/UX-01 |
| Deployment | Dev Compose with public 8000/5432 | Unsafe public exposure | **P0** | Private network, HTTPS proxy, hardening | OPS-01 |
| Database | PostgreSQL + tested Alembic 022 | No operational backup/restore | **P0** | Backup, off-host retention, restore drill | OPS-01 |
| Artifact storage | DB bytes + named Quant volume | Host/volume loss; capacity unknown | **P0** | Persistent encrypted storage and backup set | OPS-01 |
| Backups | No canonical pilot procedure | Irrecoverable real data | **P0** | Automated nightly backup + tested restore | OPS-01 |
| Workers | Durable leases/retries/recovery | Thin operator/user recovery | P1 | Queue/failed-job visibility and safe retry | OPS-01 |
| Logging | Bounded operational logs/redaction tests | Policy and central retention absent | P1 | Safe schema, rotation, access and retention | OPS-01 |
| Observability | Health/readiness/worker probe | No disk/backup/queue alerting | P1 | Minimal dashboard/alerts | OPS-01 |
| Uploads | Quant bounded; Qual type/size allowlist | Qual body/MIME/content hardening incomplete | P1 | Request caps and content validation | UX-01/OPS-01 |
| Downloads | Authorized immutable checksummed routes | Some response-policy consistency work | P2 | Standardize safe headers/filenames | UX-01 |
| Admin | CLI/API-key bootstrap; no UI | Owner needs developer/DB access | P1 | Minimal user/project/job/health admin | OPS-01 |
| Onboarding | Project pages and method labels | No first-run orientation | P1 | Welcome, method cards and walkthrough | UX-01 |
| Help | Scattered inline copy | Complex methods need explanation | P1 | Context help + support link | UX-01 |
| Feedback | No canonical in-product mechanism | Learning loop depends on ad hoc contact | P1 | Contextual feedback/problem report | UX-01 |
| Telemetry | Deep research telemetry exists | No privacy-safe product funnel | P2 | Event-only pilot telemetry | PILOT-01 |
| Visual system | Reusable pieces, fragmented styling | Cognitive load and inconsistent actions | P1 | Minimal shared components/tokens | UX-01 |

## Strict priority list

### P0 — blocks safe live pilot

1. Individual browser authentication and secure sessions.
2. Project membership/roles and user attribution across mutations/approvals.
3. HTTPS/private-network deployment hardening and non-default secrets.
4. Backup plus isolated restore proof for PostgreSQL and protected artifacts.
5. Real-data privacy/retention/provider policy and operator procedure.
6. Durable encrypted artifact capacity with disk monitoring.

### P1 — materially harms pilot usability/reliability

- coherent app/project/method navigation and progress guidance;
- plain-language status/error/AI-authority UX;
- progressive Qual workspace and clearer Quant authority vocabulary;
- provider failure/retry communication;
- upload hardening;
- failed-job/admin/health surface;
- safe logging policy and minimal alerts;
- onboarding, contextual help and feedback capture.

### P2/P3 — safe to defer

- richer product analytics, portfolio dashboards and advanced templates (P2);
- malware scanning while access remains trusted/private (P2, revisit before external
  uploads);
- real-time co-editing, organization hierarchy and granular RBAC (P3);
- mobile optimization, unlimited concurrency and multi-region operation (P3);
- Focus Groups, Survey Design, Mixed Methods and cross-method synthesis (P3);
- automated enterprise SSO, audit export and advanced compliance tooling (P3).

## Proposed next phases

### UX-01 — Pilot Product Experience (**Large**)

Scope: individual login/logout/session expiry/recovery; users, three roles and
project membership; attribution; unified app/project shell; method cards and entry;
shared progress/status vocabulary; next-action and blocked-reason panels; consistent
forms/uploads/buttons/confirmations; progressive Quant/Qual navigation; AI proposal
versus approved-result language; provenance summaries; pilot-safe errors; onboarding,
context help and feedback. Preserve all method authority and execution semantics.

### OPS-01 — Pilot Production Readiness (**Large**)

Scope: one-server private deployment; HTTPS reverse proxy/domain; trusted host/proxy
and secure session configuration; generated DB/application secrets; no public DB;
encrypted persistent volumes; migration release procedure; backup/restore automation
and drill; retention/data-provider policy; upload/request limits; log policy/rotation;
health, worker, queue, disk, backup and provider monitoring; minimal admin for users,
projects and failed jobs; runbook and rollback.

### PILOT-01 — Controlled Researcher Pilot (**Medium**)

Scope: 2–4 named colleagues, one lead and one admin; one Desk, one Quant and one Qual
project; prepared transcript as default Qual path unless audio processing is approved;
30–45 minute onboarding; privacy notice; office-hours/support channel; safe product
telemetry and feedback; weekly review; no new method development during the pilot.

## Pilot acceptance and stop criteria

Success criteria:

- all users sign in individually and see only assigned projects;
- a researcher creates a project and starts the intended method without developer
  intervention;
- each pilot method completes its permitted workflow or explains a legitimate block;
- approvals and edits are attributed; AI suggestions are not mistaken for accepted
  authority;
- no cross-project exposure, unrecoverable job or data loss;
- PDF/PPTX outputs generate/download where source eligibility is met;
- daily backups succeed and one restore drill passes;
- no P0 incident, at most three unresolved P1 UX blockers, and fewer than two
  developer interventions per project after onboarding;
- feedback identifies stage and severity without collecting research content.

Stop/rollback criteria:

- any cross-project or unauthorized data exposure;
- lost/corrupted canonical data or failed restore;
- secret leakage or provider payload sent outside approved policy;
- repeated stuck jobs with no safe recovery;
- uncontrolled provider spend;
- critical upload/download vulnerability;
- more than one severe workflow-integrity discrepancy between UI state and canonical
  authority.

Rollback means disable pilot access, preserve DB/artifacts/log evidence, revoke user
sessions/provider keys if implicated, and restore only from the tested consistency
set. It does not mean deleting or recomputing research history.

## Explicit answers

1. Ready today for real colleagues? **No.**
2. Exact prevention: shared UI identity, no membership/roles, dev deployment,
   no backup/restore and no operational privacy envelope.
3. P0 blockers: the six items listed above.
4. P1 issues: coherent guidance, errors/statuses, uploads, provider recovery,
   observability/admin, onboarding/help/feedback.
5. Can wait: enterprise RBAC/SSO, real-time collaboration, mobile, scale and new
   research methods.
6. Authentication sufficient? **API service auth yes; browser pilot auth no.**
7. Multi-user isolation sufficient? **No.** Owner fences exist, but shared UI identity
   and absent memberships fail the pilot model.
8. Storage production-safe? **Durable in one host, not operationally safe without
   encrypted persistence, capacity monitoring and backup.**
9. Backups sufficient? **No canonical backup/restore system is present.**
10. Providers production-safe? **Bounded technically, conditional operationally on
    credentials, privacy approval, cost limits and user-facing failure handling.**
11. UI understandable without developer help? **Not consistently.**
12. Desk pilotable? **Yes after UX-01/OPS-01; first recommended scenario.**
13. Quant pilotable? **Yes after those gates and stricter dataset policy.**
14. Qual IDI pilotable? **Yes after those gates; prepared transcript first.**
15. Minimum topology: one encrypted 4 vCPU/16 GiB server, HTTPS proxy, API, one
    worker, private PostgreSQL and persistent volumes, plus off-host backup.
16. Minimum admin: users/access, projects/members, health and failed-job safe retry.
17. Minimum onboarding: first-login orientation, method choice, workflow guide,
    AI/approval explanation and privacy notice.
18. Safe telemetry: IDs, stage/action/outcome/duration/error category only.
19. UX-01: the bounded scope above.
20. OPS-01: the bounded scope above.
21. PILOT-01: the controlled three-scenario pilot above.
22. Explicit deferrals: new methods, synthesis, enterprise collaboration/RBAC,
    broad scale and mobile optimization.

## Recommended roadmap

`POST-QUA-01 → UX-01 → OPS-01 → PILOT-01 → colleague feedback → pilot fixes → next research capabilities`

- POST-QUA-01: **Medium** — repository-wide product/operations evidence and decisions.
- UX-01: **Large** — cross-cutting browser identity and coherent experience, without
  method redesign.
- OPS-01: **Large** — deployment, recovery, privacy and operation must be proven as a
  system.
- PILOT-01: **Medium** — controlled execution, support and learning rather than code
  breadth.
- Pilot fixes: **Small–Medium**, evidence-driven.
- Next research capability: defer until pilot evidence confirms the product shell.
