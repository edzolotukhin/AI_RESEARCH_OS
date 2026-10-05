# POST-QUA-01 — Product and pilot readiness audit record

## Baseline

- Repository: `C:\AI_AGENTS\AI_RESEARCH_OS`
- Branch: `acceptance/live-desk-research-01`
- HEAD: `2a1eb95737e0fce6a6399753026a54d5cad14946`
- Upstream divergence at audit start: `0/0`
- Tracked tree/index at audit start: clean
- Alembic: one head, `022_qua04_report_deliverables`
- QUA-04 remote evidence: GitHub Actions run `37294185353`, exact SHA, completed
  `success` with job `test` completed `success`
- Pre-existing historical untracked acceptance/runtime artifacts were left untouched.

## Procedure

This was a read-only product and operations audit followed by documentation only.
The inspection covered:

- FastAPI application/auth/error boundaries and UI routers;
- Jinja templates, shared partials and Desk/Quant/Qual styles/navigation;
- project ownership, API-key authentication and derived-resource authorization;
- method workspaces and supported UI transitions;
- upload/download paths and size/type/checksum handling;
- PostgreSQL models for workflow, Qual private data and deliverables;
- Quant protected filesystem storage;
- worker health, leases, retries, restart behavior and operational logging;
- environment configuration, Dockerfile, stock Compose and CI workflow;
- accepted Desk/Quant/Qual architecture and acceptance records.

No application code, tests, migrations, data, Docker resources, provider credentials
or historical artifacts were changed. No full suite, live research, OpenAI, Tavily
or AssemblyAI call was run. Runtime containers were not started for this audit;
repository and accepted remote evidence were sufficient for the claims made.

## Evidence-based findings

### Product and UX

Real server-rendered product routes exist for Projects, Desk, Quant, Qual and Project
Outputs. All three method lifecycles are reachable, but navigation, density, status
language and next-step guidance differ materially. Desk has a workbench, Quant has
five section pages, and Qual concentrates a long sequence of forms on a project/run
detail page. New-user login/onboarding does not exist.

### Identity and authorization

`api/auth.py` implements bearer API keys. `api/ui/principal.py` resolves a single
server-held UI key; the browser has no individual session. `AuthorizationService`
correctly applies owner fences to projects and derived resources, but there are no
memberships, invitations or roles. This proves fail-closed single-owner isolation,
not a safe multi-colleague product.

### Data and artifacts

PostgreSQL stores Qual private bytes and immutable PDF/PPTX bytes; Quant protected
artifacts use a named shared volume. Download authorization, opaque identities,
checksums and immutable source versions are strong. Quant upload is bounded and
format checked. Qual allows DOCX/TXT/audio/video suffixes with service limits but
reads the upload before enforcing those limits and lacks authoritative content/MIME
validation at the boundary.

### Operations

Stock Compose uses PostgreSQL 16, API and worker with health checks and persistent
volumes. It also exposes PostgreSQL, embeds development credentials, exposes HTTP
without TLS and has no reverse proxy, secret manager, backup job or restore drill.
Worker durability is accepted, but pilot operator views and alerts are absent.

### Providers and privacy

OpenAI, Tavily and AssemblyAI adapters are present for distinct purposes. Existing
budgets, timeouts, retries and redaction are useful controls. A live pilot still
needs a data-transfer policy, credential operation, cost monitoring and explicit
approval for sending participant/respondent/research material to providers.

## Decision

The research architectures are accepted; the product is **not yet pilot-ready**.
The hard blockers are individual UI identity, project membership/roles, production
deployment hardening, backup/restore, protected-storage operation and real-data
privacy policy. These are assigned to UX-01 and OPS-01 rather than another method
phase.

Canonical detailed findings, matrix, phase scopes, server estimate, success and stop
criteria are recorded in
`docs/architecture/POST-QUA-01-product-pilot-readiness.md`.

## Audit acceptance

POST-QUA-01 is complete when:

- baseline and QUA-04 remote success are exact;
- all required product/operations areas have evidence and priority;
- explicit P0/P1/P2/P3 decisions are recorded;
- UX-01, OPS-01 and PILOT-01 have bounded scopes;
- no product behavior is modified;
- one documentation-only checkpoint commit is created and not pushed.

Verdict: `POST-QUA-01_AUDIT_COMPLETE`.
