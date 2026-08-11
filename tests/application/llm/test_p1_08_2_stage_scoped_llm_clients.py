"""P1-08.2 stage-scoped LLM client composition offline acceptance."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.ai.prompt import Prompt
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_verdict import ReviewVerdict

from application.analysis.provenance_validation import (
    validate_finding_candidate,
    validate_insight_candidate,
)
from application.config import ApplicationConfig, ApplicationOverrides
from application.execution.execution_budget import ExecutionBudget
from application.execution.execution_budget_context import (
    _current_budget,
    set_execution_stage,
)
from application.llm.stage_llm_clients import (
    LlmClientCompositionError,
    describe_llm_client,
    resolve_stage_llm_clients,
    unwrap_llm_client,
)
from application.ports.analysis_ports import (
    AnalysisInput,
    FindingCandidate,
    InsightCandidate,
)
from application.ports.report_ports import ReportInput
from application.ports.review_ports import SemanticReviewInput
from application.research_quality.deterministic_research_sufficiency_evaluator import (
    DeterministicResearchSufficiencyEvaluator,
)
from application.review.review_support_context import build_review_support_context
from infrastructure.analysis.llm_analysis_engine import LlmAnalysisEngine
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.llm.deterministic_llm_client import DeterministicLLMClient
from infrastructure.llm.openai_client import OpenAIClient
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from infrastructure.review.deterministic_review_engine import (
    build_rq_batch_inputs,
    build_section_inputs,
)
from infrastructure.review.llm_review_engine import LlmReviewEngine

from tests.fixtures.p1_08_claim_grade_fixture import (
    EVIDENCE_IDS,
    claim_grade_brief,
    claim_grade_design,
    claim_grade_evidence,
)


class _SpyLLMClient:
    def __init__(self, *, name: str, content: str) -> None:
        self.name = name
        self.content = content
        self.calls = 0
        self.prompts: list[Prompt] = []

    def generate(self, prompt: Prompt, *, options=None) -> LLMResponse:
        self.calls += 1
        self.prompts.append(prompt)
        return LLMResponse(content=self.content, output_tokens=8)


class StageScopedLlmClientCompositionTests(unittest.TestCase):
    def test_case1_default_uses_openai_for_all_stages(self) -> None:
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            environ={},
        )
        for stage in (
            clients.planner,
            clients.analysis,
            clients.report,
            clients.review,
            clients.evidence,
        ):
            self.assertIsInstance(stage, BudgetEnforcingLLMClient)
            self.assertIsInstance(unwrap_llm_client(stage), OpenAIClient)

    def test_case2_deterministic_planner_isolates_downstream(self) -> None:
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        self.assertIsInstance(unwrap_llm_client(clients.planner), DeterministicLLMClient)
        for stage in (clients.analysis, clients.report, clients.review, clients.evidence):
            self.assertIsInstance(unwrap_llm_client(stage), OpenAIClient)
            self.assertNotIsInstance(
                unwrap_llm_client(stage),
                DeterministicLLMClient,
            )

    def test_case3_deterministic_planner_still_returns_design_json(self) -> None:
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        response = clients.planner.generate(
            Prompt(
                system="planner",
                user=(
                    "Objectives:\n- Evaluate brand awareness.\n"
                    "Geography:\n- Germany\n"
                    "Timeframe:\n2026\n"
                    "Language:\nen\n"
                ),
            ),
        )
        payload = json.loads(response.content)
        self.assertIn("research_questions", payload)
        self.assertNotIn("findings", payload)

    def test_case4_analysis_uses_injected_stage_client(self) -> None:
        analysis_spy = _SpyLLMClient(
            name="analysis",
            content=json.dumps(
                {
                    "findings": [
                        {
                            "statement": "Aided awareness rose about 7pp.",
                            "rationale": "41% to 48% in cited surveys.",
                            "evidence_refs": [EVIDENCE_IDS[0], EVIDENCE_IDS[1]],
                            "research_question_refs": ["rq-1"],
                            "information_need_refs": ["in-rq-1"],
                            "finding_type": "synthesis",
                            "confidence": 0.8,
                        }
                    ]
                }
            ),
        )
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            ApplicationOverrides(analysis_llm_client=analysis_spy),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        self.assertIs(unwrap_llm_client(clients.analysis), analysis_spy)
        self.assertIsInstance(unwrap_llm_client(clients.planner), DeterministicLLMClient)

        engine = LlmAnalysisEngine(llm_client=clients.analysis)
        evidence = claim_grade_evidence()
        candidates = engine.analyze_findings(
            AnalysisInput(
                project_id="p",
                workflow_run_id="r",
                research_design_id="d",
                brief=claim_grade_brief(),
                design=claim_grade_design(),
                evidence_batch=evidence,
                batch_question_id="rq-1",
            )
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(analysis_spy.calls, 1)
        self.assertIn("41%", analysis_spy.prompts[0].user)

    def test_case5_report_uses_own_configured_client(self) -> None:
        report_spy = _SpyLLMClient(name="report", content='{"sections":[]}')
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            ApplicationOverrides(report_llm_client=report_spy),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        self.assertIs(unwrap_llm_client(clients.report), report_spy)
        self.assertIsInstance(unwrap_llm_client(clients.analysis), OpenAIClient)

    def test_case6_review_uses_own_client_and_support_context(self) -> None:
        review_spy = _SpyLLMClient(name="review", content='{"issues":[]}')
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            ApplicationOverrides(review_llm_client=review_spy),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        self.assertIs(unwrap_llm_client(clients.review), review_spy)

        evidence = claim_grade_evidence()
        finding = Finding(
            id="finding-1",
            project_id=evidence[0].project_id,
            workflow_run_id=evidence[0].workflow_run_id,
            research_design_id=evidence[0].research_design_id,
            statement="Brand A aided awareness increased by approximately 7pp.",
            rationale="Supported by 41% and 48% survey evidence.",
            evidence_refs=EVIDENCE_IDS[:2],
            created_at="2026-08-10T00:00:00+00:00",
            research_question_refs=("rq-1",),
            finding_type=FindingType.SYNTHESIS,
        )
        report = Report(
            id="report-1",
            project_id=evidence[0].project_id,
            workflow_run_id=evidence[0].workflow_run_id,
            research_design_id=evidence[0].research_design_id,
            title="Brand A",
            language="en",
            sections=(
                ReportSection(
                    id="section-1",
                    title="Awareness",
                    content="Aided awareness increased by approximately 7 percentage points.",
                    research_question_refs=("rq-1",),
                    finding_refs=("finding-1",),
                    evidence_refs=EVIDENCE_IDS[:2],
                    metadata={"primary_research_question_id": "rq-1"},
                ),
            ),
            executive_summary="Summary",
            limitations=(),
            created_at="2026-08-10T00:00:00+00:00",
            generation_method="test",
            finding_refs=("finding-1",),
            insight_refs=(),
            evidence_refs=EVIDENCE_IDS[:2],
            citation_registry={},
            revision_number=1,
        )
        support = build_review_support_context(
            report=report,
            findings=[finding],
            insights=[],
            evidence_items=list(evidence),
        )
        self.assertTrue(support.coverage_complete)
        engine = LlmReviewEngine(
            llm_client=clients.review,
            max_review_calls=3,
            structured_output_max_attempts=1,
        )
        review_input = SemanticReviewInput(
            project_id=evidence[0].project_id,
            workflow_run_id=evidence[0].workflow_run_id,
            research_design_id=evidence[0].research_design_id,
            report=report,
            brief_objectives=claim_grade_brief().objectives,
            research_questions=("What changed in Brand A awareness between 2024 and 2025?",),
            section_inputs=build_section_inputs(report),
            support_context=support,
        )
        issues = engine.review_report(review_input)
        self.assertIsInstance(issues, tuple)
        self.assertGreaterEqual(review_spy.calls, 1)
        joined = "\n".join(p.user for p in review_spy.prompts)
        self.assertTrue(
            "FINDING id=" in joined or "finding-1" in joined or "7" in joined,
        )

    def test_case7_and_9_no_network_and_no_planner_schema_leak(self) -> None:
        analysis_spy = _SpyLLMClient(
            name="analysis",
            content='{"findings":[]}',
        )
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            ApplicationOverrides(analysis_llm_client=analysis_spy),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        LlmAnalysisEngine(llm_client=clients.analysis).analyze_findings(
            AnalysisInput(
                project_id="p",
                workflow_run_id="r",
                research_design_id="d",
                brief=claim_grade_brief(),
                design=claim_grade_design(),
                evidence_batch=claim_grade_evidence(),
            )
        )
        user = analysis_spy.prompts[0].user
        self.assertNotIn("source_strategy", user)
        self.assertIn("evidence:", user)

    def test_case8_independent_stage_doubles(self) -> None:
        a = _SpyLLMClient(name="a", content='{"findings":[]}')
        r = _SpyLLMClient(name="r", content='{"issues":[]}')
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            ApplicationOverrides(analysis_llm_client=a, review_llm_client=r),
        )
        self.assertIs(unwrap_llm_client(clients.analysis), a)
        self.assertIs(unwrap_llm_client(clients.review), r)
        self.assertIsNot(unwrap_llm_client(clients.analysis), unwrap_llm_client(clients.review))

    def test_case10_budget_wrappers_and_shared_global_budget(self) -> None:
        analysis_spy = _SpyLLMClient(name="analysis", content="ok")
        report_spy = _SpyLLMClient(name="report", content="ok")
        review_spy = _SpyLLMClient(name="review", content="ok")
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            ApplicationOverrides(
                analysis_llm_client=analysis_spy,
                report_llm_client=report_spy,
                review_llm_client=review_spy,
            ),
        )
        for client in (clients.analysis, clients.report, clients.review):
            self.assertIsInstance(client, BudgetEnforcingLLMClient)

        budget = ExecutionBudget(
            analysis_max_llm_calls=10,
            report_max_llm_calls=12,
            review_max_llm_calls=3,
            llm_max_calls_per_run=100,
        )
        token = _current_budget.set(budget)
        try:
            set_execution_stage("analysis")
            clients.analysis.generate(Prompt(system="s", user="u"))
            set_execution_stage("report")
            clients.report.generate(Prompt(system="s", user="u"))
            set_execution_stage("review")
            clients.review.generate(Prompt(system="s", user="u"))
        finally:
            _current_budget.reset(token)

        self.assertEqual(budget.summary()["total_llm_calls"], 3)
        self.assertEqual(budget.stage_calls("analysis"), 1)
        self.assertEqual(budget.stage_calls("report"), 1)
        self.assertEqual(budget.stage_calls("review"), 1)

    def test_fail_closed_when_live_factory_returns_deterministic(self) -> None:
        from application.llm import stage_llm_clients as mod

        original = mod.create_live_llm_client
        try:
            mod.create_live_llm_client = (  # type: ignore[assignment]
                lambda config: DeterministicLLMClient()
            )
            with self.assertRaises(LlmClientCompositionError):
                resolve_stage_llm_clients(
                    ApplicationConfig(analysis_engine="llm"),
                    environ={},
                )
        finally:
            mod.create_live_llm_client = original  # type: ignore[assignment]

    def test_diagnostics_expose_concrete_client_without_secrets(self) -> None:
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        diagnostics = clients.diagnostics()
        self.assertEqual(diagnostics["planner"]["concrete_client"], "DeterministicLLMClient")
        self.assertEqual(diagnostics["analysis"]["concrete_client"], "OpenAIClient")
        self.assertNotIn("api_key", json.dumps(diagnostics).lower())
        self.assertEqual(describe_llm_client(clients.review)["classification"], "live")


class ClaimGradeDownstreamReachabilityTests(unittest.TestCase):
    def test_offline_ready_analysis_report_review_reachability(self) -> None:
        brief = claim_grade_brief()
        design = claim_grade_design()
        evidence = claim_grade_evidence()

        readiness = DeterministicResearchSufficiencyEvaluator().evaluate(
            design=design,
            evidence=evidence,
        )
        self.assertTrue(readiness.ready_for_analysis)

        analysis_response = {
            "findings": [
                {
                    "statement": (
                        "Brand A aided awareness increased by approximately "
                        "7 percentage points from 2024 to 2025."
                    ),
                    "rationale": (
                        "2024 aided awareness was 41% and 2025 was 48%."
                    ),
                    "evidence_refs": [EVIDENCE_IDS[0], EVIDENCE_IDS[1]],
                    "research_question_refs": ["rq-1"],
                    "information_need_refs": ["in-rq-1"],
                    "finding_type": "synthesis",
                    "confidence": 0.85,
                }
            ]
        }
        insight_response = {
            "insights": [
                {
                    "statement": "Brand visibility strengthened year over year.",
                    "implication": "Stronger market salience entering next cycle.",
                    "finding_refs": ["finding-aided-delta"],
                    "research_question_refs": ["rq-1"],
                    "confidence": 0.8,
                }
            ]
        }
        analysis_spy = Mock()
        analysis_spy.generate.side_effect = [
            LLMResponse(content=json.dumps(analysis_response), output_tokens=20),
            LLMResponse(content=json.dumps(insight_response), output_tokens=12),
        ]
        clients = resolve_stage_llm_clients(
            ApplicationConfig(),
            ApplicationOverrides(
                analysis_llm_client=analysis_spy,
                review_llm_client=_SpyLLMClient(
                    name="review",
                    content='{"issues":[]}',
                ),
            ),
            environ={"DETERMINISTIC_PLANNER": "1"},
        )
        self.assertIsInstance(unwrap_llm_client(clients.planner), DeterministicLLMClient)
        self.assertIs(unwrap_llm_client(clients.analysis), analysis_spy)

        analysis_engine = LlmAnalysisEngine(llm_client=clients.analysis)
        finding_candidates = analysis_engine.analyze_findings(
            AnalysisInput(
                project_id="proj-p1082-claim",
                workflow_run_id="run-p1082-claim",
                research_design_id=design.id,
                brief=brief,
                design=design,
                evidence_batch=evidence,
                batch_question_id="rq-1",
            )
        )
        evidence_by_id = {item.id: item for item in evidence}
        finding = Finding(
            id="finding-aided-delta",
            project_id="proj-p1082-claim",
            workflow_run_id="run-p1082-claim",
            research_design_id=design.id,
            statement=finding_candidates[0].statement,
            rationale=finding_candidates[0].rationale,
            evidence_refs=validate_finding_candidate(
                finding_candidates[0],
                evidence_by_id=evidence_by_id,
                project_id="proj-p1082-claim",
                workflow_run_id="run-p1082-claim",
                research_design_id=design.id,
                design=design,
            ).evidence_refs,
            created_at=datetime.now(timezone.utc).isoformat(),
            research_question_refs=("rq-1",),
            information_need_refs=("in-rq-1",),
            finding_type=FindingType.SYNTHESIS,
            confidence=0.85,
        )
        insight_candidates = analysis_engine.analyze_insights(
            AnalysisInput(
                project_id="proj-p1082-claim",
                workflow_run_id="run-p1082-claim",
                research_design_id=design.id,
                brief=brief,
                design=design,
                evidence_batch=evidence,
                persisted_findings=(finding,),
            )
        )
        validated_insight = validate_insight_candidate(
            insight_candidates[0],
            findings_by_id={finding.id: finding},
            project_id="proj-p1082-claim",
            workflow_run_id="run-p1082-claim",
            research_design_id=design.id,
            design=design,
        )
        insight = Insight(
            id="insight-visibility",
            project_id="proj-p1082-claim",
            workflow_run_id="run-p1082-claim",
            research_design_id=design.id,
            statement=validated_insight.statement,
            implication=validated_insight.implication,
            finding_refs=validated_insight.finding_refs,
            created_at=datetime.now(timezone.utc).isoformat(),
            research_question_refs=("rq-1",),
            confidence=0.8,
        )

        report_engine = DeterministicReportEngine()
        report_input = ReportInput(
            project_id="proj-p1082-claim",
            workflow_run_id="run-p1082-claim",
            research_design_id=design.id,
            brief=brief,
            design=design,
            findings=(finding,),
            insights=(insight,),
            evidence_by_id=evidence_by_id,
            sources_by_id={},
            section_titles=(design.research_questions[0].question,),
        )
        sections = report_engine.generate_sections(report_input)
        summary = report_engine.generate_executive_summary(
            report_input,
            sections=sections,
        )
        self.assertGreaterEqual(len(sections), 1)
        report = Report(
            id="report-p1082",
            project_id="proj-p1082-claim",
            workflow_run_id="run-p1082-claim",
            research_design_id=design.id,
            title=summary.title,
            language="en",
            sections=tuple(
                ReportSection(
                    id=f"section-{index + 1}",
                    title=section.title,
                    content=section.content,
                    research_question_refs=section.research_question_refs,
                    finding_refs=section.finding_refs,
                    insight_refs=section.insight_refs,
                    evidence_refs=section.evidence_refs,
                    metadata={"primary_research_question_id": "rq-1"},
                )
                for index, section in enumerate(sections)
            ),
            executive_summary=summary.executive_summary,
            limitations=summary.limitations,
            created_at=datetime.now(timezone.utc).isoformat(),
            generation_method="deterministic",
            finding_refs=(finding.id,),
            insight_refs=(insight.id,),
            evidence_refs=tuple(evidence_by_id),
            citation_registry={},
            revision_number=1,
        )
        support = build_review_support_context(
            report=report,
            findings=[finding],
            insights=[insight],
            evidence_items=list(evidence),
        )
        self.assertTrue(support.coverage_complete)
        plan = build_rq_batch_inputs(
            report,
            max_chars_per_section=8000,
            max_chars_per_batch=12000,
            max_batches=3,
        )
        self.assertGreaterEqual(len(plan.batches), 1)

        review_engine = LlmReviewEngine(
            llm_client=clients.review,
            max_review_calls=3,
            structured_output_max_attempts=1,
        )
        issues = review_engine.review_report(
            SemanticReviewInput(
                project_id="proj-p1082-claim",
                workflow_run_id="run-p1082-claim",
                research_design_id=design.id,
                report=report,
                brief_objectives=brief.objectives,
                research_questions=(design.research_questions[0].question,),
                section_inputs=build_section_inputs(report),
                support_context=support,
            )
        )
        self.assertIsInstance(issues, tuple)
        review_spy = unwrap_llm_client(clients.review)
        self.assertGreaterEqual(review_spy.calls, 1)
        payload = review_spy.prompts[0].user
        self.assertTrue(
            "41%" in payload or EVIDENCE_IDS[0] in payload or "FINDING" in payload,
        )
        # Wiring proof only — verdict construction remains ReviewService concern.
        self.assertIn(ReviewVerdict.APPROVE, ReviewVerdict)


if __name__ == "__main__":
    unittest.main()
