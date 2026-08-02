# n8n external orchestration

These workflows call the AI Research OS HTTP API only. They do not access PostgreSQL
or import Python modules.

## Canonical product-acceptance workflow

**`desk_research_product_acceptance.json`** — the single canonical end-to-end flow:

1. Create project
2. Submit research with canonical DR-01 `ResearchBrief`, `Idempotency-Key`, `source=n8n`, and `X-Correlation-ID`
3. Poll `GET /workflow-runs/{id}` with bounded attempts (`N8N_MAX_POLL_ATTEMPTS`) and configurable wait (`N8N_POLL_INTERVAL_SECONDS`)
4. Require `status=completed`, `final_review_verdict=approve`, `final_artifact_available=true`
5. Fetch approved final artifact metadata and content
6. Emit compact success payload (`outcome=success`)

Older split workflows (`create_project_and_research.json`, `poll_research_until_terminal.json`,
`fetch_results_and_artifacts.json`) remain as educational PF-07 examples. Use the canonical
workflow above for product acceptance.

## Import

### UI (local dev stack)

```bash
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.smoke.yml up -d api worker
docker compose -f docker-compose.yml -f docker-compose.n8n.yml up -d n8n
```

Open n8n at http://localhost:5678 → **Workflows** → **Import from File** → select
`desk_research_product_acceptance.json`.

### CLI (automated validation)

With the acceptance n8n container running (port **5679**):

```bash
docker compose -f docker-compose.n8n-import-test.yml -p ai_research_os_n8n_acceptance_test up -d n8n
docker cp examples/n8n/desk_research_product_acceptance.json ai_research_os_n8n_acceptance:/tmp/workflow.json
docker exec -u node ai_research_os_n8n_acceptance n8n import:workflow --input=/tmp/workflow.json
```

CI runs this import path via `tests/integration/n8n/test_n8n_native_workflow.py`.

## Required environment variables

Configure in the n8n container (see `docker-compose.n8n.yml`) or host `.env`:

| Variable | Purpose |
|---|---|
| `AI_RESEARCH_OS_API_URL` | API base URL (default `http://api:8000`) |
| `AI_RESEARCH_OS_API_KEY` | Bearer API key (required; never embed in workflow JSON) |
| `N8N_POLL_INTERVAL_SECONDS` | Wait between non-terminal polls (default `3`) |
| `N8N_MAX_POLL_ATTEMPTS` | Hard poll attempt cap before timeout (default `120`) |

Bootstrap a service API key:

```bash
docker compose run --rm api python -m tools.create_api_key --name n8n
```

Set `AI_RESEARCH_OS_API_KEY` in your shell or `.env` to the plaintext value printed once.
Workflows send `Authorization: Bearer {{$env.AI_RESEARCH_OS_API_KEY}}`. Never commit secrets.

HTTP nodes retry transient 5xx up to 3 times. Do not retry 401/409/422.

## Bounded polling

After each non-terminal poll the workflow:

1. Increments `poll_attempt` in **Process Poll Response**
2. Routes through **Is Terminal?** → **Max Poll Attempts?**
3. When `poll_attempt >= N8N_MAX_POLL_ATTEMPTS`, emits **Poll Timeout Payload** (`outcome=poll_timeout`) and stops
4. Otherwise waits `N8N_POLL_INTERVAL_SECONDS` and loops back to **Poll Workflow Run**

Maximum wall-clock wait is approximately `N8N_MAX_POLL_ATTEMPTS × N8N_POLL_INTERVAL_SECONDS` seconds (default ~6 minutes).

## Terminal outcomes

| `outcome` | Condition | Artifact fetch |
|---|---|---|
| `success` | terminal + approve + final artifact available | yes |
| `rejected` | `final_review_verdict=reject` | no |
| `failed` | `status=failed` | no |
| `contract_failure` | terminal without approved final artifact | no |
| `poll_timeout` | max poll attempts reached while still non-terminal | no |

`WorkflowStatus.COMPLETED` alone is **not** sufficient after DR-07.

## Idempotency

Header `Idempotency-Key` on `POST /projects/{id}/research`. Same project + key + payload
→ same `run_id`. Same key + different payload → **409** `idempotency_conflict`.

## Responsibility boundary

| n8n owns | AI Research OS owns |
|---|---|
| external trigger/orchestration | research planning & execution |
| API request sequencing | persistence & recovery |
| polling & bounded HTTP retries | idempotency semantics |
| final delivery handoff | review quality gate & finality |

n8n must not implement Evidence/Findings/Review business rules.

## Automated acceptance (CI)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test_n8n.ps1
```

| Step | What it validates |
|---|---|
| External orchestration API tests | HTTP contract against PostgreSQL |
| Product acceptance harness | Full E2E flow (create → poll → approve → artifact), idempotency, auth, worker restart |
| Native workflow validation | Workflow JSON schema, bounded polling nodes, failure branches, **n8n CLI import** (Docker) |

**CI includes native import validation** when Docker is available. **Full native n8n execution**
(`n8n execute`) against the deterministic stack is not automated in CI: it requires a running
api/worker stack, injected API key, and manual-trigger workflows are awkward for headless CLI
execution. Use the API harness (`test_n8n_product_acceptance.py`) as the E2E contract test;
run the imported workflow manually in n8n UI for native execution smoke.

**Deterministic acceptance** (deterministic search/report/review providers) validates orchestration
contract only. **Live product research** (real OpenAI + Tavily) is a separate milestone.
