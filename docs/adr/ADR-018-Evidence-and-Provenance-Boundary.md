# ADR-018: Evidence and Provenance Boundary

## Status

Accepted — DR-04 implemented

## Context

DR-03 delivers durable `Source` records with run/design provenance and immutable
acquired content. DR-04 introduces the first durable **Evidence** layer between
source acquisition and future analysis (DR-05).

## Decision

### Source vs Evidence vs Finding

| Entity | Role |
|--------|------|
| **Source** | Acquired external material (URL, bounded inline content, retrieval status) |
| **Evidence** | Bounded, grounded information extracted from a Source snapshot |
| **Finding** | Analytical synthesis across Evidence — **DR-05, not implemented** |

`KnowledgeItem` remains curated project knowledge. `Artifact` remains deliverable
metadata.

### Evidence domain model

Durable `Evidence` stores:

- identity: `id`, `project_id`
- source binding: `source_id`, `source_content_checksum`
- run/design binding: `workflow_run_id`, `research_design_id`
- semantic linkage: `research_question_refs[]`, `information_need_refs[]`
- content: `statement`, `source_excerpt`, `source_locator`, `evidence_type`
- extraction audit: `extraction_method`, `confidence`, `quality_signals`, `metadata`
- dedup: `deduplication_key`

Evidence is append-only after creation.

### Provenance

Every Evidence record answers:

- which Source supports it (`source_id`)
- which content snapshot (`source_content_checksum` at extraction time)
- which workflow run produced it (`workflow_run_id`)
- which design (`research_design_id`)
- which questions/needs (`research_question_refs`, `information_need_refs`)
- where in the Source (`source_locator` normalized offsets + excerpt hash)

Run-scoped IDs are stored explicitly; design-local question/need IDs are not
sufficient alone.

**Run-scoped semantic provenance:** aggregate Source ref arrays may contain merged
provenance from multiple runs. Evidence extraction resolves authoritative
run-scoped question/need IDs from `metadata.discovery_records[]` filtered by
`(workflow_run_id, research_design_id)`, preferring explicit
`information_need_id` / `research_question_id` fields on each record. Aggregate
Source arrays are not used when a Source is shared across runs. Extractor/LLM output is never authoritative for IDs;
application validation replaces refs before persistence.

### Bounded extraction input

Source normalized content is split into deterministic bounded chunks before
extractor invocation:

- `EVIDENCE_EXTRACTION_CHUNK_CHARS` (default 8000)
- `EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS` (default 500)

`ChunkedEvidenceExtractor` wraps production/test extractors. Each chunk failure
is recorded/skipped; other chunks continue. Overlap may rediscover the same
evidence; deduplication prevents duplicate durable rows.

Grounding/locators always reference the **original full Source** normalized
text. When an excerpt appears in multiple places, v1 selects the occurrence
within the chunk's original normalized range.

Deferred: semantic retrieval, embeddings, vector search, RAG platform.

### Source snapshot binding

DR-03 v1 acquired Source content is immutable. Evidence binds to
`source_content_checksum` captured at extraction time so later same-URL
discoveries do not reinterpret historical evidence against new content.

### Grounding rule

`source_excerpt` must be verifiably present in `Source.content_text` after
**whitespace normalization** (collapse runs of whitespace, trim). Ungrounded
candidates are rejected and counted as extraction failures.

### Locator semantics (v1)

`source_locator` stores normalized-text character offsets and an excerpt SHA-256
hash. PDF/section locators deferred.

### Extraction architecture

- Port: `EvidenceExtractor.extract(source, design) -> list[EvidenceCandidate]`
- Service: `EvidenceExtractionService` — selects run-scoped acquired/truncated
  sources, extracts, validates grounding, attaches authoritative provenance,
  deduplicates, persists
- Executor: `EvidenceExecutor` — task `task-extract-evidence`, executor `evidence`

Production: `EVIDENCE_EXTRACTOR=llm` (default) via `LlmEvidenceExtractor`.
Tests: `EVIDENCE_EXTRACTOR=deterministic` explicit only.

Structured LLM output is validated; application code owns all IDs and provenance.

### Quality / confidence semantics

Minimal v1 signals in `quality_signals`:

- `direct` (extractor classification, not objective truth)
- `source_retrieval_status`
- `source_type`

Optional `confidence` is extractor self-report only, not evidential weight.

### Deduplication identity

Unique per run:

`(workflow_run_id, deduplication_key)`

where `deduplication_key = sha256(source_id | checksum | statement | excerpt | sorted need refs)`.

Idempotent replay of the same run resolves existing rows; semantically different
evidence with different keys is preserved.

### Concurrency

PostgreSQL unique constraint on `(workflow_run_id, deduplication_key)`.
`DuplicateEvidenceError` on conflict; concurrent writers resolve to existing row.
No raw DB exceptions leak.

### Failure semantics

| Case | Policy |
|------|--------|
| Ungrounded excerpt | Skip candidate; count failure |
| Irrelevant source (no candidates) | Skip source; count `sources_without_evidence` |
| Extractor/provider failure | Propagate as stage failure |
| Partial source success | Stage succeeds if ≥1 grounded evidence |
| Zero grounded evidence for run | `EvidenceExtractionError`; stage fails |

### Workflow DAG

Preserved task ID `task-collect-evidence` (source acquisition). Inserted:

`task-collect-evidence` → `task-extract-evidence` → `task-analyze` → `task-write-report`

Production honesty:

- search/source acquisition completes when sources acquired
- evidence completes when grounded evidence persisted
- analysis/report remain `CapabilityNotImplementedError` until DR-05/DR-06
- workflow ends `FAILED` if analysis unimplemented

### API

- `GET /projects/{project_id}/evidence` (filters: run, question, need, source)
- `GET /evidence/{evidence_id}`
- Workflow run: `evidence_available`, `evidence_count` (run-scoped)

PF-08: foreign principal → 404.

### Persistence

Migration `007_dr04_evidence`.

### Deferred

- Finding domain model (DR-05)
- SourceVersion / reacquisition
- PDF/section locators
- Complex evidence quality scoring
- Vector/RAG platform

## Consequences

- Analysis (DR-05) can consume durable Evidence with full traceability to Source snapshots.
- Submission fingerprint remains ResearchBrief-only (PF-07); Evidence excluded.
