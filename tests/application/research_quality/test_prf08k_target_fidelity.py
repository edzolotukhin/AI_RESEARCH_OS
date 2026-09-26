"""Deterministic PRF-08J reproduction; no providers or historical data."""
import unittest
from dataclasses import replace
from unittest.mock import Mock

from application.evidence.lineage_identity import canonical_lineage_identity
from application.research_quality.deterministic_sufficiency_evaluator import _independent_lineages
from application.execution.execution_budget_context import execution_budget_scope, get_execution_budget
from application.execution.budget_utils import EVIDENCE_PURPOSE_INITIAL, EVIDENCE_PURPOSE_REMEDIATION
from application.research_quality.targeted_research_runner import TargetedResearchIterationResult
from domain.planning.research_design import ResearchDesign, ResearchQuestion, InformationNeed
from domain.research_quality.sufficiency_status import SufficiencyStatus
from tests.application.research_quality.test_targeted_research_loop import (
    _context, _build_service, _seed_evidence, _need_assessment, _result_for_needs,
    StaticSufficiencyEvaluator,
)
from tests.application.research_quality.test_prf08i_evidence_aware_continuation import _lowcost_budget
from tests.application.research_quality.test_prf08c_research_integrity import _evidence
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository


def design():
    return ResearchDesign(id="synthetic-k", research_questions=tuple(
        ResearchQuestion(id=f"RQ{i}", question=f"Question {i}") for i in (1,3,4,5)),
        information_needs=tuple(InformationNeed(id=f"IN{i}", research_question_id=f"RQ{i}", description=f"Need {i}") for i in (1,3,4,5)))


class BudgetedEvaluator:
    def __init__(self, initial_calls=4):
        self.calls = 0
        self.initial_calls = initial_calls

    def evaluate(self, *, design, evidence):
        budget = get_execution_budget()
        for _ in range(self.initial_calls if self.calls == 0 else 2):
            budget.assert_can_call("sufficiency")
            budget.record_llm_call("sufficiency")
        self.calls += 1
        result = _result_for_needs(*(
            _need_assessment(need_id=n.id, rq_id=n.research_question_id,
                status=SufficiencyStatus.SUFFICIENT if any(n.id in e.information_need_refs for e in evidence) else SufficiencyStatus.MISSING)
            for n in design.information_needs))
        return StaticSufficiencyEvaluator(result).evaluate(design=design, evidence=evidence)


class Runner:
    def __init__(self, repo, cross=True):
        self.repo, self.cross, self.targets = repo, cross, []

    def run(self, context, request):
        budget = get_execution_budget()
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        self.targets.append(request.information_need_id)
        needs = ("IN1", "IN5") if self.cross and len(self.targets) == 1 else (request.information_need_id,)
        for need in needs:
            _seed_evidence(self.repo, context, need_id=need, research_question_id=need.replace("IN", "RQ"), evidence_id=f"new-{len(self.targets)}-{need}")
        return TargetedResearchIterationResult(source_ids=(), evidence_ids=tuple(f"new-{len(self.targets)}-{n}" for n in needs), queries_executed=1, sources_acquired=0, evidence_extracted=len(needs))


class ContinuationTests(unittest.TestCase):
    def execute(self, cross=True, consumed=6):
        ctx = _context(design=design())
        repo = InMemoryEvidenceRepository()
        for n in ("IN1", "IN5"):
            _seed_evidence(repo, ctx, need_id=n, research_question_id=n.replace("IN", "RQ"), evidence_id=f"old-{n}")
        budget = _lowcost_budget()
        for _ in range(6):
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_INITIAL)
        for _ in range(consumed - 6):
            budget.record_llm_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)
        evaluator, runner = BudgetedEvaluator(4 if cross else 2), Runner(repo, cross)
        with execution_budget_scope(budget):
            result = _build_service(evaluator, evidence_repository=repo, runner=runner,
                                    max_rounds=1, max_attempts_per_gap=1).assess_and_apply(ctx)
        return ctx, repo, budget, evaluator, runner, result

    def test_j_pattern_uses_remaining_slot_for_in4_without_spending_on_cross_gains(self):
        ctx, repo, budget, evaluator, runner, result = self.execute()
        self.assertEqual(runner.targets, ["IN3", "IN4"])
        self.assertEqual(evaluator.calls, 2)  # initial + final, not after incidental gains
        self.assertEqual(budget.stage_calls("evidence"), 8)
        self.assertEqual(budget.stage_calls("sufficiency"), 6)
        self.assertFalse(result.ready_for_analysis)
        history = ctx.read_shared("research_loop_state")["history"]
        self.assertFalse(history[0]["improved"])
        diag = history[0]["remediation_attempt_diagnostics"]
        self.assertTrue(diag["cross_need_reassessment_deferred"])
        self.assertEqual(diag["target_qualifying_delta"], 0)
        items = repo.list_for_project(ctx.project.id, workflow_run_id=ctx.workflow_run.id)
        self.assertEqual(sum("IN3" in e.information_need_refs for e in items), 0)
        self.assertEqual(sum("IN4" in e.information_need_refs for e in items), 1)
        self.assertEqual(sum("IN1" in e.information_need_refs for e in items), 2)
        self.assertEqual(sum("IN5" in e.information_need_refs for e in items), 2)

    def test_exhausted_evidence_budget_never_starts_another_attempt(self):
        _, _, budget, _, runner, result = self.execute(consumed=8)
        self.assertEqual(runner.targets, [])
        self.assertEqual(budget.stage_calls("evidence"), 8)
        self.assertFalse(result.ready_for_analysis)

    def test_all_gaps_closed_stops_normally_within_same_eight_call_cap(self):
        _, _, budget, _, runner, result = self.execute(cross=False)
        self.assertEqual(runner.targets, ["IN3", "IN4"])
        self.assertTrue(result.ready_for_analysis)
        self.assertEqual(budget.stage_calls("evidence"), 8)

    def test_last_slot_cross_evidence_does_not_produce_false_readiness(self):
        ctx, _, budget, _, runner, result = self.execute(consumed=7)
        self.assertEqual(runner.targets, ["IN3"])
        self.assertFalse(result.ready_for_analysis)
        self.assertFalse(ctx.read_shared("research_loop_state")["history"][0]["improved"])
        self.assertEqual(budget.stage_calls("evidence"), 8)


class ExtractionFocusTests(unittest.TestCase):
    def test_real_extraction_path_receives_target_keeps_cross_need_evidence(self):
        from application.evidence.evidence_extraction_service import EvidenceExtractionService
        from infrastructure.evidence.llm_evidence_extractor import LlmEvidenceExtractor
        from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
        from domain.ai.llm_response import LLMResponse
        from domain.sources.source import Source
        import json
        ctx = _context(design=design())
        sources, evidence = InMemorySourceRepository(), InMemoryEvidenceRepository()
        sources.create(Source(id="s", project_id=ctx.project.id, url="https://example.test/s", canonical_url="https://example.test/s", title="Synthetic", retrieved_at="2026-01-01T00:00:00Z", content_text="Cross need fact exists.", content_checksum="synthetic", workflow_run_refs=(ctx.workflow_run.id,), research_design_refs=(design().id,), information_need_refs=("IN1", "IN3", "IN5"), research_question_refs=("RQ1", "RQ3", "RQ5")))
        llm = Mock()
        llm.generate.return_value = LLMResponse(content=json.dumps({"items":[{"statement":"Cross need fact exists.","source_excerpt":"Cross need fact exists.","information_need_id":"IN1","evidence_type":"direct_excerpt","confidence":0.8}]}))
        service = EvidenceExtractionService(source_repository=sources, evidence_repository=evidence, evidence_extractor=LlmEvidenceExtractor(llm_client=llm))
        summary = service.extract_for_source_ids(ctx, ("s",), allow_empty=True, target_information_need_id="IN3")
        prompt = llm.generate.call_args.args[0]
        self.assertIn("target_information_need_id: IN3", prompt.user)
        self.assertIn("do not repair the target", prompt.system)
        self.assertEqual(summary.diagnostics.work_items[0].primary_need_id, "IN3")
        saved = evidence.list_for_project(ctx.project.id, workflow_run_id=ctx.workflow_run.id)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].information_need_refs, ("IN1",))
        llm.reset_mock()
        empty = service.extract_for_source_ids(ctx, ("s",), allow_empty=True, target_information_need_id="IN4")
        self.assertEqual(empty.evidence_extracted, 0)
        llm.generate.assert_not_called()


class LineageTests(unittest.TestCase):
    def item(self, index, origin, basis=None):
        item = _evidence(str(index), f"s{index}", "June 2026", origin=origin)
        if basis is not None:
            item.metadata["data_lineage"]["basis_excerpt"] = basis
        return item

    def test_grounded_upstream_aliases_count_once_generic_not_brand_rule(self):
        for provider in ("Zapmap", "Example Registry"):
            origin = f"Statistics Office, sourced from {provider}"
            a = self.item(1, origin, f"Source: {origin}")
            b = self.item(2, provider)
            self.assertEqual(len(_independent_lineages((a,b))[0]), 1)

    def test_case_whitespace_unicode_width_are_harmless(self):
        self.assertEqual(canonical_lineage_identity({"status":"established", "origin_id":"  ＡＣＭＥ   Data "}), "acme data")

    def test_similar_names_and_distinct_datasets_remain_distinct(self):
        items = tuple(self.item(i, n) for i,n in enumerate(("Acme", "Acme Labs", "Acme Dataset A", "Acme Dataset B")))
        self.assertEqual(len(_independent_lineages(items)[0]), 4)

    def test_unsubstantiated_relationship_is_not_an_alias(self):
        item = self.item(1, "Office, sourced from Registry", "Unrelated text")
        self.assertNotEqual(canonical_lineage_identity(item.metadata["data_lineage"]), "registry")

    def test_unknown_does_not_add_independence_to_known_origin(self):
        known = self.item(1, "Registry")
        unknown = self.item(2, None)
        ids, warnings = _independent_lineages((known,unknown))
        self.assertEqual(len(ids), 1)
        self.assertTrue(warnings)
        self.assertEqual(canonical_lineage_identity({"status":"unknown", "origin_id":"Registry"}), "")

    def test_old_semantic_cache_is_not_reused_under_new_lineage_rule(self):
        from application.research_quality.sufficiency_assessment_cache import SufficiencyAssessmentCache
        from application.research_quality.sufficiency_assessment_fingerprint import SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION
        self.assertEqual(SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION, "prf-08k.1")
        cache = SufficiencyAssessmentCache()
        cache.entries["IN1"] = {"contract_version":"prf-08c.1", "fingerprint":"old", "assessment":_need_assessment(need_id="IN1", rq_id="RQ1", status=SufficiencyStatus.SUFFICIENT).to_dict()}
        self.assertIsNone(cache.lookup("IN1", "old"))


if __name__ == "__main__":
    unittest.main()
