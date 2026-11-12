# Source revisions — integration patch 1

Baseline: `ea6e41dc6b1410482f37ef8d6a5ea0b989103969`.

## Identity and compatibility

`Source.id` identifies an immutable extracted snapshot. Terminal identity is a
project-scoped digest of the normalized final URL, independent of landing URLs.
`content_revision` changes with raw content; `extraction_revision` identifies the
extractor contract. `version` remains an optimistic-lock counter for legacy
provenance merges. Snapshot fields and extraction metadata cannot change through
`save()`; only reference tuples and discovery records remain mutable for existing
readers. Acquisition-path insertion does not update the Source.

Only `raw_checksum_kind=sha256-bytes` establishes binary equality across extractor
versions. Existing callers without bytes use an explicitly labeled surrogate.
Surrogate equality can deduplicate identical extracted results, but never proves
binary identity or permits reusing a content revision across extractor versions.

Migration `030_source_revisions` follows revision 029. All historical IDs, content,
checksums and Evidence FKs are retained. Historical rows start at content revision
1 and extraction revision `legacy-v1`; their surrogate is based on the historical
Source ID. If legacy rows ambiguously collapse to the same terminal identity,
the migration fails transactionally rather than renumbering historical content.
Downgrade refuses when revisions cannot fit the old canonical-URL uniqueness.

## Persistence

`create_immutable_revision` takes a transaction-scoped PostgreSQL advisory lock
derived from terminal identity, including the first insert. Under READ COMMITTED,
the subsequent query sees the committed winner. Matching content/extraction
returns the existing ID; changed raw bytes allocate max(content_revision)+1;
identical proven bytes with a new extractor retain content_revision. Unique
snapshot and revision constraints provide a second duplicate guard. Legacy
`create()` preserves create-only canonical-URL semantics.

Acquisition paths have project/run/Source scope, normalized ordered path digest,
bounded diagnostics, timestamp and a unique run/path/Source observation key.
The repository checks both project linkage and terminal identity. One landing
can point to multiple snapshots and multiple landings can share one snapshot.

Failed-source recovery fetches again and creates a separate immutable revision.
An acquired Source continues to be reused by the existing acquisition policy;
capability-aware refetch of acquired Sources belongs to patch 2. Explicit
repository operations already support changed-content revisions.

## Qualification

Disposable PostgreSQL 16: container `airos-patch1-pg16`, loopback port 55439,
database `patch1_test`. No production data used.

```powershell
$env:POSTGRESQL_INTEGRATION_TESTS='1'
$env:POSTGRESQL_DISPOSABLE_TEST_DATABASE='1'
# Set DATABASE_URL_TEST to the disposable database connection.
python -m unittest tests.integration.postgresql.test_source_revisions tests.integration.postgresql.test_source_provenance_concurrency tests.integration.postgresql.test_prf08c_evidence_integrity tests.application.ports.test_postgresql_repository_contracts -q
python -m unittest discover -s tests/application/sources -q
python -m unittest tests.application.ports.test_repository_contracts tests.application.evidence.test_run_scoped_provenance tests.application.services.test_run_source_count -q
python -m unittest discover -s tests/infrastructure/retrieval -q
```

PostgreSQL/repository group: 50 passed (49 PostgreSQL cases and one memory
concurrency case). Source group: 217 passed, 2 skipped. Repository/provenance
group: 11 passed. Retrieval group: 40 passed, 1 skipped.
Source API regression: 2 passed with `PDF_FONT_PATH` pointing to the existing
local Unicode TTF font. Windows TestClient requires unrestricted local sockets;
restricted execution stalled before entering the application request handler.

Clean migration from an empty database and 029-to-030 migration with synthetic
Source/Evidence were exercised. Two independent sessions concurrently recover a
failed Source and create different extractions of changed content. Historical
Evidence survives migration/refetch and passes canonical citation validation
through a fresh persistence context. Actual acquisition service recovery/reuse
is tested with the PostgreSQL repository and a local fixture retriever.
