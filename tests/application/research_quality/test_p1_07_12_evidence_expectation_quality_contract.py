"""P1-07.12 EvidenceExpectation quality-contract integration."""

from __future__ import annotations

import ast
import copy
import inspect
import json
import unittest
from pathlib import Path

from agents.planner.planner_agent import PlannerAgent
from application.exceptions.planner_parser_error import PlannerParserError
from application.execution.budget_utils import (
    EVIDENCE_INITIAL_PARTITION_REASON,
    EVIDENCE_PURPOSE_REMEDIATION,
)
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.planner.design_service import PlannerDesignServiceImpl
from application.planner.deterministic_design_response import (
    build_deterministic_design_response,
)
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from application.research_quality.allowed_aspect_ids import resolve_allowed_aspect_ids
from application.research_quality.hybrid_sufficiency_evaluator import (
    HybridResearchSufficiencyEvaluator,
)
from application.research_quality.readiness_aggregation import (
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.research_quality.sufficiency_assessment_cache import (
    SufficiencyAssessmentCache,
    _current_cache,
    clear_sufficiency_assessment_cache,
)
from application.research_quality.sufficiency_assessment_fingerprint import (
    build_sufficiency_assessment_fingerprint,
)
from application.structured_output.correction_prompt import (
    RESEARCH_DESIGN_PAYLOAD_SCHEMA,
)
from application.structured_output.parser import StructuredOutputParser
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.gap_type import GapType
from domain.research_quality.information_need_assessment import (
    QUALITY_CONTRACT_EXPLICIT,
    QUALITY_CONTRACT_LEGACY,
    InformationNeedAssessment,
)
from domain.research_quality.semantic_decision_normalizer import LEGACY_NEED_ASPECT_ID
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.workflow_run import WorkflowRun
from infrastructure.research_quality.llm_semantic_sufficiency_assessor import (
    _build_user_payload,
    _system_prompt,
)
from runtime.workflow_context import WorkflowContext

from tests.application.research_quality.test_hybrid_sufficiency_evaluator import (
    RecordingSemanticAssessor,
    _evidence,
    _semantic,
)
from tests.application.research_quality.test_p1_07_10_1_full_pipeline_acceptance_profile import (
    LOWCOST_PATH,
    OVERLAY_PATH,
    PROFILE_B_WORKER,
)
from tests.fixtures.planner_responses import (
    LEGACY_RESEARCH_DESIGN_WITHOUT_EXPECTATION,
    VALID_RESEARCH_DESIGN_JSON,
    VALID_RESEARCH_DESIGN_RESPONSE,
    planner_evidence_expectation,
)
from tests.fixtures.research_brief import sample_research_brief
from tests.helpers.executor_catalog import make_test_executor_catalog
from application.prompts.builders.planner_prompt_builder import PlannerPromptBuilder
from application.prompts.file_template_loader import FileTemplateLoader
from application.prompts.python_format_prompt_renderer import PythonFormatPromptRenderer

REPO_ROOT = Path(__file__).resolve().parents[3]


def _bind_cache(cache: SufficiencyAssessmentCache | None = None) -> SufficiencyAssessmentCache:
    resolved = cache or SufficiencyAssessmentCache()
    _current_cache.set(resolved)
    return resolved


def _parse_design(payload: dict) -> ResearchDesign:
    dto = ResearchDesignParser().parse(payload)
    return ResearchDesignFactory().create(dto)


def _need_with_expectation(
    *,
    need_id: str = "in-1",
    rq_id: str = "rq-1",
    description: str = "Need in-1",
    aspects: tuple[str, ...] = ("market_size", "growth_rate"),
) -> InformationNeed:
    return InformationNeed(
        id=need_id,
        research_question_id=rq_id,
        description=description,
        evidence_expectation=EvidenceExpectation(
            nature=EvidenceNature.MIXED,
            required_aspects=aspects,
        ),
    )


def _design_with_expectation(
    *,
    aspects: tuple[str, ...] = ("market_size", "growth_rate"),
    extra_needs: tuple[InformationNeed, ...] = (),
) -> ResearchDesign:
    needs = (
        _need_with_expectation(aspects=aspects),
        *extra_needs,
    )
    return ResearchDesign(
        id="design-1",
        research_questions=(
            ResearchQuestion(id="rq-1", question="What is the market?", objective_refs=()),
        ),
        information_needs=needs,
    )


class PlannerQualityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ResearchDesignParser()
        self.factory = ResearchDesignFactory()
        self.contract = ResearchDesignPayloadContract()

    def test_new_planned_need_receives_explicit_expectation(self) -> None:
        design = _parse_design(VALID_RESEARCH_DESIGN_RESPONSE)
        need = design.information_needs[0]
        self.assertIsNotNone(need.evidence_expectation)
        assert need.evidence_expectation is not None
        self.assertTrue(need.evidence_expectation.required_aspects)
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, need.evidence_expectation.required_aspects)

    def test_all_new_planned_needs_receive_expectation(self) -> None:
        design = _parse_design(VALID_RESEARCH_DESIGN_RESPONSE)
        self.assertGreaterEqual(len(design.information_needs), 1)
        for need in design.information_needs:
            self.assertIsNotNone(need.evidence_expectation)
            assert need.evidence_expectation is not None
            self.assertTrue(need.evidence_expectation.required_aspects)

    def test_malformed_expectation_does_not_become_empty_valid(self) -> None:
        payload = StructuredOutputParser().parse(VALID_RESEARCH_DESIGN_JSON)
        cases = (
            None,
            {},
            {"nature": "mixed", "required_aspects": []},
            {"nature": "mixed"},
            {"required_aspects": ["market_size"]},
            {"nature": "unknown", "required_aspects": ["market_size"]},
            {"nature": "mixed", "required_aspects": [""]},
        )
        for malformed in cases:
            with self.subTest(malformed=malformed):
                mutated = copy.deepcopy(payload)
                mutated["information_needs"][0]["evidence_expectation"] = malformed
                with self.assertRaises(PlannerParserError):
                    self.parser.parse(mutated)
                self.assertFalse(self.contract.accepts(mutated))

    def test_missing_expectation_is_rejected_by_planner_contract(self) -> None:
        payload = copy.deepcopy(VALID_RESEARCH_DESIGN_RESPONSE)
        del payload["information_needs"][0]["evidence_expectation"]
        with self.assertRaises(PlannerParserError):
            self.parser.parse(payload)
        self.assertFalse(self.contract.accepts(payload))

    def test_serialization_round_trip_preserves_expectation(self) -> None:
        design = _parse_design(VALID_RESEARCH_DESIGN_RESPONSE)
        restored = ResearchDesign.from_dict(design.to_dict())
        assert restored is not None
        self.assertEqual(restored.information_needs[0].evidence_expectation, design.information_needs[0].evidence_expectation)
        self.assertEqual(restored, design)

    def test_legacy_serialized_design_without_expectation_still_loads(self) -> None:
        design = ResearchDesign.from_dict(
            {"id": "legacy-design", **LEGACY_RESEARCH_DESIGN_WITHOUT_EXPECTATION},
        )
        assert design is not None
        self.assertTrue(
            all(need.evidence_expectation is None for need in design.information_needs),
        )

    def test_planner_schema_and_prompts_require_expectation(self) -> None:
        self.assertIn("evidence_expectation", RESEARCH_DESIGN_PAYLOAD_SCHEMA)
        self.assertIn("required_aspects", RESEARCH_DESIGN_PAYLOAD_SCHEMA)
        system = (
            REPO_ROOT / "application" / "prompts" / "templates" / "planner" / "system.md"
        ).read_text(encoding="utf-8")
        user = (
            REPO_ROOT / "application" / "prompts" / "templates" / "planner" / "user.md"
        ).read_text(encoding="utf-8")
        self.assertIn("evidence_expectation", system)
        self.assertIn("required_aspects", system)
        self.assertIn("evidence_expectation", user)

    def test_deterministic_planner_output_includes_expectation(self) -> None:
        brief = sample_research_brief(
            objectives=["Identify competitors."],
            geography=["France"],
            timeframe="2024-2025",
        )
        project = Project(id="p1", name="Test")
        project.research_brief = brief
        prompt = PlannerPromptBuilder(
            template_loader=FileTemplateLoader(),
            prompt_renderer=PythonFormatPromptRenderer(),
            executor_catalog=make_test_executor_catalog(),
        ).build(WorkflowContext(workflow_run=WorkflowRun(id="plan"), project=project))
        payload = json.loads(build_deterministic_design_response(prompt))
        self.assertTrue(self.contract.accepts(payload))
        design = PlannerDesignServiceImpl(
            response_parser=ResearchDesignParser(),
            design_factory=ResearchDesignFactory(),
        ).create_design(project, payload)
        for need in design.information_needs:
            self.assertIsNotNone(need.evidence_expectation)


class SemanticSufficiencyQualityContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sufficiency_assessment_cache()

    def test_explicit_expectation_reaches_semantic_assessor(self) -> None:
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design_with_expectation()
        result = evaluator.evaluate(
            design=design,
            evidence=(_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),),
        )
        self.assertEqual(len(semantic.calls), 1)
        need = semantic.calls[0]["information_need"]
        self.assertIsNotNone(need.evidence_expectation)
        allowed = resolve_allowed_aspect_ids(need)
        self.assertEqual(allowed, ("market_size", "growth_rate"))
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, allowed)
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.quality_contract_mode, QUALITY_CONTRACT_EXPLICIT)
        self.assertEqual(assessment.required_aspect_ids, ("market_size", "growth_rate"))

        prompt = _system_prompt(allowed_aspect_ids=allowed)
        self.assertNotIn("Legacy mode", prompt)
        user = _build_user_payload(
            research_question=design.research_questions[0],
            information_need=design.information_needs[0],
            evidence=(_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),),
            deterministic_signals=semantic.calls[0]["deterministic_signals"],
            allowed_aspect_ids=allowed,
        )
        body = json.loads(user)
        self.assertIn("evidence_expectation", body["information_need"])
        self.assertEqual(
            body["allowed_aspect_ids"],
            ["market_size", "growth_rate"],
        )

    def test_required_aspect_missing_is_insufficient(self) -> None:
        semantic = RecordingSemanticAssessor(
            default=_semantic(
                status=SufficiencyStatus.INSUFFICIENT,
                missing_aspects=("growth_rate",),
                gap_types=(GapType.INSUFFICIENT_DEPTH,),
                search_directives=("growth_rate",),
            ),
        )
        result = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic).evaluate(
            design=_design_with_expectation(),
            evidence=(_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),),
        )
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertEqual(assessment.missing_aspects, ("growth_rate",))
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, assessment.missing_aspects)
        self.assertFalse(result.ready_for_analysis)

    def test_required_aspects_satisfied_may_be_sufficient(self) -> None:
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.SUFFICIENT),
        )
        result = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic).evaluate(
            design=_design_with_expectation(),
            evidence=(_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),),
        )
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.status, SufficiencyStatus.SUFFICIENT)
        self.assertEqual(assessment.quality_contract_mode, QUALITY_CONTRACT_EXPLICIT)
        self.assertTrue(result.ready_for_analysis)

    def test_high_evidence_count_does_not_override_missing_aspect(self) -> None:
        semantic = RecordingSemanticAssessor(
            default=_semantic(
                status=SufficiencyStatus.INSUFFICIENT,
                missing_aspects=("growth_rate",),
                gap_types=(GapType.INSUFFICIENT_DEPTH,),
                search_directives=("growth_rate",),
            ),
        )
        evidence = tuple(
            _evidence(
                evidence_id=f"ev-{index}",
                information_need_refs=("in-1",),
                source_id=f"source-{index}",
            )
            for index in range(20)
        )
        result = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic).evaluate(
            design=_design_with_expectation(),
            evidence=evidence,
        )
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.evidence_count, 20)
        self.assertEqual(assessment.status, SufficiencyStatus.INSUFFICIENT)
        self.assertEqual(assessment.missing_aspects, ("growth_rate",))
        self.assertFalse(result.ready_for_analysis)

    def test_zero_evidence_remains_missing_without_sufficiency_llm(self) -> None:
        semantic = RecordingSemanticAssessor()
        result = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic).evaluate(
            design=_design_with_expectation(),
            evidence=(),
        )
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.status, SufficiencyStatus.MISSING)
        self.assertEqual(assessment.evidence_count, 0)
        self.assertEqual(len(semantic.calls), 0)
        self.assertEqual(assessment.quality_contract_mode, QUALITY_CONTRACT_EXPLICIT)
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, assessment.required_aspect_ids)

    def test_explicit_expectation_path_does_not_emit_legacy_need(self) -> None:
        from application.research_quality.raw_semantic_decision_contract import (
            render_allowed_aspect_contract,
        )

        need = _need_with_expectation()
        allowed = resolve_allowed_aspect_ids(need)
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, allowed)
        scoped = render_allowed_aspect_contract(allowed_aspect_ids=allowed)
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, scoped)
        self.assertNotIn("Legacy mode", scoped)
        user = _build_user_payload(
            research_question=ResearchQuestion(
                id="rq-1",
                question="What is the market?",
                objective_refs=(),
            ),
            information_need=need,
            evidence=(_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),),
            deterministic_signals=DeterministicSufficiencySignals(
                information_need_id=need.id,
                research_question_id=need.research_question_id,
                evidence_count=1,
                independent_source_count=1,
                evidence_ids=("ev-1",),
                source_ids=("source-1",),
            ),
            allowed_aspect_ids=allowed,
        )
        self.assertNotIn(LEGACY_NEED_ASPECT_ID, user)

    def test_legacy_no_expectation_still_uses_legacy_need(self) -> None:
        need = InformationNeed(
            id="in-legacy",
            research_question_id="rq-1",
            description="Legacy need",
        )
        allowed = resolve_allowed_aspect_ids(need)
        self.assertEqual(allowed, (LEGACY_NEED_ASPECT_ID,))
        semantic = RecordingSemanticAssessor(
            default=_semantic(
                status=SufficiencyStatus.INSUFFICIENT,
                missing_aspects=(LEGACY_NEED_ASPECT_ID,),
                gap_types=(GapType.INSUFFICIENT_DEPTH,),
                search_directives=(LEGACY_NEED_ASPECT_ID,),
            ),
        )
        design = ResearchDesign(
            id="legacy",
            research_questions=(
                ResearchQuestion(id="rq-1", question="Q?", objective_refs=()),
            ),
            information_needs=(need,),
        )
        result = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic).evaluate(
            design=design,
            evidence=(_evidence(evidence_id="ev-1", information_need_refs=("in-legacy",)),),
        )
        assessment = result.research_question_assessments[0].information_need_assessments[0]
        self.assertEqual(assessment.quality_contract_mode, QUALITY_CONTRACT_LEGACY)
        self.assertEqual(assessment.required_aspect_ids, (LEGACY_NEED_ASPECT_ID,))
        self.assertEqual(assessment.missing_aspects, (LEGACY_NEED_ASPECT_ID,))


class IncrementalSufficiencyExpectationTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sufficiency_assessment_cache()

    def test_same_expectation_and_evidence_reuses_cache(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design_with_expectation()
        evidence = (_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),)
        first = evaluator.evaluate(design=design, evidence=evidence)
        second = evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(semantic.calls), 1)
        self.assertEqual(cache.reused_assessments, 1)
        self.assertEqual(
            first.research_question_assessments[0].information_need_assessments[0].status,
            second.research_question_assessments[0].information_need_assessments[0].status,
        )

    def test_expectation_change_changes_fingerprint_and_reassesses(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        evidence = (_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),)
        design_a = _design_with_expectation(aspects=("market_size",))
        design_b = _design_with_expectation(aspects=("growth_rate",))
        rq = design_a.research_questions[0]
        fp_a = build_sufficiency_assessment_fingerprint(
            information_need=design_a.information_needs[0],
            research_question=rq,
            evidence_ids=("ev-1",),
            evidence_by_id={evidence[0].id: evidence[0]},
            max_evidence_items=10,
        )
        fp_b = build_sufficiency_assessment_fingerprint(
            information_need=design_b.information_needs[0],
            research_question=rq,
            evidence_ids=("ev-1",),
            evidence_by_id={evidence[0].id: evidence[0]},
            max_evidence_items=10,
        )
        self.assertNotEqual(fp_a, fp_b)
        evaluator.evaluate(design=design_a, evidence=evidence)
        evaluator.evaluate(design=design_b, evidence=evidence)
        self.assertEqual(len(semantic.calls), 2)
        self.assertEqual(cache.reassessed_fingerprint_changed, 1)

    def test_evidence_change_reassesses(self) -> None:
        _bind_cache()
        semantic = RecordingSemanticAssessor()
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design_with_expectation()
        ev1 = _evidence(evidence_id="ev-1", information_need_refs=("in-1",))
        ev2 = _evidence(evidence_id="ev-2", information_need_refs=("in-1",))
        evaluator.evaluate(design=design, evidence=(ev1,))
        evaluator.evaluate(design=design, evidence=(ev1, ev2))
        self.assertEqual(len(semantic.calls), 2)

    def test_reorder_only_evidence_does_not_change_fingerprint(self) -> None:
        design = _design_with_expectation()
        need = design.information_needs[0]
        rq = design.research_questions[0]
        ev1 = _evidence(evidence_id="b-id", information_need_refs=("in-1",))
        ev2 = _evidence(evidence_id="a-id", information_need_refs=("in-1",))
        by_id = {ev1.id: ev1, ev2.id: ev2}
        left = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=rq,
            evidence_ids=(ev1.id, ev2.id),
            evidence_by_id=by_id,
            max_evidence_items=10,
        )
        right = build_sufficiency_assessment_fingerprint(
            information_need=need,
            research_question=rq,
            evidence_ids=(ev2.id, ev1.id),
            evidence_by_id=by_id,
            max_evidence_items=10,
        )
        self.assertEqual(left, right)
        source = inspect.getsource(build_sufficiency_assessment_fingerprint)
        self.assertNotIn("return hash(", source)
        self.assertNotIn("hash(payload", source)


class ReadinessIntegrityTests(unittest.TestCase):
    def test_one_insufficient_explicit_expectation_in_blocks_rq(self) -> None:
        sufficient = InformationNeedAssessment(
            information_need_id="in-1",
            research_question_id="rq-1",
            status=SufficiencyStatus.SUFFICIENT,
            evidence_count=2,
            quality_contract_mode=QUALITY_CONTRACT_EXPLICIT,
            required_aspect_ids=("market_size",),
        )
        insufficient = InformationNeedAssessment(
            information_need_id="in-2",
            research_question_id="rq-1",
            status=SufficiencyStatus.INSUFFICIENT,
            evidence_count=4,
            missing_aspects=("growth_rate",),
            gap_types=(GapType.INSUFFICIENT_DEPTH,),
            quality_contract_mode=QUALITY_CONTRACT_EXPLICIT,
            required_aspect_ids=("market_size", "growth_rate"),
        )
        rq = build_research_readiness_assessment(
            research_question_id="rq-1",
            need_assessments=(sufficient, insufficient),
        )
        self.assertFalse(rq.ready_for_analysis)
        self.assertIn("in-2", rq.blocking_information_need_ids)

    def test_one_blocking_rq_keeps_run_not_ready(self) -> None:
        ready_rq = build_research_readiness_assessment(
            research_question_id="rq-1",
            need_assessments=(
                InformationNeedAssessment(
                    information_need_id="in-1",
                    research_question_id="rq-1",
                    status=SufficiencyStatus.SUFFICIENT,
                    evidence_count=1,
                    quality_contract_mode=QUALITY_CONTRACT_EXPLICIT,
                    required_aspect_ids=("a",),
                ),
            ),
        )
        blocked_rq = build_research_readiness_assessment(
            research_question_id="rq-2",
            need_assessments=(
                InformationNeedAssessment(
                    information_need_id="in-2",
                    research_question_id="rq-2",
                    status=SufficiencyStatus.MISSING,
                    evidence_count=0,
                    gap_types=(GapType.NO_EVIDENCE,),
                    quality_contract_mode=QUALITY_CONTRACT_EXPLICIT,
                    required_aspect_ids=("b",),
                ),
            ),
        )
        result = build_research_readiness_result((ready_rq, blocked_rq))
        self.assertFalse(result.ready_for_analysis)
        self.assertIn("rq-2", result.blocking_research_question_ids)

    def test_all_in_sufficient_remains_required(self) -> None:
        assessments = tuple(
            InformationNeedAssessment(
                information_need_id=f"in-{index}",
                research_question_id="rq-1",
                status=SufficiencyStatus.SUFFICIENT,
                evidence_count=1,
                quality_contract_mode=QUALITY_CONTRACT_EXPLICIT,
                required_aspect_ids=("aspect",),
            )
            for index in range(1, 12)
        ) + (
            InformationNeedAssessment(
                information_need_id="in-12",
                research_question_id="rq-1",
                status=SufficiencyStatus.INSUFFICIENT,
                evidence_count=20,
                missing_aspects=("missing_aspect",),
                gap_types=(GapType.INSUFFICIENT_DEPTH,),
                quality_contract_mode=QUALITY_CONTRACT_EXPLICIT,
                required_aspect_ids=("missing_aspect",),
            ),
        )
        result = build_research_readiness_result(
            (
                build_research_readiness_assessment(
                    research_question_id="rq-1",
                    need_assessments=assessments,
                ),
            ),
        )
        self.assertFalse(result.ready_for_analysis)
        self.assertIn("in-12", result.blocking_information_need_ids)

    def test_legacy_assessment_payload_without_quality_contract_fields_loads(self) -> None:
        restored = InformationNeedAssessment.from_dict(
            {
                "information_need_id": "in-1",
                "research_question_id": "rq-1",
                "status": "insufficient",
                "evidence_count": 2,
                "missing_aspects": [LEGACY_NEED_ASPECT_ID],
                "gap_types": ["insufficient_depth"],
                "reason": "legacy snapshot",
            },
        )
        self.assertEqual(restored.quality_contract_mode, "")
        self.assertEqual(restored.required_aspect_ids, ())


class ProfileRegressionTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_sufficiency_assessment_cache()

    def test_profile_b_caps_unchanged_from_p1_07_11(self) -> None:
        overlay = OVERLAY_PATH.read_text(encoding="utf-8")
        for key, value in PROFILE_B_WORKER.items():
            self.assertIn(f'{key}: "{value}"', overlay)
        self.assertEqual(PROFILE_B_WORKER["EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS"], "6")
        self.assertEqual(PROFILE_B_WORKER["EVIDENCE_MAX_LLM_CALLS"], "36")
        self.assertEqual(PROFILE_B_WORKER["LLM_MAX_CALLS_PER_RUN"], "120")

    def test_lowcost_unchanged(self) -> None:
        lowcost = LOWCOST_PATH.read_text(encoding="utf-8")
        self.assertIn('LLM_MAX_CALLS_PER_RUN: "24"', lowcost)
        self.assertIn('EVIDENCE_MAX_LLM_CALLS: "8"', lowcost)
        self.assertIn('SUFFICIENCY_MAX_LLM_CALLS: "6"', lowcost)
        self.assertIn('ANALYSIS_MAX_LLM_CALLS: "2"', lowcost)
        self.assertIn('REPORT_MAX_LLM_CALLS: "2"', lowcost)
        self.assertIn('REVIEW_MAX_CALLS: "1"', lowcost)
        self.assertNotIn("EVIDENCE_REMEDIATION_RESERVED_LLM_CALLS", lowcost)

    def test_no_additional_expectation_generation_llm_stage(self) -> None:
        source = inspect.getsource(PlannerAgent.run)
        self.assertEqual(source.count("self._structured_output_generator.generate("), 1)
        tree = ast.parse(
            inspect.getsource(PlannerDesignServiceImpl),
            filename="design_service.py",
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"generate", "complete", "chat"}
        ]
        self.assertEqual(calls, [])

    def test_property_a_initial_cannot_consume_remediation_reserve(self) -> None:
        budget = ExecutionBudget(
            evidence_max_llm_calls=36,
            evidence_remediation_reserved_llm_calls=6,
        )
        self.assertEqual(budget.evidence_initial_allowance, 30)
        for _ in range(30):
            budget.assert_can_call("evidence")
            budget.record_llm_call("evidence")
        with self.assertRaises(BudgetExhaustedError) as ctx:
            budget.assert_can_call("evidence")
        self.assertEqual(ctx.exception.reason, EVIDENCE_INITIAL_PARTITION_REASON)
        budget.assert_can_call("evidence", purpose=EVIDENCE_PURPOSE_REMEDIATION)

    def test_property_b_unchanged_inputs_reuse_assessment(self) -> None:
        cache = _bind_cache()
        semantic = RecordingSemanticAssessor(
            default=_semantic(status=SufficiencyStatus.INSUFFICIENT),
        )
        evaluator = HybridResearchSufficiencyEvaluator(semantic_assessor=semantic)
        design = _design_with_expectation()
        evidence = (_evidence(evidence_id="ev-1", information_need_refs=("in-1",)),)
        evaluator.evaluate(design=design, evidence=evidence)
        evaluator.evaluate(design=design, evidence=evidence)
        self.assertEqual(len(semantic.calls), 1)
        self.assertEqual(cache.reused_assessments, 1)


if __name__ == "__main__":
    unittest.main()
