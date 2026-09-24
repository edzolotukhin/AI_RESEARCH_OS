# PRF-06D compatibility gate — 2026-09-24

## Executed evidence

Synthetic fixtures only. Windows commands in `README.md` ran with
`PRF06C_RUN_NAME=prf06d-windows`; all exited 0 and four validation tests
passed. Python 3.12.14, ReportLab 4.4.9, pypdf 6.10.0, bundled Node 24.19.0,
and bundled Artifact Tool 2.8.59 were used.

| Case | Windows PDF | Windows PPTX | Saved-PPTX preview | Linux PDF |
| --- | --- | --- | --- | --- |
| Desk draft | 2 pages, 28,663 B, 0.117 s | 17 slides, 53,262 B, 11.99 s | 4 sampled slides, 4.35 s | 2 pages, 28,667 B, 0.177 s |
| Quantitative accepted | 3 pages, 30,529 B, 0.207 s | 21 slides, 67,053 B, 9.36 s | 5 sampled slides, 2.32 s | 3 pages, 30,531 B, 0.209 s |

Linux Docker build and network-disabled run exited 0. It used Python 3.11.16,
Debian `fonts-dejavu-core` 2.37-8, ReportLab 4.4.9, pypdf 6.10.0, Pillow
12.3.0, and charset-normalizer 3.5.1. `validate.py --pdf-only` passed 2/2.
The container had a 256 MiB memory cap, 1 CPU, 64-PID cap, read-only rootfs,
no added capabilities, and a 16 MiB tmpfs; it still ran as root. Python
tracemalloc peaks were 1.20/1.28 MB on Windows and 1.20/1.27 MB on Linux;
these are not whole-process RSS. PPTX/preview memory was not measured.
Linux PPTX generation, full 4-test validation, and preview were **not run**.

Original PRF-06C timings/bytes differed slightly. Product byte identity means
repeated download of one stored immutable file, not byte-identical generation.

## PDF qualification

ReportLab directly produces PDF; no second PDF engine was needed. Both Linux
PDFs were parsed with pypdf; a Linux-rendered Desk page was visually inspected
and had readable Ukrainian Cyrillic, headings, body, and footer. An embedded
DejaVuSans TrueType `/FontFile2` was confirmed. Tests verify exact source IDs
and status, all section headings, citations, limitations, 38 repeated
long-text markers, quantitative values/bases/units, links, and >100,000-char
or >1,000-row rejection. The PDF table spans pages with repeated headers.
Long URL/link layout was checked only on synthetic samples, not all real-world
extremes; visual QA is sample-based. ReportLab is the **production PDF engine
candidate**, not an export/storage implementation.

The real Desk `Report` stores sections/citation registry but not every optional
objective text. Quantitative accepted reports store narratives and referenced
table/result IDs; complete cells/chart values live in separate state records.
Production must resolve exact authorized references, preserve missing-data
states, and reject mismatches. Fixtures do not prove real-data authorization.

## PPTX and preview qualification

The actual package is desktop-bundled `@oai/artifact-tool` 2.8.59. On Windows,
it produced editable text, native tables, a native chart with embedded
workbook, and saved-file sampled previews. The four tests verified PPTX slide
structure, source identity/status/values, chart presence/absence, and preview
SHA-256 binding. Its `package.json` is `private: true` and bundled `LICENSE.md`
says "PROPRIETARY AND CONFIDENTIAL", permitting internal evaluation/testing
only and requiring prior written permission for production/commercial use.
The presentation finalizer is also part of that internal runtime. **Do not
package this stack for production.** PptxGenJS (MIT) is a source-level local
generator candidate only; it was not executed, so none of this validation
transfers to it.

The prototype imported the saved PPTX bytes and rendered sample PNGs locally;
no cloud viewer is called in its source. Dependency-internal network behavior
was not independently traced. No independent PowerPoint/LibreOffice renderer
was available or run, so preview fidelity, Linux deployability, geometry, and
font substitution remain unverified. Keep preview disabled by default and
display `Попередній перегляд недоступний. Презентацію можна завантажити.` only
when a downloadable PPTX actually exists.

## Font and license

Linux PDF uses Debian `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` from
`fonts-dejavu-core` 2.37-8; regular and bold are installed. The prototype
registers regular only, so production heading weight needs design review.
Windows PDF used bundled Poppler DejaVuSans at a machine-local path with no
adjacent license; do not redistribute that binary. PPTX names `DejaVu Sans`
but does not embed it; Office substitution is unverified. Preview depends on
locally installed fonts. Debian's
`/usr/share/doc/fonts-dejavu-core/copyright` and upstream
https://github.com/dejavu-fonts/dejavu-fonts/blob/master/LICENSE document
embedding/redistribution subject to notice and renaming restrictions; do not
sell the font standalone. Prefer the Debian package with notices, not a copied
binary; review final packaging with legal/compliance. ReportLab license:
https://docs.reportlab.com/developerfaqs/ . PptxGenJS MIT license:
https://github.com/gitbrent/pptxgenjs/blob/master/LICENSE .

## Security, resource gaps, and handoff

Linux PDF generation used `--network none`; installation used network only at
build time. Prototype source has no API/fetch or research-data access. The
PDF's `example.invalid` link annotations are inert until clicked; production
must sanitize URL schemes and disallow remote asset fetch. Text is escaped
before ReportLab paragraphs. Prototype caps input characters/rows, compressed
PPTX at 5 MB for preview, and each PNG at 2 MB. It does **not** enforce
uncompressed ZIP/entry limits, prohibit all external relationships or macros,
cap wall-clock/RSS/concurrency, run non-root, provide secure persistent temp
isolation/cleanup, or sanitize all errors/logs. ZIP `testzip()` is not a
zip-bomb defense. These controls belong in the production worker/storage layer.

| Component | Classification | Next action |
| --- | --- | --- |
| ReportLab PDF/Linux | Production candidate validated for synthetic scope | Implement source-bound authorized normalization and real-shape acceptance. |
| Debian DejaVu font | Production candidate, packaging notice required | Package via Debian; verify Office substitution separately. |
| Artifact Tool PPTX | Blocked for production | Obtain written rights or qualify an independent local generator; PptxGenJS untested. |
| Local preview | Blocked/unverified | Keep off; compare same saved PPTX in independent office renderer and bound conversion. |
| Python/container packaging | Prototype validated; production integration unverified | Lock internal image/packages, run non-root, add process limits. |
| Source-preserving contract | Prototype validated; production integration unverified | Resolve exact report/version/table/chart references; never invent values. |
| Immutable private storage/download | Deferred | Version/hash outputs and no automatic deletion pending retention policy. |
| Background presentation generation | Deferred | Explicit action, idempotency, timeout, resource caps, failure state. |
| Project Outputs integration | Deferred | Authorized version/status discover and download; no Activity change. |

Production work may begin with PDF/read-model/storage while preview remains
off. The PPTX path must not ship until generator rights and Linux compatibility
are resolved. No application feature was implemented here.
