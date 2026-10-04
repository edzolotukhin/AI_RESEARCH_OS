# QUA-02 local acceptance

## Implemented authority

The product supports an explicit multi-interview Analysis Corpus, immutable Codebook and Coding Revisions, exact overlapping Code Applications, deterministic AI proposal batches with explicit review, optional Categories, Themes with supporting and contradictory evidence, deterministic corpus coverage and an accepted Thematic Analysis Revision ending at `ready_for_findings`.

The known-answer fixture uses three pseudonymous interviews. Two spans support a charging-experience interpretation and one is a deviant petrol-preference case. Assertions cover exact transcript checksums/spans, three participants/sessions/spans, category/code membership and preserved excerpts. Both inductive and deductive inputs converge through the same codebook/coding structures; hybrid origin metadata is retained.

## Integrity and isolation

Corpus creation rejects withdrawn consent, foreign/missing transcript authority and duplicate or ineligible members. Existing corpora stay pinned when newer transcript versions appear. Coding rejects stale checksums, foreign transcripts, out-of-range spans and unknown codes. AI proposals reject nonexistent evidence, unsupported themes and population-statistical claims, are idempotent by batch key, and cannot mutate accepted authority. Themes require valid applications and compute descriptive corpus coverage only.

API ownership precedes all record reads. Project/run/corpus/codebook/coding bindings are checked server-side. Qualitative records are neither Desk Evidence nor Quant Results; no ARK, Tavily, OpenAI, AssemblyAI or web provider is used in acceptance.

Project Activity exposes corpus frozen, codebook created, AI coding completed, coding accepted, thematic revision created/accepted and ready-for-Findings events. Project Outputs exposes only accepted analytical authorities plus the QUA-01 transcript/DOCX artifacts. Findings, Insights, Review, Approved Revision, Report, PDF and PPTX remain absent.

## Verification

- focused QUA-02/QUA-01/API/migration group: 24 passed, 1 skipped;
- real PostgreSQL QUA-01/02 product/API/worker/restart E2E: 3 passed; final QUA-02 Activity/Outputs assertion: 1 passed;
- migration 020 upgrade → downgrade → upgrade passed; single head `020_qua02_thematic_analysis`;
- CMF/Desk/Quant/Activity/Outputs regression: 65 passed plus 21 subtests;
- canonical final post-fix suite: 3173 total, 3011 passed, 162 skipped, 0 failures/errors;
- QUA-02 analytical working DOCX: explicitly deferred; transcript DOCX remains separate;
- disposable `ai_research_os_qua02_postgres` and its anonymous test volume removed; historical Docker resources untouched.

Completion delta adds a browser transcript workspace with same-segment text selection, checksum/segment/Unicode-offset submission, server-side span resolution, manual coding, Codebook workspace, AI job/proposal states and explicit proposal review. The production orchestration uses the existing analysis-stage `LLMClient`; deterministic acceptance replaces only transport and traverses the same queued worker path. Job and batch identities are persisted and retries cannot create duplicate proposals.

Completion focused evidence: browser/provider/API group 15 passed (14 combined authority regressions plus 4 completion tests, with overlap). Final post-completion canonical suite: 3174 total, 3012 passed, 162 skipped, 0 failures/errors.

## Closure implementation evidence

- AI coding acceptance now atomically persists the decision, optional derived draft Codebook Revision, canonical Code Applications, accepted Coding Revision and direct proposal-to-canonical linkage. Replay returns the same canonical identity and cannot duplicate an application.
- AI thematic acceptance produces a canonical draft Thematic Analysis Revision; coding and thematic proposal batches are both deduplicated.
- Explicit failed-job retry persists a child attempt pinned to the same logical request and batch. The total attempt ceiling is three (initial plus two explicit retries); completed, running/non-failed and foreign jobs are rejected.
- The browser Theme workspace supports title/description, Codes, optional Category, separate supporting/deviant evidence, server-derived coverage, canonical transcript navigation, draft save and human finalization to `ready_for_findings`.
- focused QUA-01/02 authority/API/product group: 16 passed;
- fresh PostgreSQL QUA hard gate: 4 passed, including a process-independent queue → restart → proposal → acceptance → replay and failed → restart → explicit retry → success scenario;
- accepted-proposal replay retained one Coding Revision, one Code Application, the exact corpus/checksum/span and one proposal per batch;
- canonical final offline suite: 3176 total, 3013 passed, 163 skipped, 0 failures/errors;
- Alembic remains a single head at `020_qua02_thematic_analysis`; no migration 021 was introduced;
- deterministic providers only; OpenAI, Tavily, AssemblyAI, ARK and web were not called.

Known limitations: no live AI provider call was made; Theme composition uses the repository's form workspace rather than drag/drop visualization. Retry audit is represented by immutable attempt records because migration 020 intentionally has no retry Activity enum. The optional analytical working DOCX remains deferred. A non-canonical direct `pytest tests/architecture` diagnostic still reports the baseline repository's pre-existing crypto-boundary inventory (18 historical application imports); QUA-02 adds none. QUA-03 is not implemented.
