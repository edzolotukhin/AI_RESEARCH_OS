# ARK-01 — Adaptive Research Kernel

Status: architecture decision; implementation is not authorized by this document.
Baseline: `acceptance/live-desk-research-01`,
`dc36e6bfff650d903ebcc711afec6b5d6748eca2` (ahead 27 / behind 0 at inspection).
PRF-08 is closed. This is shared infrastructure design, not PRF-08Y.

## 1. Current failure model

Evidence: [X final gate](../acceptance/PRF-08X-final-desk-live-e2e-gate.md),
[T diagnosis](../acceptance/PRF-08T-live-research-funnel-diagnosis.md),
[S telemetry](../acceptance/PRF-08S-safe-research-funnel-telemetry.md),
[U remediation](../acceptance/PRF-08U-research-funnel-effectiveness-remediation.md),
[W integrity](../acceptance/PRF-08W-temporal-relevance-integrity.md).

X: 12 searches, 24 candidate observations, 8 acquisitions (one truncated and one
content-alias pair), 6 valid-empty extraction calls, zero Evidence, all six needs
uncovered. Two extraction slots remained reserved. Crucially, this was **failed
extraction before readiness**, not an executed sufficiency verdict. Downstream
was safely prevented, but that must not be rewritten as successful adaptive refusal.

`EvidenceExtractionService` raises on zero initial yield with `allow_empty_failure`;
`ResearchReadinessService.assess_and_apply` owns entry into `ResearchLoopService`.
The latter is therefore unreachable in X. Its targeted runner already permits
empty results, but the initial stage has a different control contract.

Other observed mechanisms are structural, not proof that the web lacks evidence:
long concatenated queries retrieve generic definitions; geographic proxy sources
can dominate; acquisition opportunity is mistaken for useful coverage; an official
capacity source is scoped to utilization; equivalent bodies consume acquisition
opportunities. T demonstrates a previously returned candidate becoming productive
later. X does **not** prove every discarded candidate would have been productive.
Six valid-empty responses are not six provider failures or proof of a W rejection:
X had zero raw candidates and zero grounding/provenance rejections.

Existing execution is not entirely static: U depth feedback, K target fidelity,
bounded gap scheduling, query fingerprints and readiness caching already adapt.
The problem is fragmented ownership and stage reachability, rather than absence
of all adaptive logic. Temporal/relevance integrity must remain authoritative.

## 2. Existing reusable components

Paths below are repository-relative implementation anchors, not new APIs.

| Component | Reuse | Boundary that needs an adapter |
| --- | --- | --- |
| `application/services/project_planning_service.py` | Brief/design fingerprints, approval, atomic activation | Kernel receives immutable approved snapshots; does not redesign or approve |
| `application/sources/search_query_builder.py`, `query_opportunities.py` | Intent construction, dispatched-query history | Typed strategy novelty beyond changed text; separate search from batch acquisition |
| `application/sources/source_acquisition_service.py` | URL grouping, eligibility, retrieval, Source persistence | Expose bounded search/select/acquire primitives without hidden batch loops |
| `application/evidence/evidence_extraction_scheduler.py` | Chunk identity, first opportunities, valid-empty/depth feedback | Shared outcome state and explicit per-action caps |
| `application/evidence/evidence_extraction_service.py` | Grounding, provenance, relevance, dedup, persistence | Normalize zero yield as outcome in new kernel path only |
| `application/research_quality/production_targeted_research_runner.py` | Target-specific extraction, remediation purpose/envelope | Split its composite search/acquire/extract execution into ledger-governed steps |
| `research_readiness_service.py`, `research_loop_service.py` in that directory | Qualification, gap priority, cross-IN handling, cached assessments | Retain evaluator; replace competing loop ownership for new runs |
| `application/execution/execution_budget.py`, `infrastructure/llm/budget_enforcing_llm_client.py` | Stage caps, 6+2 partitions, downstream reserves, usage | Durable pre-dispatch reservation and non-LLM dimensions |
| `application/research_funnel_telemetry.py` | Bounded redacted S journal, IDs, outcomes | Decision/reservation correlation only; not policy state |
| `research_loop_checkpoint.py`, `application/ports/workflow_runtime_checkpoint.py` | In-task persistence seams | Prove durable fenced reservation before external dispatch |

Current `SourceAcquisitionBudget.max_sources_per_run` is not automatically a
cumulative whole-scenario cap: targeted acquisition uses a separate `max_sources`.
T recorded nine fetches without a config increase. Preserve actual scoped bounds;
do not infer eight cumulative acquisitions from a misleading variable name.

## 3. Architecture alternatives and decision

| Alternative | Blast radius / migration | Determinism / observation | Reuse / cost control |
| --- | --- | --- | --- |
| A: extend current Desk orchestrator | Small first patch, then repeated changes across stage failure/loop paths | Existing tests help; two scheduling owners risk ambiguous traces | Desk assumptions and split counters remain difficult to share |
| B: bounded controller over existing primitives | Moderate adapter work; versioned opt-in workflow isolates history | Pure reducer and single writer; decisions independently replayable | Shared state/ledger; method-specific policy stays outside controller |
| C: autonomous multi-agent planner | Largest deployment/state/prompt change and paid planning overhead | More nondeterminism and difficult causal accounting | Speculative reuse; unnecessary new cost and recovery risks |

**Choose B**, implemented as a deterministic in-process controller inside the
existing durable worker, not a new service, agent fleet or LLM supervisor. It is
above research primitives and below the existing workflow/downstream gate.
No new paid planning call is required. Architecture A's useful algorithms become
Desk policy functions; do not run A and B as nested competing loops.

Proposed placement: `application/research_kernel/` (state, reducer, ledger,
controller, ports) and `application/methods/desk/` (policy/adapters). These names
are proposed only. Kernel depends on typed contracts, not Desk domain classes,
provider SDKs, UI, or repositories of individual methods.

## 4. State machine and adaptive loop

```text
Approved immutable method input
        |
   OBSERVE -> ASSESS_GAPS -> PROPOSE -> FILTER/RANK -> RESERVE+CHECKPOINT
       ^                       | none                    |
       |                       v                         v
       |                 STOP(reason)                 DISPATCH
       |                                                 |
       +--------- COMMIT_OUTCOME <--- typed outcome ------+
                         |
                method sufficiency satisfied
                         v
                 READY -> existing downstream gate
```

State schema v1: run/project/owner IDs; method/policy/config versions; approved
brief/design fingerprints; revision and lease fence; per-need gaps; candidate and
Source references; source-content/need/chunk outcomes; attempted strategy keys;
budget ledger; pending action; terminal reason. Store IDs and small reason codes,
not copied pages/prompts. Canonical repositories remain the authority for Evidence.

Gap record: need/aspect IDs, priority, raw and qualifying Evidence refs separately,
qualification status/reasons, known lineage diversity, stale-assessment flag,
opportunities already tried, and explicit unknowns. Geography/lineage/relevance
cannot be invented by telemetry when no canonical verdict exists.

Policy evaluation uses the current immutable Evidence view. Cheap deterministic
zero-coverage detection permits scheduling without spending a semantic assessment
on every empty response. Only the existing full method sufficiency contract may
produce READY; it must be current for the exact Evidence/policy fingerprint.
No budget for a required final assessment means NOT_READY, not cached optimism.

One action in flight per run in v1. Deterministic choice from the same state,
policy version and available outcomes; provider results remain nondeterministic.
Outcomes update target and cross-IN gains separately. Raw unrelated/cross-only
yield cannot close the target gap. Valid cross-IN facts remain canonical for their
supported needs and invalidate the relevant assessment caches.

### X-shaped transition, without replaying X

Given six initial valid-empty outcomes, Evidence=0, reserve=2: record zero-yield
outcomes, enter ASSESS_GAPS, do not throw a terminal research error solely for zero.
Select a viable unprocessed existing source/candidate for an uncovered need using
policy priority, scope compatibility and content history. If new acquisition or
search is required, those dimensions must also have capacity. Reserve an entire
feasible path through extraction before buying another search.

Action 7 may extract an unprocessed compatible source/chunk without a new search.
If empty or cross-only, keep the target gap open and consider a distinct feasible
action/need for slot 8, respecting per-gap attempt limits. If a target is repaired,
reassess its material aspects; coverage alone is not readiness. After slot 8 no
further extraction is possible. If no justified action exists earlier, stop then.
Two remaining slots confer permission to consider work, not an obligation to spend.
This is a deterministic future test fixture, not a claim that X would succeed.

## 5. Action taxonomy and decision policy

| Action | Preconditions / adaptation basis | Resource |
| --- | --- | --- |
| REFORMULATE_QUERY | Unresolved aspect and a materially different retrieval intent grounded in approved need | Decision step; any dispatched search separately charged |
| CHANGE_SOURCE_STRATEGY | Recorded mismatch, duplicate saturation or absence; choose another allowed source class/retrieval arm | Decision step, existing gap-attempt limits |
| SEARCH | Novel strategy key, admissible query, feasible acquisition/extraction path | Search/arm attempts, provider credits/cost envelope |
| SELECT_EXISTING | Untried candidate compatible with gap; not already exhausted | Decision step; no fake acquisition/coverage credit |
| ACQUIRE | Safe URL, allowed type, provenance retained, bounded remaining path | Fetch attempt/time/bytes/redirect limits |
| EXTRACT | Acquired admissible content, new source-content/need/chunk opportunity | LLM/extraction tokens and initial/reserve partition |
| REDIRECT_NEED | Target still open or stalled; another viable need per priority/fairness | Decision step; no counter reset |
| ASSESS | Evidence/policy fingerprint changed or final gate needed | Assessment stage budget if semantic call required |
| STOP | Ready, exhausted, no useful action or safety/technical barrier | Terminal checkpoint, no paid call |

Typed outcomes: productive target, productive cross-only, valid-empty, rejected
qualification (with reasons), duplicate, failed acquisition, invalid structured
response, transient provider failure, ambiguous dispatch, integrity violation.
Do not collapse these into one zero-yield counter. A fetch success is not coverage.

Rank admissible actions: material/blocking gap priority, zero qualifying coverage,
known scope fit, untried content/source family, previous target yield, then bounded
fairness and stable ID tie-break. Existing Desk ranking can seed this policy; no
fabricated numeric probability of usefulness is necessary. Known wrong geography
cannot be repaired by downgrading the need; unknown is not silently direct.

Strategy identity includes target need/aspect, source class, retrieval arm,
normalized subject/entity/metric/geography/observation constraints and intent type.
Keep exact provider-query hash as well. Changing whitespace, ordinal, synonyms or
quoting the same generic aspect alone is not new strategy. Permit changing the
aspect sought, source class, or substantive retrieval arm within the frozen scope.
Both identity and allowed alternatives are finite and checkpointed. Candidate-set
overlap and content-alias feedback can exhaust a strategy even with different text.
Do not claim semantic-equivalence detection is solved by a text hash.

## 6. Generic budget ledger

Immutable versioned `BudgetEnvelope` supplied by authorized configuration, never
by a model. Dimensions: total/stage LLM calls; initial/reserved extraction;
search calls per arm and total; acquisition attempts; per-action retry and total
retry attempts; per-gap attempts/rounds; input/output allowances where enforceable;
provider credit/cost estimates; wall-clock deadline; finite decision steps.
Retain response size, timeout, redirect and candidate limits in primitive adapters.

For each dimension: `committed + reserved + uncertain <= ceiling`. Reserve before
dispatch, account attempted calls even when empty/failed/duplicate, reconcile actual
usage once, release only demonstrably undispatched capacity. Retries spend both
their operation dimension and retry allowance; no hidden SDK retry escapes the
envelope. Existing bounded structured recovery counts toward extraction calls.
Default adapters must expose/bound transport attempts or reserve their worst case.

An action/path reservation includes its child operations; spending a child converts
that reservation, never double-debits it. Nested service counters become guards
or views of the same ledger, not separately renewable budgets. A control-only
decision spends one finite decision step, preventing free reformulation loops.
Reservation failure does not reset counters or increase bounds.

Desk reference profile keeps 6 initial + 2 continuation = 8 total extraction calls,
including retries; reserve is unavailable to initial work. Early continuation may
use unused initial allowance only under the existing authorized partition rule.
Preserve downstream assessment/analysis/report/review reserve. Count design-stage
spend in the scenario authorization even though design precedes the research run;
pass a verified remaining allowance at activation, do not reset scenario cost.

Migration must map the old initial and targeted acquisition/search caps explicitly
to one ledger with scoped sublimits and a finite cumulative ceiling no greater
than their prior authorized effective envelope. Do not silently reinterpret an
initial limit of 8 as either unlimited total work or a new larger allowance.
Live-profile search/fetch/retry numbers require configuration-level equivalence
tests before activation; ARK-01 does not approve new numbers.

Money fields distinguish estimated reserved exposure, reported usage and actual
settled charge. Missing tokens/cost remain UNKNOWN, never zero. No provider-side
monetary cutoff is claimed. Stop paid work when a conservative envelope cannot be
maintained under the owner's operational limit; do not build a billing gateway.

### Durable dispatch and crash behavior

Use existing run lease and checkpoint storage, with a durable versioned
`research_kernel_v1` payload. In a fenced revision-checked transaction persist
decision, action ID and reservation **before** external dispatch. Then persist
canonical result refs and ledger completion atomically where existing unit-of-work
permits; otherwise reconcile idempotent refs before marking outcome committed.

States: RESERVED -> DISPATCHED -> COMPLETED/FAILED/AMBIGUOUS. A crash between
reservation and dispatch acknowledgment is ambiguous, not proof of no paid call.
On reclaim, reconcile existing results using stable action IDs. If no supported
provider idempotency/result lookup establishes the outcome, retain worst-case debit
and stop for reconciliation; do not automatically replay the paid operation.
Exactly-once external billing is not promised. Stale workers must fail the fence
before side effects and cannot update counters. Missing persistence/fencing fails
closed for paid execution; current best-effort checkpoint no-op is insufficient.
Whether current JSONB/transaction hooks can provide these guarantees must be
proved by integration tests; no migration is performed or assumed unnecessary.

## 7. Stop conditions

- READY: current method sufficiency verdict and all required constraints satisfied.
- INSUFFICIENT_BUDGET: no feasible next action fits all dimensions/reserves.
- INSUFFICIENT_OPPORTUNITIES: finite admissible strategies/candidates exhausted.
- INSUFFICIENT_NO_PROGRESS: policy's bounded stagnation threshold reached with no
  materially different admissible opportunity; not simply one empty response.
- BLOCKED_DEPENDENCY: unresolved required method input or unsupported capability.
- STOPPED_SAFETY: integrity violation, authorization loss, cost uncertainty or
  expired deadline; preserve Evidence and explicit reason.
- FAILED_TECHNICAL / RECONCILIATION_REQUIRED: infrastructure/persistence failure or
  ambiguous dispatch; never label this as evidence of substantive insufficiency.

Every unsuccessful terminal outcome blocks downstream. User cancellation is a
checkpointed stop; preserve spent/reserved/uncertain accounting. No auto-new run.

## 8. Integrity boundaries

Strategy chooses where to look next, never what counts as Evidence. Frozen brief,
design, criteria and policy version remain immutable within a run. Retain W temporal
interval containment (not publication dates), conservative unknown applicability,
relevance validation, grounding, provenance and authorized project/run ownership.
Retain URL/content dedup and normalized stable lineage; unknown lineage cannot
become independent. Two URLs or facts are not two independent underlying datasets.

The controller cannot insert Evidence, change status/review, rewrite refs, weaken
geography/period or fabricate source metadata. Adapters persist only through current
canonical services. Cross-IN discovery retains original discovery provenance;
new supported IN refs require normal validation, not controller relabeling.
No historical re-evaluation/backfill. New strategy behavior applies only to new
versioned runs. Analytical rules and report/review/exports remain outside kernel.

## 9. Telemetry: reuse S without making it authoritative state

Keep S event types/allowlists, correlation IDs, 4096 cap, redaction and dropped/error
counters. Add additive `adaptive_decision`, `budget_reservation`, `action_outcome`
and `kernel_stop` observations: state revision/fingerprint -> gap/reason -> action
and strategy ID -> expected resource vector -> actual/uncertain usage -> outcome
refs/target gain/cross gain -> next revision. No provider bodies, keys or raw prompts.

Critical decisions/action IDs/ledger live in mandatory bounded canonical state,
not the optional journal. Store a finite decision trail limited by decision ceiling;
S mirrors it and may truncate without changing behavior. Exact query visibility
still carries `query_exact`; no inference from a redacted query. Telemetry on/off,
capped or throwing must yield identical action sequence, calls and sufficiency.
Explain failure from persisted decisions when observational events are missing.

## 10. Method/kernel boundary

Kernel owns durable state transitions, resource reservation, action dispatch,
deterministic scheduling mechanism, deadlines, recovery, audit and stop protocol.
Method owns meaning: needs/aspects, legal strategies, qualification, independence,
priority/fairness policy, sufficiency and analytical handoff requirements.
Kernel filters all method proposals through universal authorization/resource gates.
Methods cannot mutate ledger, dispatch hidden calls or override integrity verdicts.

Desk is first adapter. Quantitative or other methods may expose approved dataset
acquisition/validation actions instead of web search; unsupported actions are absent,
not fake Desk equivalents. Reuse is optional where applicable, not permission to
adapt sampling/statistical plans or consent without their own approval contract.

## 11. Canonical Method Framework (minimal proposed contract)

| Port | Input -> output | Constraint |
| --- | --- | --- |
| `describe()` | method/policy version, supported action/outcome schemas | Fixed capability registry; no dynamic plugin code loading |
| `prepare(approved_input)` | typed NeedSpecs, dependencies, immutable constraints | Reject missing approval/unsupported capabilities before spending |
| `observe(canonical_refs)` | immutable qualification/coverage view with unknowns | Read only, scoped; use authoritative existing evaluators |
| `assess_gaps(view)` | prioritized GapSpecs and assessment requirements | Pure for known state; semantic work must be an explicit metered action |
| `propose(state,gaps)` | finite ActionSpecs with novelty/preconditions/resource upper bounds | No network, writes or paid planning; bounded candidate generation |
| `execute(action,reservation)` | typed Outcome + canonical refs + usage receipt | Adapter only, fenced/idempotent; no additional unreserved operations |
| `validate_outcome(outcome)` | accepted refs and target/cross/constraint deltas | Existing method integrity rules cannot be overridden by controller |
| `sufficiency(view,assessment_refs)` | READY/NOT_READY/UNKNOWN + reasons/fingerprint | Pure final decision; expensive evaluator requests explicitly budgeted |
| `handoff(ready_snapshot)` | existing downstream contract | Only current verified READY, no fabricated report approval |

Versioned DTOs: NeedSpec, GapSpec, StrategySpec, ActionSpec, ResourceVector,
Outcome, SufficiencyVerdict. Each action has run/owner IDs, idempotency key,
target/scope, expected state revision, policy version, resource reservation and
safe reason. Unknown outcome enum/version is blocked, not coerced into success.
Method conformance tests are mandatory. One fake non-Desk method demonstrates
portability offline; no second production methodology implementation is required.

## 12. Migration from current Desk

Opt in **new** workflow templates to a versioned kernel executor owning the research
phase (search through final sufficiency). Retain existing worker, activation, owner
checks, canonical repositories and downstream task/gate contracts. Do not rewrite
task history for old runs or silently resume old partial runs with new semantics.

First isolate adapters without changing old callers. The new kernel path consumes
typed valid-empty outcomes; legacy executor retains legacy behavior until its
retirement is explicitly accepted. This is versioned migration, not acceptance-only
bypass. No catch-all conversion of technical/validation exceptions to empty success.
Avoid calling legacy `assess_and_apply` and its loop from inside the kernel:
reuse evaluation/final gate with a single scheduling owner.

Persist kernel version at activation. Reuse JSONB only if fencing/atomicity tests
prove it sufficient; any required persistence change needs a separately reviewed
implementation/migration task. Rollback disables new activations; active kernel
runs stay pinned or stop safely, never fallback into legacy execution and repeat
calls. Offline shadow decisions may use immutable synthetic outcomes, never paid
double execution or writing new classifications into historical runs.

## 13. Testing strategy and acceptance gates

No tests were run for this documentation-only task; below are implementation gates,
not achieved results. Existing PRF evidence is background, not proof of new kernel.

1. Pure reducer/ledger tests: finite transitions, nonnegative capacity, reservations,
   initial 6+reserve 2, every retry charged, no counter reset, downstream reserve.
2. Integrated synthetic X: six empty, zero Evidence, two viable distinct remaining
   opportunities -> attempt 7 then 8 if needed, never 9; no early zero-yield failure.
   Variants: no viable opportunity, no search/fetch budget, all gaps close at 7,
   cross-only at 7 and target still open, assessment budget absent, initial<6.
3. Meaningful adaptation: same query reworded rejected; same candidates/new URL
   aliases do not refresh strategy; a new allowed source/aspect is considered;
   legitimate geographic retrieval-arm differences remain distinguishable.
4. W/C/E/G/I/K/P/U invariants: temporal/relevance/geography unknowns, target vs cross,
   lineage independence, valid-empty vs invalid, dedup, query intent, conservative
   sufficiency; multiple unrelated domains, not UK-EV string fixtures only.
5. Telemetry enabled/disabled/capped/error equality, redaction and explainability.
6. PG/worker/API fault injection: crash before/after reservation/dispatch/result,
   duplicate callbacks, stale lease holder, ambiguous timeout, atomic result refs,
   restored counters, owner isolation, version pinning and rollback.
7. Primitive parity then canonical offline suite at implementation closure;
   affected integration paths actually executed, skips reported separately.
8. Only after offline/integration gates: separately authorized bounded live
   acceptance. Higher yield is not guaranteed and cannot replace integrity gates.

## 14. Implementation phases

1. Contracts/state/reducer plus fake ports and X-shaped fixtures. Gate: deterministic
   transitions, meaningful novelty, zero-yield reachability, no product activation.
2. Durable ledger/dispatch fencing and adapter budget mapping. Gate: crash/retry
   tests and numeric equivalence to prior effective authorized envelopes.
3. Desk primitive adapters and opt-in kernel executor, existing sufficiency/downstream
   gate retained. Gate: parity where intended; explicit tested behavior differences,
   telemetry invariance and current integrity regressions.
4. Method-conformance test kit, offline full/integration closure and deployment
   rollback proof. Gate: all mandatory checks pass, no hidden paid work.
5. Separately approved live evaluation of a new versioned run; no PRF history replay.

Risks: extraction primitives currently contain loops; opaque retries invalidate
ledger proofs; lexical relevance/geography signals remain imperfect; conservative
unknowns may reduce yield; schema-less state still needs concurrency guarantees;
overly strict novelty may discard useful work. Mitigate via small adapters,
explicit contracts and adversarial fixtures, not scope/threshold relaxation.

## 15. Non-goals and delivery

No product implementation, migration, provider call, live run, Docker operation,
historical DB audit/rewrite, new research question, search-budget increase, generic
multi-agent framework, billing gateway, new authentication, renderer/UI redesign,
cross-method synthesis or implementation of future methodologies. No research
success promise. PRF-08 remains closed.

Only this architecture document changes. Baseline tracked/index clean; existing
untracked acceptance artifacts preserved. Validation: source/record traceability,
decision consistency, scope/secret review and Git whitespace check; no executable
behavior changed. Intended local commit: `ARK-01 design adaptive research kernel`.
No push.
