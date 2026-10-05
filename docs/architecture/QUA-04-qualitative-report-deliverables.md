# QUA-04 — Qualitative Report and deliverables

## Authority and boundary

The sole analytical input is one exact immutable `qualitative_approved_revision` from QUA-03. A Report revision stores that Approved Revision ID/version, its accepted Thematic Analysis Revision, and the exact Finding and Insight IDs. It never resolves “latest” authority and never re-analyses transcripts. QUA-04 does not synthesize Desk, Quantitative, or web material.

Reports are append-only `qualitative_report_revision` records in the existing qualitative state repository. A draft may produce a successor draft. Finalization creates a new immutable final record; edits to a final record are rejected. The source version exposed to the shared deliverable layer is the final state-record checksum.

## Content and qualitative integrity

The deterministic template contains an executive summary, persisted methodology, exact accepted Findings and Insights, supporting excerpts, contradictory/deviant evidence, limitations, and conclusion/implications. Excerpts are selected only from coding applications referenced by the accepted thematic authority and retain transcript, segment, Unicode span, and application identity. Speaker display is pseudonymous; unknown labels are reduced to `Participant`. Missing timestamps remain absent.

Population inference is not introduced. The template uses corpus-bounded language and preserves the QUA-03 overclaim controls. Optional future AI assistance must use the existing provider boundary and may receive only this exact approved chain plus researcher instructions or a current draft; it cannot silently access providers, web, Desk, Quant, or raw transcript re-analysis.

## Shared document lifecycle

`ProjectDeliverablesService` now catalogs `QUALITATIVE` beside `DESK` and `QUANTITATIVE`. All methods converge on `PdfSourceDocument`, the shared ReportLab renderer, durable presentation jobs, PptxGenJS renderer, private immutable `pdf_deliverables` storage, checksum validation, owner authorization, and repeated byte-identical download. Qualitative selection is method-specific; renderer/storage/download infrastructure is not duplicated.

PDF/PPTX identity includes Project, run, method, final Report ID, final Report checksum, renderer/template version, and format. A later Approved Revision cannot move an existing Report or binary. Failed rendering does not create completed metadata; idempotent generation returns the already stored identity.

## Product and Activity

The Qual workspace supports Approved Revision → Report draft → successor draft → final Report. Project Outputs lists final qualitative Reports and the common PDF/PPTX controls. Activity records only meaningful milestones: draft creation, finalization, deliverable readiness, PDF generation, and PPTX generation.

Migration `022_qua04_report_deliverables` only extends Activity check constraints. It creates no Qual-specific binary table and refuses downgrade when QUA-04 Activity rows exist.

## Exclusions

QUA-04 does not reopen analysis, modify Findings/Insights, create population statistics, infer identities or timestamps, implement Mixed Methods, Focus Groups, or a separate renderer/storage subsystem.
