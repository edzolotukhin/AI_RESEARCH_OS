"""Desk policy translation; canonical services alone qualify Evidence/readiness."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
import time

from application.evidence.temporal_scope import qualifying_evidence
from application.execution.execution_budget_context import (
    execution_stage_scope, get_evidence_call_purpose, set_evidence_call_purpose,
)
from application.research_kernel.contracts import Action, Gap, Observation, Outcome, OutcomeKind, KernelState, Stop
from application.research_kernel.ledger import Ledger
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from application.sources.content_identity import acquired_content_identity
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from application.research_quality.terminal_state_reconciliation import reconcile_terminal_readiness
from application.research_quality.sufficiency_assessment_cache import SHARED_SUFFICIENCY_CACHE_KEY

FRONTIER = "ark_desk_frontier_v1"
ASSESSMENT = "ark_desk_assessment_v1"


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class DeskAdapter:
    method_id = "desk-v1"

    def __init__(self, context, config, primitives, readiness, evidence_repository):
        self.context, self.config, self.primitives = context, config, primitives
        self.readiness, self.evidence = readiness, evidence_repository
        self.design = context.workflow_template.research_design_snapshot
        self.queries = {q.id: q for q in primitives.initial_queries()}
        self.items, self.groups = {}, {}
        self.last_result = None
        self.state = None
        context.shared_state.setdefault("ark_acquisition_deadline", time.time() + config.source_acquisition_max_seconds)

    def initial_state(self):
        c = self.config
        total = c.evidence_max_llm_calls
        reserve = min(total, c.evidence_remediation_reserved_llm_calls)
        gap_attempts = min(c.research_max_gap_rounds_per_run, c.targeted_max_attempts_per_gap)
        continuation_paths = len(self.design.information_needs) * gap_attempts
        limits = {"decisions": max(32, 4 * (len(self.queries) + c.source_max_sources_per_run + total)),
            "extractions": total, "initial": total - reserve, "continuation": reserve,
            "search": len(self.queries), "acquisitions": c.source_max_sources_per_run + continuation_paths * c.targeted_max_sources_per_gap,
            "initial_acquisitions": c.source_max_sources_per_run,
            "continuation_acquisitions": continuation_paths * c.targeted_max_sources_per_gap,
            "assessments": c.sufficiency_max_llm_calls, "retries": total + c.sufficiency_max_llm_calls,
            "initial_llm": max(0, c.llm_max_calls_per_run - c.sufficiency_max_llm_calls - c.analysis_max_llm_calls - c.report_max_llm_calls - c.review_max_calls),
            "llm": max(0, c.llm_max_calls_per_run - c.analysis_max_llm_calls - c.report_max_llm_calls - c.review_max_calls)}
        limits.update({"logical:gap:" + n.id: gap_attempts for n in self.design.information_needs})
        limits.update({"fetch:gap:" + n.id: gap_attempts * c.targeted_max_sources_per_gap for n in self.design.information_needs})
        frozen = {"owner": self.context.project.owner_principal_id,
            "brief": self.context.workflow_template.research_brief_snapshot.to_dict() if self.context.workflow_template.research_brief_snapshot else None,
            "design": self.design.to_dict(), "limits": limits}
        return KernelState(self.context.workflow_run.id, self.method_id, fingerprint(frozen), limits)

    def checkpoint(self):
        checkpoint = self.context.services.get(CHECKPOINT_SERVICE_KEY)
        if checkpoint is None or not callable(getattr(checkpoint, "on_task_progress", None)):
            raise RuntimeError("ARK Desk requires a durable workflow checkpoint")
        checkpoint.on_task_progress(self.context)

    def qualified(self):
        return qualifying_evidence(design=self.design,
            source_repository=self.primitives.extraction._source_repository,
            evidence=self.evidence.list_for_project(self.context.project.id, workflow_run_id=self.context.workflow_run.id),
            brief=self.context.workflow_template.research_brief_snapshot)

    def observe(self, state):
        self.state = state
        evidence = self.qualified()
        digest = fingerprint([e.to_dict() for e in evidence])
        saved = self.context.shared_state.get(ASSESSMENT, {})
        if saved.get("fingerprint") == digest:
            result = ResearchReadinessResult.from_dict(saved["result"])
        else:
            prior = (ResearchReadinessResult.from_dict(saved["result"]) if saved.get("result") else
                     DeterministicResearchSufficiencyEvaluator().evaluate(design=self.design, evidence=()))
            result = reconcile_terminal_readiness(design=self.design, evidence=evidence, previous=prior,
                cache_payload=self.context.shared_state.get(SHARED_SUFFICIENCY_CACHE_KEY))
        self.last_result = result
        counts = Counter(need for e in evidence for need in e.information_need_refs)
        gaps = tuple(Gap(n.information_need_id, n.status.value, index,
                        counts[n.information_need_id], tuple(n.missing_aspects))
                     for rq in result.research_question_assessments
                     for index, n in enumerate(rq.information_need_assessments)
                     if n.information_need_id in result.blocking_information_need_ids)
        ready = saved.get("fingerprint") == digest and result.ready_for_analysis
        return Observation(digest, gaps, ready, not ready and time.time() >= self.context.shared_state["ark_acquisition_deadline"])

    def _action(self, kind, target, key, reason, resources, rank, refs=()):
        identifier = kind + ":" + fingerprint(key)
        return Action(identifier, kind, target, identifier, reason, tuple(resources.items()), rank, refs)

    def propose(self, state, observation):
        ledger = Ledger(state)
        actions = []
        # The active phase is bounded by every resource needed to execute it.
        # Once its dedicated LLM allowance is exhausted, nominal extraction
        # slots cannot keep continuation capacity stranded.
        initial = ledger.remaining("initial") > 0 and ledger.remaining("initial_llm") > 0
        phase = "initial" if initial else "continuation"
        # Semantic assessment is explicit paid work, never hidden in observe.
        if self.qualified() and ledger.remaining("assessments") > 0:
            actions.append(self._action("assess", "", observation.fingerprint, "changed_evidence",
                {"assessments": 1, "llm": 1, "retries": 0}, (-1,), (observation.fingerprint,)))
        if ledger.remaining("extractions") <= 0 or ledger.remaining(phase) <= 0:
            return tuple(actions)
        counts = {g.need_id: g.qualifying_count for g in observation.gaps}
        acquisition_open = time.time() < self.context.shared_state["ark_acquisition_deadline"]
        def path_fits(target):
            # Single-flight ownership means no competing action can consume
            # this feasible path while search is in flight. The paid search
            # itself is reserved durably; each later step is reserved in turn.
            required = {"acquisitions": 1, phase + "_acquisitions": 1,
                        "extractions": 1, phase: 1, "llm": 1, "decisions": 3}
            if not initial:
                required.update({"logical:gap:" + target: 1, "fetch:gap:" + target: 1})
            return acquisition_open and all(ledger.remaining(k) >= v for k, v in required.items())
        # Finite approved retrieval arms: query wording changes never create a
        # new strategy. Identity is need + arm + immutable scoped input.
        for q in self.queries.values():
            if q.information_need_id not in counts:
                continue
            key = (q.information_need_id, str(q.retrieval_arm), q.geography, q.timeframe, q.preferred_source_types)
            if path_fits(q.information_need_id):
                actions.append(self._action("search", q.information_need_id, key, "untried_retrieval_arm",
                    {"search": 1}, (0 if initial else 3, counts[q.information_need_id]), (q.id,)))
        rows = self.context.shared_state.get(FRONTIER, [])
        for index, group in enumerate(self.primitives.groups(rows, self.queries)):
            target = group.decision.information_need_id if group.decision else group.items[0].query.information_need_id
            if target not in counts or not path_fits(target):
                continue
            key = group.canonical_url
            action = self._action("acquire", target, key, "untried_eligible_candidate",
                {"acquisitions": 1, phase + "_acquisitions": 1, **({"fetch:gap:" + target: 1} if not initial else {})},
                (1 if initial else 2, counts[target], index))
            self.groups[action.id] = group
            actions.append(action)
        prior = {decision["action"] for decision in state.decisions}
        for index, item in enumerate(self.primitives.work_items(counts)):
            targets = [n for n in item.run_context.information_need_ids if n in counts]
            if not targets:
                continue
            target = min(targets, key=lambda n: (counts[n], n))
            # Content identity, original offsets and supported target prevent a
            # URL alias or phase change from buying the identical work again.
            key = (acquired_content_identity(item.source), target,
                   item.chunk.original_normalized_start, item.chunk.original_normalized_end)
            resources = {"extractions": 1, phase: 1, "llm": 1, "retries": 0}
            if initial:
                resources["initial_llm"] = 1
            if not initial:
                resources["logical:gap:" + target] = 1
            action = self._action("extract", target, key, "untried_scoped_content", resources,
                (2 if initial else 0, int(not item.source_first_attempt),
                 counts[target] if item.source_first_attempt else 0, index), (phase, item.source.id))
            if not initial and self.config.evidence_remediation_max_llm_calls_per_attempt:
                action = replace(action, max_attempts=self.config.evidence_remediation_max_llm_calls_per_attempt)
            self.items[action.id] = item
            if action.id not in prior:
                actions.append(action)
        return tuple(sorted((a for a in actions if a.strategy_key not in state.attempted_strategies),
                            key=lambda a: (a.rank, a.id))[:state.limits["decisions"]])

    def execute(self, action):
        c = self.context
        if action.kind == "search":
            rows = self.primitives.search(c, self.queries[action.refs[0]])
            c.shared_state.setdefault(FRONTIER, []).extend(rows)
            outcome = Outcome(OutcomeKind.EMPTY, reason="search_completed")
        elif action.kind == "acquire":
            ids = self.primitives.acquire(c, self.groups[action.id])
            outcome = Outcome(OutcomeKind.EMPTY if ids else OutcomeKind.ACQUISITION_FAILED, refs=ids, reason="acquisition_completed")
        elif action.kind == "extract":
            before = {e.id for e in self.qualified()}
            purpose = get_evidence_call_purpose()
            set_evidence_call_purpose("initial" if action.refs[0] == "initial" else "remediation")
            try:
                with execution_stage_scope("evidence"):
                    summary = self.primitives.extract(c, self.items[action.id],
                        action.target if action.refs[0] == "continuation" else None)
            finally:
                set_evidence_call_purpose(purpose)
            # Do not copy arbitrary provider exception text into durable state.
            c.shared_state.setdefault("ark_extraction_diagnostics", []).append({
                "evidence_ids": list(summary.evidence_ids),
                "evidence_extracted": summary.evidence_extracted,
                "extraction_failures": summary.extraction_failures,
                "raw_candidates": summary.diagnostics.raw_candidates,
                "failure_classification": summary.diagnostics.failure_classification,
                "budget_stop": summary.diagnostics.budget_stop,
            })
            new = [e for e in self.qualified() if e.id not in before]
            target = sum(action.target in e.information_need_refs for e in new)
            cross = sum(action.target not in e.information_need_refs for e in new)
            kind = OutcomeKind.TARGET if target else OutcomeKind.CROSS if cross else OutcomeKind.EMPTY
            if not new and (summary.diagnostics.extractor_failures or summary.diagnostics.inner_calls_exception):
                kind = OutcomeKind.INVALID
            elif not new and (summary.evidence_extracted or summary.diagnostics.raw_candidates):
                kind = OutcomeKind.DUPLICATE if summary.diagnostics.dedup_hits == summary.diagnostics.raw_candidates and summary.diagnostics.raw_candidates else OutcomeKind.REJECTED
            elif not new and not (summary.diagnostics.work_items and all(
                    self.primitives.extraction._trace_is_valid_empty(t) for t in summary.diagnostics.work_items)):
                kind = OutcomeKind.INVALID
            outcome = Outcome(kind, tuple(summary.evidence_ids), target, cross, "canonical_extraction")
        elif action.kind == "assess":
            with execution_stage_scope("sufficiency"):
                result = self.readiness.evaluate_for_context(c)
            c.shared_state[ASSESSMENT] = {"fingerprint": action.refs[0], "result": result.to_dict()}
            outcome = Outcome(OutcomeKind.EMPTY, reason="canonical_assessment")
        else:
            raise ValueError("unsupported Desk action")
        self.checkpoint()  # Result refs/frontier durable before kernel completion.
        return outcome

    def validate(self, action, outcome):
        return outcome  # Existing canonical services validated persisted results.

    def finish(self, state):
        if state.terminal in (Stop.RECONCILIATION, Stop.TECHNICAL, Stop.SAFETY):
            raise RuntimeError("ARK stopped for reconciliation or technical safety")
        self.observe(state)
        result = self.readiness._finalize_terminal_readiness(self.context, self.last_result)
        if state.terminal != Stop.READY and result.ready_for_analysis:
            raise RuntimeError("ARK handoff lacks a current ready verdict")
        if not result.ready_for_analysis:
            self.readiness._gate.apply_not_ready(self.context)
        self.readiness._persist(self.context, result, None)
        self.context.shared_state["ark_stop"] = state.terminal.value
        self.checkpoint()
        return result
