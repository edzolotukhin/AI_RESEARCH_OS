# PRF-06F Project presentations

## Qualification gate

PptxGenJS **4.0.1** (MIT) was selected. It is pinned with a lockfile and
installed with `npm ci`; the production image copies Node **22.16.0** and the
locked local modules from a build stage. No globally installed npm packages,
headless browser, cloud service, or LibreOffice runtime are needed to generate
PPTX. The package lock records the transitive packages, including JSZip,
image-size, and the `https` package. The renderer does not call their network
APIs. It accepts no remote image or media assets; citation URLs remain text.

Synthetic qualification commands from the repository root:

```powershell
docker build -t prf06f-qualify:local prototypes/prf06f_pptx_qualification
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m --memory 256m --cpus 1 --pids-limit 64 -v 'C:\AI_AGENTS\AI_RESEARCH_OS\prototypes\prf06f_pptx_qualification\runs:/output' prf06f-qualify:local
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m --memory 256m --cpus 1 --pids-limit 64 prf06f-qualify:local node qualify.mjs /output --self-test-limits
python -m unittest prototypes.prf06f_pptx_qualification.validate -v
```

The network-disabled, non-root Debian Bookworm/Node 22.16 run generated Desk
ambiguous/draft/approved decks of 15 slides (160,564 / 159,716 / 159,828 B)
and a Quantitative accepted deck of 11 slides (266,363 B). Individual measured
generation times were 39–321 ms and process RSS reached about 72 MB; these are
synthetic measurements, not load-test guarantees. The resource self-test
rejected oversized text and tables and omitted a chart without a base.
OOXML inspection passed three test cases: package validity, all internal
relationships resolved, no external relationships/macros/executables,
Ukrainian text/status/source markers, native table, native chart with embedded
workbook and exact 42/58 synthetic values.

An isolated LibreOffice Impress 7.4 container converted the two primary decks
to 15/11-page PDFs without network access. Sampled title, long Ukrainian
continuation, table, and chart slides were visually inspected; all 55 long-text
markers survived PDF text extraction. No PowerPoint test was performed. This
independent conversion is qualification evidence only; it is **not** a product
preview implementation or a production dependency.

Decision: the local PPTX generator passes the bounded production qualification
gate for source-preserving, editable presentations. This is not a general
fidelity guarantee for arbitrary future report shapes or fonts.

## Source contract and status

The Project Outputs catalog uses the exact saved Desk Report revision and its
same-report review evidence. Draft, approved, and ambiguous/unconfirmed
statuses are source snapshots, never independent presentation approval. A new
review can change the source-version identity and schedule a new presentation;
an existing completed one remains immutable. The exact saved text, sections,
citations, registry, and limitations are used. No later findings/evidence are
queried for slide generation.

Quantitative uses only an accepted supported composition/report for the exact
project/run/study. Its composition ID is the version identity; no Desk-style
revision is invented. The existing PRF-06E contract carries claim text,
referenced display values, base/filter/weighting context, and limitations.
It does not prove ownership of separate statistical table cells or chart
series for a composition, so production omits those rather than reconstructing
them from raw data. The renderer supports native tables/charts when a future
source contract supplies exact authorized rows and sufficient chart metadata.
No cross-method presentation or new research calculation exists.

## Lifecycle, identity, and storage

Only PostgreSQL-backed deployments expose the explicit **Створити презентацію**
action. The action authorizes the project and exact source before inserting a
durable `presentation_jobs` row. The worker polls committed rows, claims one
with a lease, rechecks exact source association/status, and invokes the local
renderer. The states are pending, processing, completed, and failed. Repeated
requests for the same project/method/source/version/template/renderer identity
reuse one job. Failed jobs may be retried up to three attempts. A stale
processing lease can be reclaimed after worker interruption; after three
expired claims it becomes a terminal failed job with no downloadable artifact.

Completed PPTX bytes use the existing PRF-06E private `pdf_deliverables` table
(legacy table name) with explicit format and template-version columns. PDF and
PPTX have distinct MIME checks, size caps, and idempotency keys. The metadata
and bytes commit atomically in one row; the existing trigger rejects updates
and deletes. A crash after blob commit but before job completion is recovered
by finding the same immutable row. A PPTX is downloadable only when its job is
completed and linked to that row. Every download rechecks current ownership,
source/run/study binding, size, and SHA-256. The response is a private/no-store
attachment with a generated ASCII filename; no public URL or filesystem path
is exposed. No generation occurs on download.

## Bounds and operational requirements

The renderer accepts at most 200,000 JSON characters, 100 sections, 1,000
rows/table, 12 columns, 40 chart points, and 250 slides. Exceeding a supported
limit fails rather than truncating source content. Completed PPTX is capped at
10 MB compressed and 20 MB uncompressed; macro and external OOXML
relationships are rejected. The Python subprocess has a 60-second timeout and
Node a 192 MB heap limit. One presentation is processed at a time per worker
loop; deployment should budget at least 512 MB per worker and cap worker count
to available memory. Rendering is in-memory, with no report-content temp
files or report-content logs. The container runs as `appuser`; only the
synthetic qualification harness writes temporary files and cleans them after
failure. Production fonts come from Debian `fonts-dejavu-core`; the PPTX names
DejaVu Sans but does not embed it. Office font substitution remains a
deployment/recipient consideration.

Apply migration `016_prf06f_pptx` before starting the new API and worker image.
The downgrade refuses to remove format columns while immutable PPTX rows
exist. Back up the complete database, including the existing deliverable blob
table and new job table. No slide preview, DOCX, remote conversion, or
project-wide synthesis is implemented. The UI truthfully says preview is
unavailable only after a PPTX is downloadable.
