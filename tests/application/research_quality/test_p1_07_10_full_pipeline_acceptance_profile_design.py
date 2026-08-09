"""P1-07.10 offline design contracts for full-pipeline acceptance profiles.

DESIGN / OFFLINE ONLY. Does not implement compose overlays or change production.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_quality.sufficiency_status import SufficiencyStatus
from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate

from application.config import ApplicationConfig
from application.execution.exceptions import BudgetExhaustedError
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    _current_stage,
    set_execution_stage,
)
from application.research_quality.gap_scheduler import select_next_actionable_gap
from application.research_quality.production_targeted_research_runner import (
    ProductionTargetedResearchRunner,
)
from application.research_quality.readiness_aggregation import (
    build_information_need_assessment,
    build_research_readiness_assessment,
    build_research_readiness_result,
)
from application.sources.source_acquisition_service import (
    SourceAcquisitionService,
    _PendingCandidate,
)
from application.sources.source_budget import SourceAcquisitionBudget
from domain.research_quality.deterministic_sufficiency_signals import (
    DeterministicSufficiencySignals,
)
from domain.research_quality.semantic_sufficiency_assessment import (
    SemanticSufficiencyAssessment,
)
from domain.research_quality.targeted_research_request import TargetedResearchRequest

REPO_ROOT = Path(__file__).resolve().parents[3]

SERBIA_INFORMATION_NEEDS = 12
SERBIA_RESEARCH_QUESTIONS = 6
PLANNER_WORST_CASE_CALLS = 9

LOWCOST_SOURCE_MAX_SOURCES_PER_RUN = 5
LOWCOST_EVIDENCE_MAX_LLM_CALLS = 8
LOWCOST_SUFFICIENCY_MAX_LLM_CALLS = 6
LOWCOST_ANALYSIS_MAX_LLM_CALLS = 2
LOWCOST_REPORT_MAX_LLM_CALLS = 2
LOWCOST_REVIEW_MAX_CALLS = 1
LOWCOST_LLM_MAX_CALLS_PER_RUN = 24


@dataclass(frozen=True)
class AcceptanceProfile:
    name: str
    source_max_candidates_per_query: int
    source_max_candidates_per_information_need: int
    source_max_sources_per_run: int
    source_min_successful_sources: int
    source_min_information_need_coverage_ratio: float
    evidence_max_llm_calls: int
    sufficiency_max_llm_calls: int
    analysis_max_llm_calls: int
    report_max_llm_calls: int
    review_max_calls: int
    llm_max_calls_per_run: int
    evidence_max_items_per_source: int
    research_max_gap_rounds_per_run: int
    targeted_max_attempts_per_gap: int
    targeted_max_queries_per_gap: int
    targeted_max_sources_per_gap: int
    intended_targeted_reevals: int


PROFILE_A = AcceptanceProfile(
    name="minimal_expansion",
    source_max_candidates_per_query=3,
    source_max_candidates_per_information_need=3,
    source_max_sources_per_run=12,
    source_min_successful_sources=3,
    source_min_information_need_coverage_ratio=1.0,
    evidence_max_llm_calls=20,
    sufficiency_max_llm_calls=24,
    analysis_max_llm_calls=8,
    report_max_llm_calls=10,
    review_max_calls=1,
    llm_max_calls_per_run=80,
    evidence_max_items_per_source=2,
    research_max_gap_rounds_per_run=1,
    targeted_max_attempts_per_gap=1,
    targeted_max_queries_per_gap=1,
    targeted_max_sources_per_gap=1,
    intended_targeted_reevals=1,
)

PROFILE_B = AcceptanceProfile(
    name="balanced_full_pipeline",
    source_max_candidates_per_query=3,
    source_max_candidates_per_information_need=3,
    source_max_sources_per_run=18,
    source_min_successful_sources=3,
    source_min_information_need_coverage_ratio=1.0,
    evidence_max_llm_calls=36,
    sufficiency_max_llm_calls=36,
    analysis_max_llm_calls=10,
    report_max_llm_calls=12,
    review_max_calls=3,
    llm_max_calls_per_run=120,
    evidence_max_items_per_source=2,
    research_max_gap_rounds_per_run=2,
    targeted_max_attempts_per_gap=2,
    targeted_max_queries_per_gap=1,
    targeted_max_sources_per_gap=1,
    intended_targeted_reevals=2,
)

PROFILE_C = AcceptanceProfile(
    name="high_confidence",
    source_max_candidates_per_query=5,
    source_max_candidates_per_information_need=5,
    source_max_sources_per_run=24,
    source_min_successful_sources=3,
    source_min_information_need_coverage_ratio=1.0,
    evidence_max_llm_calls=48,
    sufficiency_max_llm_calls=48,
    analysis_max_llm_calls=14,
    report_max_llm_calls=20,
    review_max_calls=7,
    llm_max_calls_per_run=160,
    evidence_max_items_per_source=50,
    research_max_gap_rounds_per_run=2,
    targeted_max_attempts_per_gap=2,
    targeted_max_queries_per_gap=2,
    targeted_max_sources_per_gap=2,
    intended_targeted_reevals=3,
)

RECOMMENDED_PROFILE = PROFILE_B


def _stage_sum(profile: AcceptanceProfile) -> int:
    return (
        profile.evidence_max_llm_calls
        + profile.sufficiency_max_llm_calls
        + profile.analysis_max_llm_calls
        + profile.report_max_llm_calls
        + profile.review_max_calls
    )


def _controlled_envelope(profile: AcceptanceProfile) -> int:
    return PLANNER_WORST_CASE_CALLS + _stage_sum(profile)


def _budget_for(profile: AcceptanceProfile) -> ExecutionBudget:
    return ExecutionBudget(
        evidence_max_llm_calls=profile.evidence_max_llm_calls,
        sufficiency_max_llm_calls=profile.sufficiency_max_llm_calls,
        analysis_max_llm_calls=profile.analysis_max_llm_calls,
        report_max_llm_calls=profile.report_max_llm_calls,
        review_max_llm_calls=profile.review_max_calls,
        llm_max_calls_per_run=profile.llm_max_calls_per_run,
    )


def _signals(need_id: str, *, count: int) -> DeterministicSufficiencySignals:
    source_count = 1 if count else 0
    return DeterministicSufficiencySignals(
        information_need_id=need_id,
        research_question_id="RQ1",
        evidence_count=count,
        independent_source_count=source_count,
        evidence_ids=tuple(f"e-{need_id}-{index}" for index in range(count)),
        source_ids=tuple(f"src-{need_id}" for _ in range(source_count)),
    )


def _semantic(status: SufficiencyStatus) -> SemanticSufficiencyAssessment:
    return SemanticSufficiencyAssessment(
        status=status,
        confidence=0.7,
        missing_aspects=(),
        gap_types=(),
        search_directives=(),
        reason="offline design snapshot",
    )


def _gap(need_id: str, rq_id: str = "RQ1") -> TargetedResearchRequest:
    return TargetedResearchRequest(
        workflow_run_id="run-1",
        research_design_id="design-1",
        research_question_id=rq_id,
        information_need_id=need_id,
        gap_types=(),
        missing_aspects=(),
        search_directives=(),
        attempt=1,
        existing_source_ids=(),
        existing_evidence_ids=(),
    )


class LowcostAndDefaultInvariantTests(unittest.TestCase):
    def test_lowcost_compose_unchanged(self) -> None:
        compose = (REPO_ROOT / "docker-compose.lowcost.yml").read_text(encoding="utf-8")
        self.assertIn(f'SOURCE_MAX_SOURCES_PER_RUN: "{LOWCOST_SOURCE_MAX_SOURCES_PER_RUN}"', compose)
        self.assertIn(f'EVIDENCE_MAX_LLM_CALLS: "{LOWCOST_EVIDENCE_MAX_LLM_CALLS}"', compose)
        self.assertIn(
            f'SUFFICIENCY_MAX_LLM_CALLS: "{LOWCOST_SUFFICIENCY_MAX_LLM_CALLS}"',
            compose,
        )
        self.assertIn(f'ANALYSIS_MAX_LLM_CALLS: "{LOWCOST_ANALYSIS_MAX_LLM_CALLS}"', compose)
        self.assertIn(f'REPORT_MAX_LLM_CALLS: "{LOWCOST_REPORT_MAX_LLM_CALLS}"', compose)
        self.assertIn(f'REVIEW_MAX_CALLS: "{LOWCOST_REVIEW_MAX_CALLS}"', compose)
        self.assertIn(f'LLM_MAX_CALLS_PER_RUN: "{LOWCOST_LLM_MAX_CALLS_PER_RUN}"', compose)
        self.assertIn('EVIDENCE_MAX_ITEMS_PER_SOURCE: "2"', compose)
        self.assertIn('RESEARCH_MAX_GAP_ROUNDS_PER_RUN: "1"', compose)
        self.assertIn('SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO: "1.0"', compose)

    def test_acceptance_overlay_aliases_remain_unimplemented(self) -> None:
        # P1-07.10.1 implements the designed filename; alternate aliases stay unused.
        self.assertTrue(
            (REPO_ROOT / "docker-compose.full-pipeline-acceptance.yml").exists(),
        )
        self.assertFalse((REPO_ROOT / "docker-compose.acceptance.yml").exists())
        self.assertFalse((REPO_ROOT / "docker-compose.full-e2e.yml").exists())

    def test_product_defaults_not_reduced_to_lowcost(self) -> None:
        config = ApplicationConfig()
        self.assertEqual(config.source_max_sources_per_run, 30)
        self.assertEqual(config.evidence_max_llm_calls, 50)
        self.assertEqual(config.sufficiency_max_llm_calls, 20)
        self.assertEqual(config.analysis_max_llm_calls, 14)
        self.assertEqual(config.report_max_llm_calls, 20)
        self.assertEqual(config.review_max_calls, 7)
        self.assertEqual(config.llm_max_calls_per_run, 100)
        self.assertEqual(config.source_min_information_need_coverage_ratio, 1.0)


class ProfileEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._budget_token = _current_budget.set(None)
        self._stage_token = _current_stage.set(None)
        self.addCleanup(_current_budget.reset, self._budget_token)
        self.addCleanup(_current_stage.reset, self._stage_token)

    def test_recommended_profile_is_balanced_b(self) -> None:
        self.assertEqual(RECOMMENDED_PROFILE.name, "balanced_full_pipeline")
        self.assertEqual(RECOMMENDED_PROFILE, PROFILE_B)

    def test_profiles_monotone_on_primary_knobs(self) -> None:
        self.assertLess(PROFILE_A.source_max_sources_per_run, PROFILE_B.source_max_sources_per_run)
        self.assertLess(PROFILE_B.source_max_sources_per_run, PROFILE_C.source_max_sources_per_run)
        self.assertLess(PROFILE_A.evidence_max_llm_calls, PROFILE_B.evidence_max_llm_calls)
        self.assertLess(PROFILE_B.evidence_max_llm_calls, PROFILE_C.evidence_max_llm_calls)
        self.assertLess(PROFILE_A.sufficiency_max_llm_calls, PROFILE_B.sufficiency_max_llm_calls)
        self.assertLess(PROFILE_B.sufficiency_max_llm_calls, PROFILE_C.sufficiency_max_llm_calls)
        self.assertLess(PROFILE_A.llm_max_calls_per_run, PROFILE_B.llm_max_calls_per_run)
        self.assertLess(PROFILE_B.llm_max_calls_per_run, PROFILE_C.llm_max_calls_per_run)

    def test_no_profile_weakens_coverage_ratio_or_min_successful_sources(self) -> None:
        for profile in (PROFILE_A, PROFILE_B, PROFILE_C):
            self.assertEqual(profile.source_min_information_need_coverage_ratio, 1.0)
            self.assertEqual(profile.source_min_successful_sources, 3)

    def test_global_cap_exceeds_controlled_stage_envelope(self) -> None:
        for profile in (PROFILE_A, PROFILE_B, PROFILE_C):
            envelope = _controlled_envelope(profile)
            self.assertGreaterEqual(
                profile.llm_max_calls_per_run,
                envelope,
                msg=f"{profile.name}: global {profile.llm_max_calls_per_run} < envelope {envelope}",
            )

    def test_evidence_stage_cap_usable_under_downstream_reserve(self) -> None:
        for profile in (PROFILE_A, PROFILE_B, PROFILE_C):
            budget = _budget_for(profile)
            set_execution_stage("planner")
            for _ in range(PLANNER_WORST_CASE_CALLS):
                budget.assert_can_call("planner")
                budget.record_llm_call("planner")
            set_execution_stage("evidence")
            for _ in range(profile.evidence_max_llm_calls):
                budget.assert_can_call("evidence")
                budget.record_llm_call("evidence")
            self.assertTrue(budget.stage_cap_reached("evidence"))
            self.assertFalse(budget.exhausted)
            with self.assertRaises(BudgetExhaustedError) as ctx:
                budget.assert_can_call("evidence")
            self.assertEqual(ctx.exception.reason, "evidence_max_llm_calls")

    def test_sufficiency_cap_covers_intended_reeval_formula(self) -> None:
        for profile in (PROFILE_A, PROFILE_B, PROFILE_C):
            required = SERBIA_INFORMATION_NEEDS * (1 + profile.intended_targeted_reevals)
            self.assertGreaterEqual(
                profile.sufficiency_max_llm_calls,
                required,
                msg=f"{profile.name}: sufficiency {profile.sufficiency_max_llm_calls} < {required}",
            )

    def test_evidence_cap_covers_first_chunk_plus_targeted_reserve(self) -> None:
        first_chunks = SERBIA_INFORMATION_NEEDS
        targeted_reserve = {
            PROFILE_A.name: 8,
            PROFILE_B.name: 12,
            PROFILE_C.name: 24,
        }
        for profile in (PROFILE_A, PROFILE_B, PROFILE_C):
            lower_bound = first_chunks + targeted_reserve[profile.name]
            self.assertGreaterEqual(profile.evidence_max_llm_calls, first_chunks)
            self.assertGreaterEqual(profile.evidence_max_llm_calls, lower_bound)

    def test_analysis_and_report_exceed_lowcost_because_of_rq_batching(self) -> None:
        analysis_happy_path = SERBIA_RESEARCH_QUESTIONS + 1
        report_happy_path = SERBIA_RESEARCH_QUESTIONS + 1
        self.assertGreater(analysis_happy_path, LOWCOST_ANALYSIS_MAX_LLM_CALLS)
        self.assertGreater(report_happy_path, LOWCOST_REPORT_MAX_LLM_CALLS)
        for profile in (PROFILE_A, PROFILE_B, PROFILE_C):
            self.assertGreaterEqual(profile.analysis_max_llm_calls, analysis_happy_path)
            self.assertGreaterEqual(profile.report_max_llm_calls, report_happy_path)

    def test_relative_call_multiplier_vs_lowcost(self) -> None:
        self.assertEqual(PROFILE_B.llm_max_calls_per_run / LOWCOST_LLM_MAX_CALLS_PER_RUN, 5.0)
        self.assertEqual(PROFILE_B.evidence_max_llm_calls / LOWCOST_EVIDENCE_MAX_LLM_CALLS, 4.5)
        self.assertEqual(PROFILE_B.sufficiency_max_llm_calls / LOWCOST_SUFFICIENCY_MAX_LLM_CALLS, 6.0)
        self.assertEqual(
            PROFILE_B.source_max_sources_per_run / LOWCOST_SOURCE_MAX_SOURCES_PER_RUN,
            3.6,
        )


class SearchSchedulerSemanticsTests(unittest.TestCase):
    def test_source_cap_is_unique_url_group_index_not_success_count(self) -> None:
        source = inspect.getsource(SourceAcquisitionService._acquire_candidates)
        self.assertIn("index >= source_group_limit", source)
        self.assertIn("skipped_budget += 1", source)
        self.assertIn("attempted += 1", source)
        self.assertIn("is_successful_acquisition", source)

    def test_prioritize_groups_is_coverage_then_rank_not_need_round_robin(self) -> None:
        def _item(url: str, need_id: str, rank: int) -> _PendingCandidate:
            query = SearchQuery(
                id=f"sq-{need_id}",
                research_question_id="RQ1",
                information_need_id=need_id,
                query_text=f"query for {need_id}",
            )
            candidate = SourceCandidate(
                provider="tavily",
                url=url,
                title=need_id,
                snippet="",
                query_id=query.id,
                rank=rank,
            )
            return _PendingCandidate(candidate=candidate, query=query, canonical_url=url)

        grouped = {
            "https://high-rank-need-a.example/a": [_item("https://high-rank-need-a.example/a", "IN12", 1)],
            "https://low-rank-need-b.example/b": [_item("https://low-rank-need-b.example/b", "IN1", 9)],
            "https://overlap.example/c": [
                _item("https://overlap.example/c", "IN4", 4),
                _item("https://overlap.example/c", "IN7", 5),
            ],
        }
        ordered = SourceAcquisitionService._prioritize_groups(grouped)
        self.assertEqual(ordered[0].canonical_url, "https://overlap.example/c")
        self.assertEqual(ordered[1].canonical_url, "https://high-rank-need-a.example/a")
        self.assertEqual(ordered[2].canonical_url, "https://low-rank-need-b.example/b")

    def test_information_need_priority_not_used_in_acquisition_sort(self) -> None:
        source = inspect.getsource(SourceAcquisitionService._prioritize_groups)
        self.assertIn("need_coverage", source)
        self.assertIn("best_rank", source)
        self.assertNotIn("priority", source)

    def test_coverage_ratio_is_early_stop_target_not_hard_gate(self) -> None:
        design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(id="RQ1", question="Q?", objective_refs=()),
            ),
            information_needs=tuple(
                InformationNeed(
                    id=f"IN{index}",
                    research_question_id="RQ1",
                    description=f"Need {index}",
                )
                for index in range(1, 13)
            ),
        )
        service = SourceAcquisitionService(
            search_provider=Mock(),
            source_retriever=Mock(),
            source_repository=Mock(),
            budget=SourceAcquisitionBudget(
                min_information_need_coverage_ratio=1.0,
                min_successful_sources=3,
            ),
        )
        covered_three = {f"IN{index}" for index in (4, 7, 9)}
        self.assertFalse(
            service._coverage_target_satisfied(design, covered_three, set()),
        )
        all_needs = {f"IN{index}" for index in range(1, 13)}
        self.assertTrue(service._coverage_target_satisfied(design, all_needs, set()))
        acquire_source = inspect.getsource(SourceAcquisitionService._acquire_candidates)
        self.assertIn("coverage_complete_early_stop", acquire_source)
        self.assertIn("min_successful_sources", acquire_source)


class EvidenceAndTargetedBudgetTests(unittest.TestCase):
    def test_targeted_runner_shares_evidence_extract_path(self) -> None:
        source = inspect.getsource(ProductionTargetedResearchRunner.run)
        self.assertIn("extract_for_source_ids", source)
        self.assertIn("acquire_targeted_queries", source)

    def test_evidence_max_items_per_source_not_enforced_in_extractors(self) -> None:
        extraction = (
            REPO_ROOT / "application" / "evidence" / "evidence_extraction_service.py"
        ).read_text(encoding="utf-8")
        extractor = (
            REPO_ROOT / "infrastructure" / "evidence" / "llm_evidence_extractor.py"
        ).read_text(encoding="utf-8")
        budget = (REPO_ROOT / "application" / "execution" / "execution_budget.py").read_text(
            encoding="utf-8",
        )
        self.assertNotIn("evidence_max_items_per_source", extraction)
        self.assertNotIn("max_items_per_source", extraction)
        self.assertNotIn("evidence_max_items_per_source", extractor)
        self.assertIn("evidence_max_items_per_source", budget)
        tree = ast.parse(budget)
        attrs = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("evidence_max_items_per_source", attrs)

    def test_one_round_can_service_multiple_distinct_gaps(self) -> None:
        gaps = (_gap("IN1"), _gap("IN2"), _gap("IN3"))
        first = select_next_actionable_gap(
            gaps,
            gap_attempt_counts={},
            stalled_need_ids=set(),
            max_attempts_per_gap=1,
        )
        self.assertIsNotNone(first)
        assert first is not None
        second = select_next_actionable_gap(
            gaps,
            gap_attempt_counts={first.information_need_id: 1},
            stalled_need_ids=set(),
            max_attempts_per_gap=1,
        )
        self.assertIsNotNone(second)
        assert second is not None
        self.assertNotEqual(first.information_need_id, second.information_need_id)


class ReadinessSemanticsUnchangedTests(unittest.TestCase):
    def test_all_information_needs_still_required(self) -> None:
        assessments = []
        for index in range(1, 13):
            status = (
                SufficiencyStatus.SUFFICIENT if index != 10 else SufficiencyStatus.MISSING
            )
            count = 2 if status == SufficiencyStatus.SUFFICIENT else 0
            assessments.append(
                build_information_need_assessment(
                    signals=_signals(f"IN{index}", count=count),
                    semantic=(
                        _semantic(SufficiencyStatus.SUFFICIENT)
                        if count
                        else None
                    ),
                ),
            )
        rq = build_research_readiness_assessment(
            research_question_id="RQ1",
            need_assessments=tuple(assessments),
        )
        result = build_research_readiness_result((rq,))
        self.assertFalse(result.ready_for_analysis)
        self.assertIn("IN10", result.blocking_information_need_ids)

    def test_twelve_sufficient_needs_are_ready(self) -> None:
        assessments = tuple(
            build_information_need_assessment(
                signals=_signals(f"IN{index}", count=2),
                semantic=_semantic(SufficiencyStatus.SUFFICIENT),
            )
            for index in range(1, 13)
        )
        rq = build_research_readiness_assessment(
            research_question_id="RQ1",
            need_assessments=assessments,
        )
        result = build_research_readiness_result((rq,))
        self.assertTrue(result.ready_for_analysis)


if __name__ == "__main__":
    unittest.main()
