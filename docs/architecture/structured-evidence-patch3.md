# Structured Evidence production wiring — patch 3

Parent commit: `92159821af18ee7440898d36ce76f20edcc047ce`.
Schema remains migration 030. No Analysis, Readiness or Report semantics change.

## Production path

`build_evidence_extractor` now composes deterministic structured mapping with the
existing chunked text extractor. The same EvidenceExtractionService validates
run/design provenance, semantic assignment v2, grounding, canonical spans and
deduplication before using the existing repository. Structured observations use
extraction method `xlsx-structured-v2`; ordinary text retains its configured
extractor. Existing provider-configuration inspection remains available.

The workbook capability is incremented to `xlsx-structured-v2`, so patch 2
reextracts an older workbook without modifying its Source revision. Raw bytes,
content/extraction revision and terminal identity come from patch 1 persistence.

## Supported structured contract

The parser identifies explicit annual Year/Рік/Год header tables separately,
including multiple tables/sheets. Each observation preserves table range, header
coordinates/values/checksum, original cell value, decimal numeric value and a
literal canonical row. Formula-aware parsing rejects formula cells without
executing formulas or accepting cached results as observations. External links
are not loaded. Existing content_text/structured_rows remain present; the new
canonical table rows and structured_tables_v2 are additive within render bounds.

The mapper requires explicit metric identity from EvidenceCoverageContract,
an executable ResearchSubject, unambiguous period/value/unit and compatible
explicit geography. Metric labels match normalized exact header labels, allowing
an explicit parenthesized unit; synonyms are not guessed. Multiple matching
tables for the same metric/period fail closed. Merged or unresolved multi-level
headers are conservatively rejected, including a preceding nonempty header
level whose qualifiers have not been resolved.

Only supported aspect IDs are assigned (value/level, metric, period/timepoint,
unit, geography and the explicit metric). Definition/methodology coverage is
never inferred from a numeric row. Existing v2 provenance validation establishes
the final semantic_assignment. observation_period comes from the explicit Year
cell and remains literally grounded in source_excerpt. Legacy period metadata
does not certify an observation date.

Quantitative ambiguity cannot fall through to an LLM for the same IN. Explicit
qualitative INs can still use the existing text extractor alongside structured
observations; duplicate numeric claims are filtered. Text-only sources retain
the original text path. Structured rejection reasons are bounded and serialized
with existing Evidence diagnostics.

## Provenance example from the synthetic E2E

For 2020, value 950 persons in Ukraine:

```text
statement: Population=950 | Year=2020 | Unit=persons | Geography=Ukraine
observation_period: 2020
sheet: Population (index 0)
table_range: A1:D4
header_cells: A1, B1, C1, D1
header_values: Year, Population, Unit, Geography
metric_header_cell: B1
period_header_cell: A1
value_cell: B3
period_cell: A3
unit_cells: C3
geography_cells: D3
```

The persisted source_locator additionally retains normalized_start/end and
excerpt_hash from unchanged canonical grounding. Its structured member contains
terminal_resource_key, raw_workbook_checksum/kind, content/extraction revision
and workbook coordinates. The excerpt is the literal canonical table row.

## Qualification

E2E-A runs actual loopback HTTP acquisition, immutable PostgreSQL Source
revisions, the production Evidence factory configured for LLM text, and real
EvidenceExtractionService/repositories. A provider boundary rejects any LLM call
for structured observations. Synthetic values 2019=1000, 2020=950, 2021=900 are
persisted as three Evidence records with B2/B3/B4 provenance. Shared temporal
qualification accepts all three; deterministic sufficiency recognizes the
validated aspect assignments. Fresh connections validate canonical citations.

Repeated extraction and two acquisition paths do not duplicate observations.
Changed Source content receives separate Evidence; prior Source and Evidence
remain unchanged and citation-valid. Ambiguous tables produce explicit bounded
diagnostics without provider fallback. The original UAT-04A PostgreSQL test is
updated to use production wiring, explicit Design/subject and persisted workflow
scope instead of its former standalone deterministic smoke extractor.

```powershell
python -m pytest tests/application/evidence tests/infrastructure/evidence tests/application/test_ark04_citation_integrity.py tests/application/test_ark06_readiness_sources.py -q
# Set PostgreSQL flags and URL to the disposable patch3_test database only.
python -m unittest tests.integration.postgresql.test_structured_evidence_pipeline tests.integration.postgresql.test_uat04a_bounded_navigation tests.integration.postgresql.test_source_revisions tests.integration.postgresql.test_evidence_concurrency tests.integration.postgresql.test_prf08c_evidence_integrity tests.application.ports.test_postgresql_repository_contracts -q
```

Qualification results: PostgreSQL/repository group 59 passed; focused Evidence,
citation, Readiness-source, qualitative and composition tests 377 passed plus
51 subtests; retrieval 52 passed/1 skipped; Source regression 217 passed/2 skipped;
Source API 2 passed. The expanded E2E also verifies three distinct Evidence sets
for original content, changed content and a new extraction revision, with no
duplicates from an alternate landing or repeat extraction.
