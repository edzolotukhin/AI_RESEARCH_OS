# OPS-01A — Pilot production infrastructure

## Decision

The supported pilot target is one private Linux host running Docker Compose. Caddy is the only public service. The API/UI, worker, and PostgreSQL are separate containers; PostgreSQL and the worker have no published ports. PostgreSQL and explicit named volumes are the canonical persistence boundary.

This is a pilot baseline, not a claim of complete production readiness. `BACKUP/RESTORE P0 OPEN` remains true until OPS-01B completes encrypted off-host backup and an isolated restore drill.

## Discovered runtime

The accepted application is FastAPI/Uvicorn (`api.main:create_app`) with server-rendered UI and API on port 8000. A separate `python -m worker.main` process consumes durable PostgreSQL jobs. `/health` is liveness, `/ready` verifies dependencies, and `python -m worker.healthcheck` verifies worker composition and database readiness.

The development Compose publishes PostgreSQL 5432 and API 8000, uses a known development database password, and has no TLS proxy. It is development-only and remains unchanged.

Canonical PostgreSQL persistence includes projects, identities/sessions/memberships, Desk/Quant/Qual state, jobs, activity, and immutable PDF/PPTX bytes. Qual source bytes and prepared transcripts are stored in PostgreSQL qualitative-state records. Quant raw data, parsed rows, respondent bindings, lineage, and manifests use `ProtectedFileDatasetStorage`; therefore the Quant protected root must be a shared persistent mount for API and worker. `PROJECTS_ROOT` is retained as a compatibility mount, although PostgreSQL is authoritative in pilot mode. No accepted canonical deliverable depends on container-local storage.

## Target topology and trust boundaries

```text
Internet / controlled pilot network
              |
          TCP 80/443
              |
        Caddy TLS proxy -------- public boundary
              |
       pilot_frontend network
              |
        FastAPI API/UI
              |
        pilot_backend network
          /           \
      worker       PostgreSQL
          \           /
        protected named volumes
```

Only Caddy publishes host ports. API exposes 8000 only to Compose networks. Worker has no control endpoint or host port. PostgreSQL has no `ports` entry. Caddy is not attached to `pilot_backend`, so it cannot directly reach PostgreSQL. API and worker may make outbound provider requests when explicitly configured; providers have no inbound route.

## Deployment definitions

- `docker-compose.pilot.yml`: production/pilot services, persistent volumes, health checks, bounded logs, explicit migration and bootstrap jobs.
- `docker-compose.pilot.local.yml`: loopback-only local TLS qualification, `restart: no`, and Caddy internal CA. It is not evidence of public certificate issuance.
- `deploy/pilot/Caddyfile`: real hostname and automatic trusted TLS, including normal HTTP-to-HTTPS behavior.
- `deploy/pilot/Caddyfile.local`: local/staging TLS at `https://localhost:18443`.
- `.env.pilot.example`: placeholders and non-secret defaults only. Real `.env.pilot` files remain ignored.

## Configuration and secrets

`APP_ENV=pilot` activates fail-closed validation. Pilot startup requires PostgreSQL persistence, a non-placeholder database password embedded in the private service DSN, an explicit non-wildcard `ALLOWED_HOSTS`, Secure cookies, disabled debug mode, and a strong runtime-only `UI_CSRF_SECRET`. Validation errors name the setting but never its value.

The CSRF secret is distinct from API service credentials. It signs server-rendered PDF/PPTX mutation forms and is never sent except as action-bound CSRF tokens. `UI_INTERNAL_API_KEY` and `AI_RESEARCH_OS_API_KEY` remain service-integration credentials, not browser identity fallbacks.

Secret inventory:

- mandatory: PostgreSQL password and `UI_CSRF_SECRET`;
- bootstrap-only: owner password, removed from the runtime secret path after bootstrap;
- optional: OpenAI, Tavily/search, and AssemblyAI keys; absence does not prevent startup;
- Caddy: ACME account/certificate state in its named volume; no private key is committed.

Generate URL-safe random values explicitly (the runbook gives an operator command), deliver them at runtime, and never commit the resulting env file. Provider features must report unconfigured/disabled rather than fake readiness.

## HTTP, proxy, sessions, and origins

Caddy terminates TLS and forwards to an unpublished Uvicorn service. Uvicorn accepts proxy headers because its only inbound network peers are Compose services; arbitrary internet traffic cannot reach it. `TrustedHostMiddleware` enforces `ALLOWED_HOSTS` before browser-session handling. Caddy preserves the client host and forwarded scheme, so FastAPI constructs an HTTPS base URL.

Pilot cookies are `Secure`, `HttpOnly`, `SameSite=Lax`, scoped to `/ui`. State-changing UI requests retain same-origin enforcement. Same-origin UI/API means no CORS middleware or wildcard CORS is required. Public-host operation requires the configured DNS hostname and trusted ACME certificate; local qualification uses Caddy's internal CA and proves proxy semantics only.

Caddy accepts bounded request bodies up to 128 MiB, sufficient for the application's supported XLSX, SAV, DOCX, TXT, and bounded audio paths. It does not bypass application authorization for downloads. Connection and response-header waits are bounded; long research execution remains worker/job based rather than an infinite proxy request.

## Persistence and sensitivity

| Boundary | Owner | Contents | Sensitivity | Persistence/backup |
|---|---|---|---|---|
| `pilot_postgres_data` | PostgreSQL | identities, sessions, memberships, project/method state, Qual bytes, jobs, PDF/PPTX bytes | confidential / participant data | mandatory |
| `pilot_protected_data` | API + worker | Quant raw files, parsed rows, respondent bindings and lineage | participant/personal data | mandatory |
| `pilot_project_data` | API + worker | compatibility file-repository path | confidential if used | preserve and inventory |
| `pilot_caddy_data` | Caddy | ACME account and certificate state | operational secret | preserve or reissue deliberately |
| `pilot_caddy_config` | Caddy | Caddy runtime state | internal | operational backup optional |

Encryption at rest is the host's encrypted block device/filesystem boundary for Docker data and backup staging. The application does not claim custom encryption for PostgreSQL or named volumes. Existing Quant integrity/checksum protections remain unchanged. Operators must monitor PostgreSQL, protected storage, Docker data root, and free space; below 30 GiB free is an operator warning threshold, with 50 GiB recommended before large imports. A full capacity/alerting policy is deferred to OPS-01C.

## Lifecycle, health, and logs

Production services use `unless-stopped`; one-shot migration/bootstrap services use `restart: no`. Fatal configuration errors remain visible rather than being concealed by an application-level retry loop. PostgreSQL health gates API, worker, and one-shot jobs. API and worker still perform real readiness checks; start order alone is not treated as readiness.

Migrations run once, explicitly, before API/worker release. API and worker do not independently run Alembic. The accepted schema remains the single head `023_ux01a_identity_membership`. Application rollback and database downgrade are separate decisions; image rollback never implies a safe schema rollback.

Docker `json-file` logs are bounded to five 10 MiB files per service. Application, worker, proxy, and PostgreSQL logs remain available through Compose. Research content and secret values must not be added to diagnostic logs. Central aggregation and retention are deferred to OPS-01C.

## Server and firewall specification

Supported baseline: Debian 12 or Ubuntu 22.04/24.04 LTS; Docker Engine 26+ and Compose plugin 2.24.4+; 4 vCPU, 16 GiB RAM, and 100–200 GiB encrypted SSD minimum; 8 vCPU, 32 GiB RAM, and about 200 GiB preferred. No restrictive per-container memory limits are imposed yet because imports and rendering need measured pilot telemetry.

Inbound firewall: SSH only from controlled operator sources, TCP 80/443 for HTTPS and certificate operations. PostgreSQL 5432, application 8000, and worker endpoints are not public. Outbound: DNS/NTP, approved image/package registries during maintenance, configured providers, and a future backup destination. SSH is key-based; password root login is disabled; sudo and OS updates are restricted to operators.

## Release and rollback

The operator runbook defines first deployment, exact-SHA release, one-shot migration, owner bootstrap, restart, health verification, and application rollback. A release verifies the environment and persistent volumes before migration, then checks PostgreSQL, `/ready`, worker health, HTTPS login/logout, and an authorized project path.

Destructive database rollback is not automated. Forward-compatible migrations and forward fixes are preferred. OPS-01B must add encrypted off-host backups and prove an isolated restore before pilot readiness can be claimed.

## Remaining priorities

P0: encrypted off-host backups; isolated restore drill; retention/deletion policy; provider-transfer privacy policy; stronger MIME/content validation for uploads; production monitoring/operator visibility; real server, DNS, firewall, and trusted-certificate verification.

P1: measured resource limits; formal log retention; automated disk/certificate alerts; credential rotation procedure; hardened OS build checklist; reviewed maintenance-access procedure.

Deferred by design: Kubernetes/distributed orchestration, HA PostgreSQL, centralized SIEM, enterprise vault, autoscaling, multi-region deployment, UI redesign, and new research capability.
