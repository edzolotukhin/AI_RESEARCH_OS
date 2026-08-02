# ADR-017: Search, Source Acquisition and Provenance Boundary

## Status

Accepted — DR-03 in progress

## Context

DR-02 delivers `ResearchDesign` / `InformationNeed` and an honest failure point at
`task-collect-evidence`. DR-03 implements the first real external research capability:
search and durable source acquisition, stopping before evidence extraction (DR-04).

## Decision

### Semantic models (Domain)

| Model | Role |
|-------|------|
| `SearchQuery` | Provider-neutral search request derived from `InformationNeed` |
| `SourceCandidate` | Transient search result before retrieval |
| `Source` | Durable acquired document with provenance and bounded inline text |

Evidence extraction remains out of scope (DR-04).

### Query generation

Deterministic `SearchQueryBuilder` maps each `InformationNeed` to one `SearchQuery`
(stable id `sq-{information_need_id}`). No autonomous search planner agent.

### Provider abstraction

- Port: `SearchProvider.search(query) -> list[SourceCandidate]`
- Port: `SourceRetriever.retrieve(candidate) -> Source` (non-persisted)
- Production adapter: **Tavily** (`SEARCH_PROVIDER=tavily`, `SEARCH_API_KEY`)
- Test adapter: `DeterministicSearchProvider` / `DeterministicSourceRetriever`
  (`SEARCH_PROVIDER=deterministic`, explicit only)

Application/domain never import vendor SDKs or HTTP clients.

### Acquisition orchestration

`SourceAcquisitionService`:

1. Read `WorkflowTemplate.research_design_snapshot`
2. Build queries
3. Search → candidates
4. Canonical URL deduplication within project
5. Retrieve content (separate from search)
6. Persist `Source` records

Failure policy (v1):

- Search provider failure → task fails
- Individual retrieval failure → recorded, continue
- Zero successfully acquired sources → task fails

### URL canonicalization

Conservative normalization: scheme/host casing, fragment removal, trailing slash,
known tracking params only (`utm_*`, `fbclid`, `gclid`). Other query params preserved.

Unique constraint: `(project_id, canonical_url)`.

### Content storage

v1 stores bounded inline `content_text` in PostgreSQL (`sources.content_text`, max
512KB at retrieval). PDF retrieval deferred (`retrieval_status=unsupported`).

### Network safety

HTTP/HTTPS only; timeouts; payload limits; SSRF checks block localhost/private/reserved
IPs via `validate_fetch_url`.

### Executor matrix (production)

| Stage | Executor |
|-------|----------|
| planner | implemented |
| search | `SearchExecutor` → `SourceAcquisitionService` |
| analysis | `UnimplementedCapabilityExecutor` |
| report | `UnimplementedCapabilityExecutor` |

`DETERMINISTIC_STAGE_EXECUTORS=1` remains test-only infrastructure bypass.

### API

- `GET /projects/{project_id}/sources`
- `GET /sources/{source_id}`
- Workflow run exposes `sources_available` / `source_count`

PF-08 owner boundary enforced (foreign principal → 404).

### Run/design provenance

`ResearchQuestion`, `InformationNeed`, and `SearchQuery` IDs are **design-local** —
planner fixtures may reuse the same IDs across runs in one project.

Each durable `Source` therefore stores:

- `workflow_run_refs[]` — which runs discovered/linked the source
- `research_design_refs[]` — which design snapshots contributed
- existing `query_refs[]`, `research_question_refs[]`, `information_need_refs[]`
- `metadata.discovery_records[]` — provider, query_id, rank, run/design per discovery

`GET /workflow-runs/{id}` `source_count` / `sources_available` are computed from
sources whose `workflow_run_refs` contains that run ID (not project-wide totals).

### Same-URL deduplication and concurrency

Unique `(project_id, canonical_url)` deduplicates storage. Concurrent creates catch
`DuplicateSourceError` / PostgreSQL integrity violations and merge provenance with
optimistic retry — no process-local locks, no leaked DB exceptions.

### Immutable acquired content (v1)

Once a source reaches `acquired` or `truncated` with content, later discoveries of
the same canonical URL **merge provenance only** — they do not overwrite
`content_text`, checksum, or factual retrieval fields. Explicit reacquisition /
`SourceVersion` is deferred.

### Provenance merge semantics

Reference arrays merge with stable first-seen order and uniqueness. Discovery records
dedupe on `(provider, query_id, workflow_run_id, rank)`.

### Redirect validation

`HttpSourceRetriever` validates every redirect target before following (`fetch_with_validated_redirects`).
Bounded redirect count; http/https only.

### Residual DNS rebinding risk

Pre-request DNS validation reduces SSRF risk but cannot fully eliminate DNS rebinding
with stock httpx without a custom connection transport. Documented limitation for
DR-03; not claimed as complete SSRF prevention.

### Retrieval status semantics

| Status | Meaning | Counts toward search success threshold |
|--------|---------|----------------------------------------|
| `acquired` | Full bounded content retrieved | Yes |
| `truncated` | Content retrieved but exceeded size cap | Yes (partial; `metadata.truncated=true`) |
| `failed` | Retrieval error | No |
| `unsupported` | Content type deferred (e.g. PDF) | No |

Zero threshold-eligible sources → search task fails.

### Persistence

Migration `006_dr03_sources` (includes run/design provenance columns).

## Consequences

- `KnowledgeItem` remains curated project knowledge, not raw web crawl storage.
- `Artifact` remains deliverable metadata, not intermediate fetched pages.
- DR-04 will introduce Evidence linked to `Source` provenance.
