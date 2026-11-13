# Capability-aware acquisition — patch 2

Parent: `758e1434270a700b2a2349b7829f38e3f0dcc8a8`.
No schema migration beyond patch 1 revision 030.

## Decisions

`decide_acquisition` returns action, reason and required resource kind. Explicit
quantitative Evidence expectations or metric/period coverage contracts request
tables. Legacy unspecified needs retain text behavior. The immutable Design is
read, never modified. Description, metric, geography and periods flow into
navigation terms. No Evidence qualification result is invented here.

* REUSE: successful compatible resource in the same design scope; no HTTP.
* REVALIDATE: compatible resource with new design scope; candidate selection and
  scope/provenance attachment run again without HTTP. Downstream Evidence
  qualification remains responsible for citation/temporal/semantic sufficiency.
* REFETCH: missing/failed resource, explicit refresh, or HTML missing required
  table capability. A failed observation is not fetched repeatedly in one run.
* REEXTRACT: table extraction version changed. Raw
  bytes are not durably stored, so this path performs bounded refetch and parses
  using the configured extractor capability. Proven equal bytes keep their
  content revision while a new extraction revision gets a distinct Source ID.

The adapter supplies its extraction version; search metadata cannot certify it.
Changed terminal bytes create a content revision. Identical terminal snapshots
deduplicate through patch 1 repository locks/constraints, even across landings.

## Navigation and limits

One traversal budget covers the tree and validated redirects: 12 requests,
2,048,000 bytes, 25 considered links, depth 3 and 5 links per page by default.
Caller metadata can lower limits; ceilings are 24 requests, 8,192,000 bytes,
50 links, depth 3, and 10 links per page. Each URL is canonicalized for loop
prevention. Real HTTP responses are streamed in bounded chunks; a byte-budget
overflow aborts the response and cannot become acquired content.

Structured needs reject ordinary descriptive HTML as a terminal and continue
through relevant links. Extensionless downloads retain MIME/ZIP detection.
Text needs retain useful HTML terminals. Challenge pages are rejected. The
existing DNS/SSRF checks run before every network request, including redirects;
TLS verification remains enabled. PDF/unsupported formats remain controlled
unsupported results.

Diagnostics contain counters, maxima, terminal URL, capability decision/reason,
and at most 16 bounded HTTP/link events. Complete documents are not placed in
diagnostics. Actual successful path includes validated redirects. The current
attempt's diagnostics and path are persisted separately from a reused immutable
Source, preventing stale snapshot metadata from replacing new run evidence.

## Qualification

Disposable PostgreSQL 16 on loopback port 55439, database `patch2_test`, migrated
from empty schema through 030. Synthetic loopback HTTP server serves landing HTML
and an extensionless XLSX. Test-only network guard permits that exact fixture
origin; separate tests exercise the unchanged public SSRF/redirect protections.

Real acquisition service plus PostgreSQL repository verifies legacy HTML upgrade,
reuse without HTTP, extraction-version change, changed bytes, concurrent two-
landing deduplication, run-scoped paths, bounded failed retry and historical
Evidence citation validity through a fresh persistence context.

```powershell
# Configure the isolated test URL, POSTGRESQL_INTEGRATION_TESTS=1 and
# POSTGRESQL_DISPOSABLE_TEST_DATABASE=1.
python -m unittest tests.integration.postgresql.test_capability_acquisition tests.integration.postgresql.test_source_revisions tests.integration.postgresql.test_source_provenance_concurrency tests.integration.postgresql.test_prf08c_evidence_integrity tests.application.ports.test_postgresql_repository_contracts -q
python -m unittest discover -s tests/infrastructure/retrieval -q
python -m unittest discover -s tests/application/sources -q
python -m unittest tests.application.evidence.test_run_scoped_provenance tests.application.ports.test_repository_contracts -q
```

Qualification results: PostgreSQL/repository group 53 passed (including one
memory concurrency case); acquisition Source regression 217 passed/2 skipped;
retrieval regression 52 passed/1 skipped; provenance/repository regression 10
passed; Source API regression 2 passed. Source API tests use the existing local
Unicode TTF through PDF_FONT_PATH. No external AI or production requests.

Landing aliases resolve through durable acquisition paths, including across
workflow runs. Reused terminal snapshots retain their original metadata while
each run stores the actual path used by that attempt. Exhaustion from an older
extraction does not suppress a relevant table upgrade when the retriever exposes
that capability. Legacy retrievers retain their exhaustion behavior.

Compressed HTTP content is decoded once and charged to the shared byte budget
after decompression; reconstructed bounded responses remove transport encoding
headers to avoid double decoding.
