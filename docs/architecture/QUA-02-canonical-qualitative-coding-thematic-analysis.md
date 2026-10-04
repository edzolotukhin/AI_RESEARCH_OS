# QUA-02 canonical qualitative coding and thematic analysis

QUA-02 extends `QUALITATIVE/1` from Transcript Authority to an immutable, reviewable analysis authority. It does not create Findings, Insights, Review, Approved Revision, Report, PDF or PPTX.

## Authority chain

`Transcript Version → Analysis Corpus → Codebook Revision → Coding Revision → Thematic Analysis Revision → ready_for_findings`.

An Analysis Corpus stores explicit members. Every member pins project/run, session, participant pseudonym, exact transcript identity/checksum, source artifact and consent record observed at creation. A later transcript version never replaces an existing member. New analyses reject absent authority, foreign runs/projects and the latest withdrawn/ineligible consent; historical records remain append-only.

A Codebook Revision gives each code a stable identity independent of its editable label and definition. Human, AI-proposed and imported origins are distinct. A Coding Revision pins one corpus and one codebook revision. Each application resolves an exact checksum-bound `TranscriptSpanRef`, then persists participant/session provenance and the original excerpt. Overlap and multiple codes per span are valid because applications are independently identified.

AI assistance produces `ai_analysis_proposal` records, never accepted coding directly. The proposal is closed to the supplied corpus/codebook, validates every span before persistence, has a deterministic batch key for retry idempotency and requires an explicit accepted/rejected review record. Batch boundaries are operational provenance, not analytical authority. Production provider choice remains outside canonical persistence; automated acceptance is provider-free.

Categories are optional code groupings. Themes may refer directly to codes or to categories and must include valid supporting applications. Contradictory/deviant applications are modeled separately. Coverage is deterministically computed as corpus participant, session and span counts; validators reject canonical population-percentage/prevalence wording. Memos guide interpretation but cannot satisfy evidence requirements. Original source-language excerpts remain canonical and are never silently translated.

Accepted Thematic Analysis Revisions are immutable and bind the exact corpus, codebook and coding revision. Further work creates a new revision. Human acceptance is mandatory for the terminal state. Project Activity records bounded milestones only; Project Outputs may expose accepted codebook/coding/thematic authorities while continuing to state that no final report exists.

Migration `020_qua02_thematic_analysis` extends only the Activity catalogue/source kinds. QUA-02 records use the existing append-only PostgreSQL qualitative state store introduced by migration 019. Desk Evidence, Quant Results, ARK and web research are not used.

The working analysis DOCX export is explicitly deferred: QUA-01 transcript DOCX remains available, while QUA-02 does not masquerade an analytical working document as a final deliverable. QUA-03 begins only from an accepted Thematic Analysis Revision and owns canonical qualitative Findings and Insights.
