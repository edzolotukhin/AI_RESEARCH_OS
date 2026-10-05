# QUA-03 — Qualitative Findings, Insights, Review and Approved Revision

## Position in the method lifecycle

QUA-03 starts only from an accepted QUA-02 `thematic_revision` and ends at an
immutable `qualitative_approved_revision` whose state is
`ready_for_deliverables`. It does not create reports, PDFs, or presentations.
The authority chain is:

`Transcript → Coding Revision → accepted Thematic Revision → Finding → Insight
→ post-analysis Revision → Review → Approved Revision`.

No QUA-03 service reads raw transcripts to discover Findings. A Finding selects
Theme IDs from one exact accepted thematic revision; its supporting and deviant
application IDs are copied from those canonical Themes. Those applications
already carry the QUA-02 checksum and Unicode span provenance back to the exact
transcript version, session, participant, and source artifact.

## Findings and Insights

Findings are append-only records with stable IDs, revision ordinals, optional
parent identity, exact thematic-revision identity, selected Theme IDs, and
derived supporting/deviant application IDs. Accepted Findings require at least
one canonical Theme. The language guard rejects empty claims and unsupported
quantitative/population certainty patterns such as percentages, “most
consumers”, “the market believes”, and “this proves”. Coverage counts remain
descriptive QUA-02 metadata and are not converted into Quant authority.

Insights are append-only interpretations of one or more accepted Findings from
the same project, run, and thematic authority. They carry exact Finding IDs and
never become independent evidence. Multi-Finding synthesis and synthesis of
tension are supported without suppressing deviant cases.

## AI boundary

AI work is a durable proposal workflow. The request contains the exact accepted
thematic revision and, for Insight proposals, exact accepted Findings. The
provider is not given Desk, Quant, web, Tavily, or ARK context. Structured
outputs are validated against the closed set of Theme or Finding IDs before a
proposal can be persisted. Researcher acceptance atomically and idempotently
canonicalizes the proposal into accepted Finding or Insight records; rejection
does not create authority. Provider prose alone is never evidence.

## Revision and Review governance

`qualitative_post_analysis_revision` binds one project/run, `QUALITATIVE/1`, one
accepted thematic revision, and exact accepted Finding and Insight sets. The
shared Review projection is used for governance. `changes_required` freezes the
reviewed revision: it cannot later be approved. A successor revision with an
explicit parent must be created and reviewed. Shared Review and approved IDs are
deterministic UUIDs, preserving idempotency while satisfying the shared schema.

Approval revalidates every authority link and creates an immutable approved
snapshot containing the exact thematic revision, Finding IDs, Insight IDs,
Review ID, and revision number. There is no implicit “latest” substitution.

## Product, Activity, and Outputs

The Qualitative workspace exposes manual Finding/Insight creation and revision,
AI proposal requests and accept/reject controls, Theme/application provenance
links, revision review, changes-required handling, approval, and the approved
summary. Project Activity records the bounded QUA-03 milestones, and Project
Outputs exposes accepted Findings, accepted Insights, and the Approved Revision
without fabricating a final report.

All API and UI mutations resolve the authenticated owner server-side and all
record lookups remain project-scoped. Foreign, stale, draft, missing, or
cross-run authority fails closed.

## Shared CMF convergence and QUA-04 boundary

Desk, Quant, and Qual retain method-specific analytical authority while sharing
the post-analysis governance shape: Findings, Insights, Review, and Approved
Revision. QUA-03 reuses the shared Review repository and does not reinterpret
Desk Evidence or Quant Results. QUA-04 may consume only the exact approved QUA-03
revision to create a report and deliverables.
