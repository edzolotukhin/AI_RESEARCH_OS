# ADR-011: HTTP API Boundary and Synchronous Execution Policy

## Status

Accepted (PF-05)

## Context

PF-01 through PF-04 established the domain model, workflow runtime, repository
ports, PostgreSQL adapters, and durable checkpointing. The system remained an
internal Python runtime invoked through the `Agency` facade. PF-05 exposes the
same application capabilities through a stable HTTP API without bypassing the
Application Layer.

## Decision

### API / Application boundary

- **FastAPI** lives under `api/` and is the HTTP adapter.
- Routers depend on **ApplicationContainer** services (`Agency`, `ProjectService`,
  `WorkflowService`, `ArtifactService`, `ExecutionLogService`).
- Routers **must not** import repository ports, ORM models, or PostgreSQL adapters.
- Domain aggregates are mapped to **API DTOs** before leaving the HTTP layer.
- Application services **must not** raise HTTP exceptions.

### Application container

- `create_application_container()` is the Composition Root result for HTTP and
  other entry points.
- `create_application()` remains a convenience wrapper returning `Agency`.
- Concrete persistence adapters are selected only in the Composition Root.

### Synchronous execution policy (PF-05)

- `POST /projects/{project_id}/research` executes planning and workflow runtime
  **synchronously** in the request process.
- No background workers, queues, or fake `202 Accepted` responses.
- Long-running live LLM planning may block the HTTP request; callers must size
  timeouts accordingly.
- API tests inject deterministic LLM/planner dependencies; production requires
  `OPENAI_API_KEY` for the default OpenAI client.

### Durable recovery endpoints

- `POST /workflow-runs/{run_id}/resume` delegates to `Agency.resume_research()`.
- Terminal runs return current state without re-execution.
- PAUSED resume returns **409** (out of PF-04/PF-05 scope).
- Non-durable `file` backend returns **409** for resume.

### Error model

HTTP responses use a consistent envelope:

```json
{
  "error": {
    "code": "entity_not_found",
    "message": "...",
    "details": {}
  }
}
```

Application persistence exceptions map to HTTP status codes in `api/errors.py`.
Stack traces, SQL, credentials, and ORM details are never returned.

### Health vs readiness

- `GET /health` — process liveness only.
- `GET /ready` — backend readiness (`503` when PostgreSQL connectivity fails).
- No Redis, worker, or LLM readiness in PF-05.

### OpenAPI

- `/docs`, `/redoc`, and `/openapi.json` are the public contract surface.
- Stable `operationId` values support future SDK and n8n integration.

### Docker

- Minimal `Dockerfile` runs `uvicorn api.main:create_app --factory`.
- `docker-compose.yml` adds an `api` service depending on PostgreSQL health.
- **Migrations are explicit** — run
  `docker compose run --rm api alembic upgrade head` before starting API in dev.
- Schema is not mutated silently on every import.

### Out of scope (PF-05)

- Authentication, authorization, API keys, rate limiting
- Background workers, Redis, Celery, WebSockets, SSE
- n8n implementation, UI, blob storage, vector database
- Kubernetes / production reverse proxy

### File backend limitation

- Default `file` backend persists projects only; workflow runs and logs are
  in-memory. HTTP resume and durable recovery require `memory` or `postgresql`.

## Consequences

- External systems can integrate through HTTP without touching infrastructure.
- Synchronous research keeps PF-05 honest but limits production scalability until
  PF-06+ background execution.
- API integration tests require explicit container injection to avoid accidental
  PostgreSQL connections during unit runs.
