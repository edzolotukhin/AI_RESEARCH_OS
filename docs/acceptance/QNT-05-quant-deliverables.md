# QNT-05 — Canonical Quant Deliverables

## Result

QNT-05 completes the provider-free canonical path from a QNT-04
`QuantitativeApprovedRevision` to the existing shared Project Outputs, PDF, and
asynchronous PPTX infrastructure. The approved revision ID is the public source
identity and its immutable fingerprint is the deliverable source version.

## Architecture and provenance

`approved_quantitative_sources` is a read-only adapter. For every canonical
QNT-04 run it resolves and validates the exact persisted chain:

`Approved Revision → approving Review → accepted Report composition → Insights
and Findings generations → Analysis manifest/statistical results → DatasetVersion`.

The adapter checks project/run/method scope, every recorded ID and fingerprint,
the approving verdict, the supported Report identity, each referenced result,
and each result's dataset/data/codebook authority. Missing, stale, foreign, or
substituted authority fails closed. It never resolves a latest object and never
recomputes a statistic. Report prose is projected from the accepted Quant Report;
tables use only persisted referenced `StatisticalResult` values and contexts.

Legacy Quant runs without the QNT-04 review pin retain the accepted historical
composition-based projection. New CMF Quant runs without an Approved Revision
produce no canonical deliverable source. Both legacy and CMF Quant workflow IDs
are recognized by Project Outputs.

## Reused shared infrastructure

- Existing `ProjectDeliverablesService`, private binary store, renderer versions,
  authorization, CSRF, and source-bound download checks are unchanged.
- PDF uses the existing bounded ReportLab renderer and immutable PDF record.
- PPTX uses the existing durable presentation job and PptxGenJS worker path.
- Repeated download returns the stored bytes and validates size/checksum; it does
  not render again.
- Project Outputs distinguishes the approved Quant revision and generated PDF/PPTX.
  Existing Project Activity approval/revision events remain canonical; no parallel
  deliverable-event model was introduced.

## Integrity and provider isolation

Deterministic adversarial coverage rejects: no approval, non-approving Review,
cross-run authority, another method, stale dataset/result/Finding/Insight/Review,
missing authority, mismatched revision, and a newer unapproved composition.
Unknown project/source and revoked ownership remain non-disclosing. Generation
uses no ARK, Tavily, web Evidence, OpenAI, or other provider.

## Acceptance evidence

- New QNT-05 unit/UI source, immutability, authorization, worker, and adversarial
  tests: **10 passed**.
- Consolidated affected Quant/Desk/shared regression: **110 passed**.
- Project Outputs/Activity and production renderer regression: **20 passed,
  3 expected local skips** (local PDF font path); the corresponding renderer was
  exercised in the production image.
- Disposable PostgreSQL API/worker path: **1 passed**. It persisted the QNT-04
  revision, PDF binary and PPTX job/binary, then a separate application container
  recovered and downloaded byte-identical artifacts.
- Offline production image (`--network none`, read-only, 512 MiB): **29 passed**,
  including a real ReportLab Quant PDF, PptxGenJS Quant PPTX/OOXML validation,
  authenticated Quant UI, and shared Desk PDF/PPTX regressions.
- Canonical full offline suite (single final run): **3143 passed, 159 skipped,
  0 failures, 0 errors**.

The legacy Quant composition tests and Desk report/PDF/PPTX tests remained green;
historical records were neither migrated nor rewritten. No migration was added;
the existing migration head remains `017_qnt04_review_activity`.

## Resource and scope status

The disposable QNT-05 PostgreSQL container used `restart=no` and was removed after
the integration test. No QNT-05 acceptance container remains running. The local
production image was retained as a build artifact only. No provider credentials,
`.env` files, generated documents, database dumps, or historical artifacts are
part of the change.

Known limitation: canonical Quant charts remain omitted unless a future accepted
contract binds chart semantics to the Approved Revision; QNT-05 renders exact
persisted result tables rather than inventing chart mappings.
