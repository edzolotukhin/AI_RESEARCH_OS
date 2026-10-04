# POST-QNT-01 — Product and method portfolio checkpoint

Status: decision checkpoint after remote acceptance of canonical Desk and Quant.
Baseline: `acceptance/live-desk-research-01` at
`0feb2ef2f84df0526c78d89bf339914b41c2c06b`, upstream divergence `0/0`,
Alembic head `018_qnt06d_deliverable_activity`.

## 1. Executive conclusion

AI Research OS now has two complete product method families, but they prove
different things:

- Desk proves bounded external discovery, canonical Source/Evidence integrity,
  adaptive execution, safe insufficiency, and evidence-grounded downstream work.
- Quant proves immutable dataset authority, governed design/QC/weighting,
  deterministic computation, exact statistical provenance, and provider-free
  downstream work.

Together they validate CMF's shared method envelope, version registry, project/run
ownership, authorization, worker/persistence foundation, Findings/Insights/Review
roles, immutable deliverables, Outputs and Activity. They do **not** prove that
Research Design, readiness, execution or support are semantically universal.
Those remain method-owned behind a shared lifecycle.

The next method should be **Qualitative In-Depth Interviews (IDI)**. It materially
extends the product, complements both existing methods, and is the strongest third
proof of CMF because it requires a concrete third authority family: immutable
participant/session/artifact/transcript authority with coded, span-resolvable
excerpts. Treating interview transcripts as ordinary web Evidence would lose
consent, participant/session identity, speaker/time location, transcript version,
redaction and coding provenance.

Do not implement IDI immediately. First run one bounded architecture phase,
**QUA-01 — Canonical Qualitative Authority and Third-Method Enablement**. Its scope
is contracts and routing needed by the first qualitative method, not a platform
refactor: define the new authority and integrity floor, extend CMF's closed support
kind, remove the few remaining Desk/Quant-only catalogue switches needed to register
a third method, and specify participant/privacy/retention boundaries. Then implement
IDI. Focus Groups should reuse the same qualitative authority next. Mixed Methods
comes third as a composition capability after qualitative authority exists.

## 2. Current accepted method products

### Desk Research

Accepted product path:

`Project -> method selection/design -> exact Desk execution pin -> ARK-controlled
discovery/acquisition/extraction -> canonical Sources/Evidence -> readiness ->
Analysis -> Findings/Insights -> Report/Review/Approved Revision -> PDF/PPTX ->
Project Outputs`.

The method is product-complete in the important operational sense: it can execute,
refuse safely when bounded evidence is insufficient, preserve exact provenance,
and produce reviewed deliverables when sufficiency is naturally reached. ARK-07
accepted the architecture with exact ledger/retry/version/citation/readiness-source
gates. The final live case remained genuinely insufficient and therefore did not
prove a successful live Desk E2E deliverable for that frozen case. This is a known
research-coverage limitation, not permission to weaken readiness or citations.

Desk-specific semantics that must remain method-owned include RQ/Information Need
design, search query/retrieval strategy, web candidate selection, Source acquisition,
Evidence extraction, temporal/geographic/relevance qualification, lineage,
sufficiency thresholds, ARK actions and the actual draft-report-before-review flow.

### Quantitative Research

Accepted product path:

`Project -> Quantitative/1 -> immutable SAV/XLSX Dataset Authority -> schema/QC ->
optional governed weighting -> approved Analysis Design -> deterministic execution
-> Statistical Results -> Findings -> Insights -> Review -> Approved Revision ->
persisted Report -> PDF/PPTX -> Project Outputs/download`.

QNT-01 through QNT-06D prove this as a complete provider-free product method with
known-answer numerical acceptance, PostgreSQL restart recovery, exact source-chain
validation, immutable byte-identical downloads and production renderer qualification.
Historical Quant remains readable but is not canonical Quant and is never promoted
by inference.

Quant-specific semantics include dataset/codebook/version authority, QC, measurement
reconciliation, weight approval, supported procedure catalogue, bases/filters,
deterministic statistical computation, significance rules, result fingerprints,
closed numeric-world validation and Quant-specific Review criteria.

## 3. CMF validation with two real methods

| Concern | Classification after Desk + Quant | Decision |
| --- | --- | --- |
| Project, owner and brief | Shared and proven by both | Keep platform-owned. |
| Exact method registry/version envelope | Shared and proven by both | CMF resolves exact versions; never add latest fallback. |
| Run, leases and durable worker lifecycle | Shared and proven by both | Reuse for future methods. |
| Method Design lifecycle | Shared shell, method-specific payload | Approval/invalidation is shared; schemas and eligibility stay method-owned. |
| Authority binding | Shared invariant, distinct implementations | Exact immutable authority is universal; authority shape is not. |
| Execution | Intentionally different | Desk uses ARK adaptive external execution; Quant uses deterministic persisted-data execution. |
| Readiness | Shared result role, method-specific meaning | Operational failure must remain distinct from substantive insufficiency. |
| Analysis | Shared stage role, only partially shared machinery | Desk LLM/evidence analysis and Quant deterministic/statistical analysis should not be unified. |
| Findings | Shared concept, proven with two support families | Keep typed method metadata and exact support refs. |
| Insights | Shared concept, proven by both | Must remain supported by accepted Findings; generation policy stays method-owned. |
| Review | Shared governance envelope, method-specific criteria/order | Exact revision and verdict semantics are shared; do not force one artifact order. |
| Approved Revision | Shared and proven by both | Canonical downstream handoff. |
| Report source projection | Shared output contract, two adapters | Worth keeping behind method binding; content composition remains method-owned. |
| PDF/PPTX and private storage | Shared and proven by both | Mature reusable platform capability. |
| Project Outputs | Shared surface, currently branch-based | Reuse, but third-method routing needs bounded registry projection. |
| Project Activity | Shared event stream, catalogue is hard-coded | Extend through controlled registered event definitions, not arbitrary strings. |
| Authorization | Shared and proven by both | Resolve owner/project before method/resource lookup. |
| PostgreSQL persistence | Shared infrastructure, method-owned records | Avoid a universal payload table. |
| Worker orchestration | Shared and proven by both | Future methods supply jobs/stages, not a second worker. |
| Provenance | Shared integrity floor, typed resolvers | Text citations and dataset authority are proven; no generic unvalidated ref. |
| Validation | Shared fail-closed posture, method-owned rules | Platform integrity AND method eligibility, never either/or. |
| Failure/retry semantics | Shared operational rules, distinct substantive stops | Durable bounded retries are shared; insufficiency meanings remain method-specific. |

The remaining duplication in `ProjectWorkspaceQueryService`,
`ProjectOutputsQueryService`, `ProjectDeliverablesService`, the fixed domain method
catalogue and Activity allowlists is not evidence that method semantics should be
merged. It is a narrow third-method routing concern. Consolidate only the selection,
capability and projection dispatch; retain the two accepted implementations.

## 4. Proven authority taxonomy

### Evidence Authority — proven by Desk

Canonical Source identity/checksum/full normalized content plus Unicode citation
span, scoped Evidence, RQ/IN relationship, temporal/geographic/relevance eligibility,
lineage and bounded ARK execution. It is appropriate for public documents, web
sources, desk content analysis and other externally acquired textual evidence.

### Dataset Authority — proven by Quant

Immutable dataset version/checksum plus codebook, QC, mapping, filters, weight
authority, approved analysis design and deterministic Statistical Result
fingerprints. It is appropriate for survey response analysis and other structured,
row-oriented quantitative computation.

### Qualitative Artifact Authority — required next

Proposed canonical chain:

`approved qualitative design -> participant and consent scope -> session -> immutable
recording/notes artifact -> transcript version -> speaker/time or character span ->
redaction state -> codebook/coding revision -> coded excerpt/theme support -> Finding
-> Insight -> Review -> Approved Revision`.

This authority may reuse the same checksum/span machinery as text citations, but it
is not merely Evidence Authority. The primary artifact is privately collected,
participant-scoped and versioned; its admissibility depends on consent, retention,
redaction and session completeness. A coded excerpt must resolve to the exact
transcript version and location. Unknown speaker, stale transcript, withdrawn consent
or unresolved span fails closed. Theme support must retain all contributing excerpt
references and negative/deviant cases.

Likely reuse by future methods:

| Method family | Authority |
| --- | --- |
| Competitive research, market sizing from published sources, desk content analysis | Evidence; market sizing may also consume Dataset Results through an explicit composition. |
| Survey analysis / concept-test metrics | Dataset. |
| IDI, Focus Groups, moderated UX research | Qualitative Artifact. |
| Social/media listening | Neither unchanged at scale; likely a governed collected-corpus/event authority, possibly a later specialization of qualitative artifacts. |
| Mixed Methods | Existing authorities plus a new cross-method Synthesis Authority; it must not flatten them. |

## 5. Capability inventory

Legend: **Shared** means implemented platform capability used by both; method labels
identify genuinely different implementations; **Absent** means no canonical product
capability yet.

| Capability | Status | What a third method receives |
| --- | --- | --- |
| Project/ownership/brief | Shared | Ready. |
| Method registry and exact version | Shared | Ready after explicit registration. |
| Setup/design approval shell | Shared; payload Desk/Quant | Lifecycle ready, new design schema required. |
| Input acquisition | Desk: web/source; Quant: upload | Transport patterns exist, qualitative private upload/capture absent. |
| Source/data authority | Desk Evidence; Quant Dataset | Integrity pattern ready, new authority resolver required. |
| Execution | Desk ARK; Quant deterministic | Worker/leases ready, method engine required. |
| Deterministic computation | Quant | Optional for coding counts; not a substitute for qualitative interpretation. |
| AI interpretation | Desk and Quant bounded paths | Stage/budget patterns ready; qualitative coding/theming contracts required. |
| Validation/readiness | Shared role, method-specific policy | Envelope ready. |
| Provenance | Shared typed integrity principle | New typed support kind required. |
| Findings/Insights | Shared concept, proven by both | Reusable with qualitative support metadata. |
| Review/Approved Revision | Shared governance, method criteria | Reusable. |
| Report/PDF/PPTX | Shared | Reusable through a report-source adapter. |
| Project Outputs/Activity | Shared but two-method switches remain | Needs bounded third-method dispatch/catalogue extension. |
| Authorization | Shared | Ready; qualitative adds participant/privacy rules. |
| Resumability/retries | Shared infrastructure | Ready for durable stages; method semantics required. |
| PostgreSQL/worker | Shared | Ready; new tables/jobs required. |
| Offline/provider-free acceptance | Strong in Quant; deterministic Desk fixtures | Qualitative can use known transcripts and deterministic coding fixtures. |
| Cross-method synthesis | Absent | Nothing canonical is inherited yet. |

## 6. Material platform gaps

### A. Blockers before a third method

1. CMF's closed support-kind registry accepts only `text_citation` and
   `dataset_authority`; a reviewed qualitative authority contract and resolver are
   required.
2. The domain method catalogue, workspace/output projections, deliverable source
   selection and Activity method/event catalogues still contain explicit Desk/Quant
   branches. Add registry-driven third-method dispatch only at these boundaries.
3. No participant/session/transcript/consent/redaction/retention model exists. This
   is product integrity, not optional infrastructure.

### B. Useful but non-blocking

- A common lifecycle navigation vocabulary and reusable Review/status components.
- Shared presentation of provenance summaries while preserving authority-specific
  detail views.
- Consistent operational failure/retry UX and method progress projection.
- Export/version-history navigation across immutable revisions.

### C. Later platform enhancements

- Cross-method project synthesis, conflict handling and combined deliverables.
- Portfolio-level method comparison and operational observability.
- Rich onboarding and reusable research templates.

None of B or C should delay QUA-01/IDI.

## 7. Candidate decision matrix

Scores use 1–5. Higher is better for value/reuse/testability/leverage. For
**complexity** and **new infrastructure**, higher means more costly. These two are
burden indicators and are not added as benefits.

| Candidate | Business value | Distinctiveness | CMF reuse | Existing authority reuse | UI reuse | Review/deliverable reuse | Complexity | New infra | Testability | CMF proof | Future leverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qualitative In-Depth Interviews | 5 | 5 | 5 | 2 | 3 | 5 | 4 | 4 | 5 | 5 | 5 |
| Focus Groups | 4 | 5 | 5 | 2 | 3 | 5 | 5 | 4 | 3 | 5 | 4 |
| Survey Design / Questionnaire Research | 4 | 3 | 4 | 4 | 4 | 4 | 3 | 2 | 5 | 3 | 4 |
| Content Analysis | 4 | 4 | 5 | 5 | 4 | 5 | 2 | 1 | 5 | 3 | 4 |
| Social/Media Listening | 4 | 4 | 4 | 2 | 2 | 4 | 5 | 5 | 2 | 4 | 4 |
| Competitive Research | 4 | 2 | 4 | 5 | 4 | 5 | 2 | 1 | 4 | 2 | 3 |
| Market Sizing | 5 | 3 | 4 | 4 | 4 | 5 | 3 | 2 | 4 | 3 | 4 |
| Concept Testing | 5 | 4 | 5 | 3 | 3 | 5 | 4 | 3 | 4 | 4 | 4 |
| Customer/UX Research | 5 | 4 | 5 | 2 | 3 | 5 | 4 | 4 | 4 | 5 | 5 |
| Mixed Methods | 5 | 5 | 5 | 3 | 2 | 3 | 5 | 5 | 3 | 5 | 5 |

IDI is preferred despite higher cost because it adds the missing first-party
qualitative authority and a commercially legible workflow. Content Analysis would be
cheaper, but mostly demonstrates another policy over already-proven Evidence Authority.
Competitive Research and Market Sizing are better expressed first as Desk workflows
(with optional governed Quant result inputs) rather than new foundational methods.
Survey Design is a design/fieldwork capability adjacent to Quant; questionnaire design
alone is not yet an independent result authority. Concept Testing and Customer/UX
Research are study products composed from Quant and/or Qualitative execution rather
than the first authority family to build. Social Listening adds ingestion, licensing,
identity and scale complexity before the qualitative core exists.

## 8. Qualitative authority and product boundary

IDI should not ingest a transcript into the public Source repository and call it web
Evidence. Shared checksum, normalized text and span-resolution code can be reused, but
the canonical record must preserve:

- participant pseudonym and consent/withdrawal scope;
- session, moderator and collection mode;
- private artifact checksum and storage identity;
- transcript version, language, speaker turns and time/character bounds;
- redaction/PII review status;
- coding schema/version, coder or bounded model identity and coding revision;
- coded excerpts, themes, contradictions/deviant cases and saturation/readiness;
- exact excerpt/theme support for Findings and Insights.

The product path should be:

`Project -> IDI design -> participant/session setup -> artifact/transcript intake ->
transcript/redaction validation -> coding -> themes/readiness -> Findings/Insights ->
Review -> Approved Revision -> Report/PDF/PPTX -> Outputs`.

The first acceptance can be provider-free using fixed fictional transcripts with
known spans, codes, themes, negative cases and expected readiness. Provider-backed
transcription or AI coding is a separate bounded adapter, not required to establish
authority correctness.

## 9. Mixed Methods decision

Mixed Methods is **later and a composition layer**, not the next independent method.
Desk + Quant availability is insufficient. Canonical Mixed Methods still needs:

- a Synthesis Design binding exact input revisions from each method;
- cross-method provenance that preserves each native authority;
- convergence/divergence/conflict representation;
- synthesis Findings/Insights distinct from source-method conclusions;
- synthesis Review and an Approved Synthesis Revision;
- sequencing/parallel orchestration and combined deliverables.

Without this, a combined report would be presentation-level concatenation or an
unreviewed AI summary. Build it only after Qualitative Artifact Authority is accepted,
so the composition model is proven across three genuinely different supports.

## 10. Recommended sequence

1. **Qualitative In-Depth Interviews** — implement after QUA-01. Authority:
   Qualitative Artifact. Reuses Project, CMF envelope, worker, Findings/Insights,
   Review, revisions, deliverables, Outputs, Activity and authorization. New:
   participants/sessions, private artifacts, transcripts, consent/redaction, coding
   and qualitative readiness. Complexity: **High**.
2. **Focus Groups** — reuse the qualitative authority, adding multi-participant
   speaker identity, group interaction/dynamics, moderator guide and group-level
   coding/readiness. Complexity: **Medium** after IDI, **Very High** before it.
3. **Cross-Method Synthesis / Mixed Methods composition** — bind exact accepted
   Desk, Quant and Qualitative revisions into a new Synthesis Authority with conflict
   handling and synthesis Review. Complexity: **Very High**.

Content Analysis, Competitive Research and Market Sizing should first ship as bounded
design/workflow profiles over existing Desk/Evidence and Quant authorities. Concept
Testing and Customer/UX Research become product templates combining Quant and
Qualitative capabilities once both exist.

## 11. Bounded consolidation decision

**Perform one bounded platform enablement phase before implementing IDI.** This is
required because adding IDI directly would otherwise hard-code a third method into
the domain catalogue, workspace, Outputs, deliverables and Activity, while CMF would
reject its support kind.

QUA-01 scope is limited to:

1. specify immutable Participant, Session, Artifact, TranscriptVersion, CodedExcerpt
   and CodingRevision contracts plus consent/redaction/retention states;
2. define `qualitative_artifact` support identity and resolver/integrity contract;
3. extend CMF capability validation for that reviewed support kind;
4. make method catalogue/workspace/Outputs/deliverable projection/Activity dispatch
   accept an explicitly registered third method without changing Desk or Quant logic;
5. define provider-free known-answer fixtures and threat/adversarial acceptance.

Out of scope: building transcription, coding UI, provider adapters, IDI execution,
new renderers, Mixed Methods, or broad refactoring of Desk/Quant internals.

## 12. Explicit non-recommendations

- **No immediate Mixed Methods:** no synthesis authority, review or conflict model.
- **No Focus Groups first:** harder speaker/group dynamics without a proven transcript
  authority; build on IDI.
- **No Competitive Research as a new method:** mostly a Desk design/profile.
- **No Market Sizing as a new authority family:** use Evidence and governed Dataset
  Results until a concrete unmet authority appears.
- **No Content Analysis as the third CMF proof:** valuable and inexpensive, but it
  mostly reuses the already-proven Evidence family.
- **No Survey Design-only method yet:** it creates an instrument, not accepted result
  authority or fieldwork response lifecycle by itself.
- **No generic plugin system or universal Support table:** explicit registration and
  typed authority resolvers remain the safer architecture.

## 13. Next architecture phase

Recommended phase name:

**QUA-01 — Canonical Qualitative Artifact Authority and Third-Method Enablement**

Its deliverable is an implementation-ready authority, privacy, lifecycle and CMF
integration specification for IDI, with a bounded list of shared routing changes and
known-answer acceptance fixtures. It must not implement the method itself.
