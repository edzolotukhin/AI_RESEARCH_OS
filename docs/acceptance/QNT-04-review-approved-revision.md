# QNT-04 — Quant Review and approved revision (local gate pending)

## Baseline and reuse

Started from `d685a9da11b5f9f7c5f3f506b19c7cc8ed2ba065` on
`acceptance/live-desk-research-01`, aligned with upstream. QNT-04 reuses the
QNT-02 immutable dataset/result authority, QNT-03 canonical Finding/Insight
validators and report validation, shared Review verdict/repository, QL immutable
Quant state records, CMF exact method pin, durable worker, and Project Activity.
It does not invoke ARK or a provider on the Quant path. Earlier runs without
the new protected review pin retain their previous behavior.

## Authority and decisions

The deterministic Review loads the exact project/run-scoped dataset, analysis
manifest, statistical results, comparisons, Finding generation, Insight
generation, and accepted report composition named by the persisted state. It
checks dataset fingerprints; result dataset/data/codebook; canonical Finding
support against the result set; canonical Insight support against Findings; and
the report's support references and narrative. It also rejects unsupported
confidence intervals, causal wording, contradictory weighting statements and
omitted accepted limitation Insights. Existing validators enforce numeric
closed-world, base/filter, significance and claim-unit semantics. No AI Review
is required or permitted to override these deterministic gates.

The shared verdict is `approve` or `revise`; missing/corrupt authority fails
operationally closed. A `revise` Review persists its issues and creates no
revision. `QuantitativeApprovedRevision` is an immutable source-bound QL record
created only after approval, with project/run/method, report, Review, dataset,
analysis manifest, Finding/Insight generation, plan and weighting fingerprints.
Its identity changes when reviewed sources change; it never resolves latest.
Shared Review and Quant state persistence are separate transactions: a crash
between them can leave a replayable partial result, not an atomic exactly-once
Review+revision unit. Deterministic IDs and immutable conflict checks support
safe replay. Completed analysis alone is not an approved revision.

QNT Review and revision events use the canonical Project Activity table. Review
events are committed with the shared Review row; revision-created is committed
with the immutable revision row. Migration `017_qnt04_review_activity` adds the
event catalogue/check constraints and refuses downgrade if it would discard
Quant Activity history.

## Verification

- QNT-04 offline unit tests: 8 passed. They cover exact binding/replay,
  weighted and non-significant positive paths, changed dataset/report,
  stale Insight, foreign result, unsupported CI/causality/weighting, numeric
  and context tampering, cross-run/missing authority, and protected/legacy pin.
- Focused QNT-04/QNT-03/CMF/Activity group: 27 passed.
- PostgreSQL QNT-03 worker plus shared Review crash/concurrency/isolation:
  5 passed on a dedicated disposable PostgreSQL 16 database.
- PostgreSQL CMF/Quant worker integration: 8 passed on the same disposable
  database, including new Review/revision source binding and rejected Review.
  Expected negative worker exceptions in the log did not fail tests.
- Focused Desk/shared Review/CMF deliverable UI: 43 passed.
- Migration smoke on dedicated disposable migration database: upgrade through
  `017`, downgrade to `016`, then re-upgrade to `017` passed.
- Historical primary PostgreSQL was read-only: all 224 Quant state records
  loaded with zero checksum/integrity errors; Desk counts were reports=8,
  reviews=6, Evidence=2658; no historical workflow carried the new Review pin.
  No historical data was migrated or changed.

The initial canonical offline suite executed 3141 tests:
2981 passed, 159 skipped, 1 failure, 0 errors. Its sole failure was the
repository-readiness test hard-coding Alembic head `016` after the intended
`017` migration was added. The test expectation was updated to `017`; the
affected readiness/Review group then passed: 18 tests, 1 skipped, 0
failures/errors. The one required post-fix canonical suite then passed:
3141 tests, 2982 passed, 159 skipped, 0 failures, 0 errors.

## Boundary and limitations

The approved revision is identifiable by exact immutable QL record ID and
source fingerprints for a future Quant deliverable adapter. Existing Project
Outputs PDF/PPTX generation is not extended or exercised for Quant in QNT-04;
actual deliverable source consumption belongs to the next phase. No PDF/PPTX
was fabricated. No OpenAI, Tavily, live research, or external provider call
occurred. Post-fix full-suite acceptance is complete; CI and live provider
behavior were outside this offline gate.
