# n8n external orchestration examples

These workflows call the AI Research OS HTTP API only. They do not access PostgreSQL
or import Python modules.

## Prerequisites

```bash
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d api worker
docker compose -f docker-compose.yml -f docker-compose.n8n.yml up -d n8n
```

Open n8n at http://localhost:5678 and import JSON files from this directory.

Set environment variable `AI_RESEARCH_OS_API_URL=http://api:8000` inside the n8n
container (provided by `docker-compose.n8n.yml`).

Bootstrap a service API key before importing workflows:

```bash
docker compose run --rm api python -m tools.create_api_key --name n8n
```

Set `AI_RESEARCH_OS_API_KEY` in your environment (or n8n credentials) to the
plaintext value printed once. Workflows send `Authorization: Bearer` using
`{{$env.AI_RESEARCH_OS_API_KEY}}`.

## Primary scenario

1. **create_project_and_research.json** — create project, submit research with
   `Idempotency-Key` and `source=n8n`
2. **poll_research_until_terminal.json** — poll `GET /workflow-runs/{id}` until
   `is_terminal` (recommended interval: 2–5s, bounded timeout)
3. **fetch_results_and_artifacts.json** — retrieve `/results` and `/artifacts`

## Polling guidance

- Poll interval: **2–5 seconds**
- Stop when `is_terminal` is true
- Branch on `status`: `completed`, `failed`, `cancelled`
- Do not tight-loop faster than 1 second

## Idempotency

Use header `Idempotency-Key: <unique-per-submission>` on `POST /research`. Retries
with the same key and body return the same `run_id` without creating a duplicate run.
