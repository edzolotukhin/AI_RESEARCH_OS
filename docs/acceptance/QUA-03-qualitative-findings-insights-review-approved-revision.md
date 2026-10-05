# QUA-03 — Local acceptance record

## Baseline and scope

- Branch: `acceptance/live-desk-research-01`.
- Accepted baseline: `480f6b5e0b064b9cf13dd47b2f207e8ff2cce6d5`
  (`QUA-02_REMOTE_ACCEPTED`, initial divergence `0/0`).
- Input authority: exact accepted QUA-02 Thematic Analysis Revision.
- Terminal authority: exact qualitative Approved Revision in
  `ready_for_deliverables`.
- Final Report, PDF, PPTX, and downloads remain outside QUA-03.

## Implemented authority and product behavior

- Manual and deterministic-AI Findings bind exact accepted Themes and inherit
  their supporting and contradictory/deviant Code Application provenance.
- Manual and deterministic-AI Insights bind exact accepted Findings; the
  known-answer fixture synthesizes multiple Findings.
- Draft/accepted records are append-only and successor records carry explicit
  parent identity. No accepted record is overwritten.
- AI proposal validation rejects empty or unsupported Theme/Finding references.
  Acceptance canonicalizes once; replay returns the same canonical identities.
- Qualitative overclaim patterns fail closed and descriptive corpus coverage is
  not treated as Quant statistical authority.
- Review uses the shared Review projection. A changes-required revision cannot
  be approved unchanged; a successor revision is required.
- Approved Revision freezes exact thematic, Finding, Insight, Review, and
  revision identities. Repeated approval is idempotent.
- The UI exposes Findings, Insights, AI proposal review, evidence navigation,
  revision/review controls, and a researcher-facing Approved Revision summary.
- Project Activity and Project Outputs expose accepted post-analysis authority,
  but no final report deliverable is fabricated.

## PostgreSQL, migration, and restart evidence

- Migration: `021_qua03_findings_review`, based on single head
  `020_qua02_thematic_analysis`.
- The migration extends only canonical Activity event/source constraints; QUA-03
  authority reuses the existing qualitative state and shared Review schema.
- Isolated Alembic `upgrade → downgrade to base → upgrade` smoke: `1 passed`.
- Real PostgreSQL API E2E: `1 passed`. It exercised accepted QUA-02 authority,
  pending AI Finding job across restart, AI Finding acceptance, a second
  Finding, AI Insight acceptance, changes-required, revised successor records,
  Review approval, Approved Revision, Activity, final restart/reload, and exact
  `ready_for_deliverables` recovery.
- The initial E2E exposed a shared Review `varchar(36)` collision from a compound
  ID. The root cause was corrected with deterministic UUID Review/Approved IDs;
  the exact PostgreSQL test then passed.

## Focused verification

- QUA-03 plus QUA-02 API/UI/authority group: `9 passed`.
- Shared CMF/Desk/Quant lifecycle regression: `102 passed`, `45 subtests passed`.
- PostgreSQL QUA-03 E2E: `1 passed`.
- Migration round-trip smoke: `1 passed`.
- Provider isolation: deterministic provider only; no OpenAI, Tavily, ARK, or
  web calls.

Adversarial checks cover no/unknown Theme, qualitative overclaim, draft or zero
Finding Insight authority, malformed AI Theme references, unchanged approval
after changes-required, exact parent authority, idempotent proposal acceptance,
and exact approved snapshot binding. Existing project-scoped authorization and
foreign/unknown-project UI controls remain shared enforcement boundaries.

## Final canonical suite

The first canonical post-implementation run executed `3181` tests and exposed
one stale infrastructure expectation for Alembic head `020`; QUA-03 legitimately
introduces head `021`. No product behavior failed. The expectation was corrected
to the repository's actual single head and its affected module passed `10` tests
with `1` expected skip.

The permitted post-fix canonical run then completed:

- total: `3181`;
- passed: `3017`;
- skipped: `164`;
- failures: `0`;
- errors: `0`.

## Limitations

- No live AI provider call was made; deterministic fixtures exercise the same
  production proposal boundary.
- Review comments are revision-level governance context. Finding/Insight-level
  comments are not separately modeled.
- QUA-03 stops at `ready_for_deliverables`; report composition and PDF/PPTX are
  deliberately deferred to QUA-04.
