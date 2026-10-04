# QUA-01 canonical qualitative artifact and transcript authority

## Boundary

`QUALITATIVE/1` identifies **In-Depth Interviews**. It is the third CMF authority family:

- Desk: `text_citation` Evidence Authority;
- Quantitative: `dataset_authority` Dataset Authority;
- Qualitative IDI: `transcript_authority` Qualitative Artifact Authority.

Qualitative artifacts are never projected as Desk Sources/Evidence or Quant datasets. QUA-01 stops at authority ready for future Coding; Coding, Themes, Findings, Insights, Review and final report deliverables belong to QUA-02 or later.

## Equal ingestion paths

Recorded sessions bind immutable audio to an asynchronous transcription job. The provider-neutral result is canonicalized inside AI Research OS. Prepared DOCX/TXT sessions bind the original document bytes and parse them directly. Audio is neither required nor synthesized for prepared transcripts. Both paths converge on the same immutable `TranscriptVersion` contract.

## Authority and provenance

Participant identity is pseudonymous. Consent/context is append-only (`unknown`, `eligible`, `withdrawn`); researcher attestation is distinguished from platform-collected consent. A session binds Project, exact run, `QUALITATIVE/1`, participant and research context. Artifacts retain exact checksum, byte size, media type, filename, source mode and private bytes. Replacement creates a new artifact.

Transcript versions bind exact Project/run/session/source artifact/source mode. Segments have stable IDs and order, safe speaker labels/roles, text and optional timing. Word timing is retained only when supplied. Prepared text without timestamps remains untimed. `TranscriptSpanRef` resolves against exact transcript ID, checksum, segment and Unicode `[start,end)` bounds, and therefore fails closed for stale or foreign authority.

Correction, speaker mapping, clean text and redaction create a derived version with an exact parent. V1 is not mutated and downstream consumers must name the version they use. Consent withdrawal preserves historical records but readiness fails closed.

## Parsing and provider boundary

DOCX parsing reads ordered Word paragraphs and recognizes bounded labels (`Interviewer`, `Participant`, `I`, `Pnn`) plus explicit timestamps. Unknown structure is retained with `unknown` speaker rather than inferred. AssemblyAI is an infrastructure adapter implementing the narrow `TranscriptionProvider`; provider response types never enter canonical domain objects. CI uses `DeterministicTranscriptionProvider` and requires no provider credential.

## Worker and persistence

The existing worker loop polls queued Qual jobs in addition to workflow and presentation work. Append-only job records describe queued, transcribing, provider-result, canonicalizing, ready and failure-compatible states. Exact artifact binding and an existing transcript lookup fence retries from silently creating another authority.

PostgreSQL migration `019_qua01_transcript_authority` adds an immutable-record table with private binary storage and extends Activity constraints. The application has equivalent in-memory persistence. No latest-artifact or latest-transcript lookup is an authority decision.

## DOCX and product surface

DOCX import is source ingestion. DOCX export is a generated, private artifact bound to one transcript version; it is not fed back as source authority. Export bytes are persisted once and repeated downloads return the same identity/checksum/bytes. Existing timestamps are shown and absent timestamps are omitted. Verbatim and Clean exports are available only for versions that actually exist.

Protected API and UI actions cover run, participant, consent, session, upload, job processing/inspection, transcript inspection/derivation, readiness, export and download. Project Outputs labels transcript/DOCX artifacts separately and never claims a Qual report, PDF, PPTX or approved revision. Activity records meaningful Qual lifecycle events.

## QUA-02 boundary

QUA-02 may consume an exact analysis-eligible transcript version and stable spans. It must not select “latest”, reinterpret provider payloads, or bypass consent/readiness. Automated coding, codebooks, themes, qualitative Findings/Insights, Review and final report deliverables are intentionally absent here.
