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

Known limitations: no live AI provider qualification; proposal scheduling is synchronous and provider-neutral in this bounded phase, while persisted batch identity/review makes retries resumable and nonduplicating. UI supports corpus selection, codebook creation and analytical state inspection; detailed span/theme editing is available through the protected structured API rather than a rich text-selection widget. The optional analytical working DOCX is deferred. A non-canonical direct `pytest tests/architecture` diagnostic still reports the baseline repository's pre-existing crypto-boundary inventory (18 historical application imports); QUA-02 adds none and the canonical suite is green. QUA-03 is not implemented.
