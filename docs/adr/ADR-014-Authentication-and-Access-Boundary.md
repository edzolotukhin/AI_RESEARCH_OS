# PF-08: Authentication and Access Boundary

## Status

Accepted — PF-08

## Context

PF-03 through PF-07 established PostgreSQL persistence, HTTP 202 background execution,
external orchestration, and idempotent research submission. All business endpoints were
public. Machine clients (n8n) require a service-to-service boundary without introducing
a full identity platform.

## Decision

### Authentication model: API keys (Bearer)

- Header: `Authorization: Bearer airos_<key_id>_<secret>`
- No JWT/OAuth in PF-08 — no identity issuer exists
- Keys are service credentials, not user passwords

### Principal model

`AuthenticatedPrincipal` in `application/security/` with `principal_id`, `name`,
`authentication_type`, optional `api_key_id` and `key_prefix`. Domain remains unaware
of HTTP or key formats.

### Storage

Table `api_keys` (migration `005_pf08_auth_boundary`):

| Column | Purpose |
|---|---|
| id | Public key identifier |
| principal_id | Resource owner identity |
| name | Operator label |
| key_prefix | Safe logging prefix |
| key_hash | SHA-256 of full plaintext key |
| is_active / revoked_at | Lifecycle |

Plaintext keys are shown once at bootstrap; never logged or returned by read APIs.

**Constraints:** `id` primary key; unique `key_prefix`; index on `principal_id`. Lookup
authenticates by primary key `id` (parsed from key prefix). `key_hash` uniqueness is not
constrained — SHA-256 collision risk is negligible and CSPRNG secret entropy makes
duplicate verifiers infeasible.

**Credential validity:** accepted only when `is_active == true` AND `revoked_at IS NULL`.
Revocation sets both fields.

### Cryptography layering

- `application/ports/ApiKeyMaterialProvider` — generate/hash/verify contract
- `application/security/api_key_format.py` — prefix and parse rules (no crypto)
- `infrastructure/security/Sha256ApiKeyMaterialProvider` — `secrets`, SHA-256, `hmac.compare_digest`
- Composition Root injects the provider into `AuthenticationService`

Secret entropy: `secrets.token_urlsafe(32)` → 256 bits. Key ID uses `secrets.token_hex(6)` (48 bits, public prefix only).

Authentication uses dummy verifier hash on lookup miss before rejection to reduce obvious timing enumeration between unknown ID and wrong secret.

### Bootstrap

Explicit operator command:

```bash
python -m tools.create_api_key --name n8n
```

Requires PostgreSQL at Alembic head. No anonymous key-creation endpoint.

### Public endpoints

- `GET /health`
- `GET /ready`
- `GET /docs`, `/redoc`, `/openapi.json`

All business routes require Bearer authentication.

### Authorization / ownership

`projects.owner_principal_id` scopes resources. Workflow runs, results, logs, and
artifacts derive access through project ownership. Unauthorized cross-principal access
returns **404** (`entity_not_found`) to avoid enumeration.

Legacy projects with `NULL` owner are inaccessible to authenticated principals until
explicitly backfilled or recreated.

### Idempotency interaction

Idempotency remains scoped per `(project_id, idempotency_key)`. Authorization runs
before submission; principals cannot replay keys against inaccessible projects.
PF-07 concurrency semantics unchanged.

### n8n

Workflows use `AI_RESEARCH_OS_API_URL` and `AI_RESEARCH_OS_API_KEY` environment
variables. Example JSON uses `Authorization: Bearer {{$env.AI_RESEARCH_OS_API_KEY}}`.

### Worker isolation

Worker claims WorkflowRuns via PostgreSQL execution ports only. No HTTP authentication
dependency. API principals are unrelated to worker lease identity.

### Logging

Structured API logs may include `principal_id`, `api_key_id`, `key_prefix`. Never log
raw Authorization headers, plaintext keys, or key hashes.

## Deferred

- Human login/UI, OAuth/OIDC, RBAC, organizations, API gateway, token refresh

## Consequences

- PostgreSQL required for durable API keys in production
- Memory and file backends use in-memory API key stores for tests/dev
