"""Live-shaped analysis regression with mocked LLM output."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding_type import FindingType
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief

from application.analysis.analysis_service import AnalysisService
from application.analysis.diagnostics import (
    REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
)
from application.analysis.exceptions import AnalysisError, AnalysisConfigurationError
from application.ports.analysis_ports import AnalysisInput, FindingCandidate, InsightCandidate
from infrastructure.analysis.llm_analysis_engine import LlmAnalysisEngine
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.persistence.memory.in_memory_finding_repository import (
    InMemoryFindingRepository,
)
from infrastructure.persistence.memory.in_memory_insight_repository import (
    InMemoryInsightRepository,
)


def _live_like_design() -> ResearchDesign:
    return ResearchDesign(
        id="design-4a8eae0f",
        research_questions=(
            ResearchQuestion(
                id="rq-market-size",
                question="What is the market size?",
                objective_refs=("obj-1",),
                priority=1,
                rationale="",
            ),
            ResearchQuestion(
                id="rq-competition",
                question="Who are the competitors?",
                objective_refs=("obj-2",),
                priority=2,
                rationale="",
            ),
        ),
        information_needs=(),
        source_strategy=("web",),
        analysis_plan=("synthesize market and competitor evidence",),
        deliverable_plan=("summary",),
        assumptions=(),
        limitations=(),
        language="en",
    )


def _live_like_evidence(*, run_id: str, design_id: str) -> list[Evidence]:
    items: list[Evidence] = []
    for index in range(1, 7):
        question_ids = ("rq-market-size",) if index % 2 else ("rq-competition",)
        items.append(
            Evidence(
                id=f"evidence-4a8eae0f-{index:03d}",
                project_id="project-live",
                source_id=f"source-{index:03d}",
                source_content_checksum=f"checksum-{index:03d}",
                workflow_run_id=run_id,
                research_design_id=design_id,
                statement=f"Evidence statement {index}",
                source_excerpt=f"Excerpt {index}",
                created_at="2026-08-04T00:00:00+00:00",
                research_question_refs=question_ids,
                evidence_type=EvidenceType.DIRECT_EXCERPT,
                deduplication_key=f"dedup-evidence-{index:03d}",
            ),
        )
    return items


def _analysis_context(*, run_id: str, design: ResearchDesign):
    from domain.factories.task_factory import TaskFactory
    from domain.factories.workflow_run_factory import WorkflowRunFactory
    from domain.project import Project
    from domain.value_objects.executor_type import ExecutorType
    from domain.workflow_template_builder import WorkflowTemplateBuilder
    from runtime.workflow_context import WorkflowContext

    template = (
        WorkflowTemplateBuilder(id="template-live", name="Live Shape")
        .add_task(
            id="task-analyze",
            name="Analyze",
            executor_id="analysis",
            executor_type=ExecutorType.AGENT,
        )
        .build()
    )
    brief = ResearchBrief(title="Live", business_question="Market assessment")
    template.research_design_snapshot = design
    template.research_brief_snapshot = brief
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template=template,
        run_id=run_id,
    )
    return WorkflowContext(
        project=Project(id="project-live", name="Live Project"),
        workflow_run=run,
        workflow_template=template,
    )


class InsightEchoEngine:
    method_name = "test"

    def __init__(self, finding_engine) -> None:
        self._finding_engine = finding_engine

    @property
    def last_finding_batch_stats(self):
        return getattr(self._finding_engine, "last_finding_batch_stats", None)

    def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
        return self._finding_engine.analyze_findings(analysis_input)

    def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
        finding_refs = tuple(item.id for item in analysis_input.persisted_findings)
        return [
            InsightCandidate(
                statement="Insight from findings",
                implication="Implication",
                finding_refs=finding_refs,
            ),
        ]


class AnalysisLiveShapeRegressionTests(unittest.TestCase):
    def _service(self, engine) -> AnalysisService:
        return AnalysisService(
            analysis_engine=InsightEchoEngine(engine),
            evidence_repository=InMemoryEvidenceRepository(),
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=3,
            max_chars_per_batch=12000,
        )

    def test_valid_finding_referencing_real_evidence_persists(self) -> None:
        design = _live_like_design()
        run_id = "run-live-valid"
        evidence_repo = InMemoryEvidenceRepository()
        for item in _live_like_evidence(run_id=run_id, design_id=design.id):
            evidence_repo.create(item)

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "findings": [
                        {
                            "statement": "Market is growing",
                            "rationale": "Multiple sources agree",
                            "evidence_refs": ["evidence-4a8eae0f-001"],
                            "research_question_refs": ["rq-market-size"],
                            "finding_type": "synthesis",
                            "confidence": 0.8,
                        },
                    ],
                },
            ),
        )
        engine = LlmAnalysisEngine(llm_client=mock_llm)
        service = AnalysisService(
            analysis_engine=InsightEchoEngine(engine),
            evidence_repository=evidence_repo,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=3,
            max_chars_per_batch=12000,
        )
        summary = service.analyze_for_context(
            _analysis_context(run_id=run_id, design=design),
        )
        self.assertEqual(len(summary.finding_ids), 1)
        self.assertEqual(len(summary.insight_ids), 1)

    def test_invalid_foreign_evidence_ref_is_rejected(self) -> None:
        design = _live_like_design()
        run_id = "run-live-invalid-ref"
        evidence_repo = InMemoryEvidenceRepository()
        for item in _live_like_evidence(run_id=run_id, design_id=design.id)[:1]:
            evidence_repo.create(item)

        mock_llm = Mock()
        mock_llm.generate.return_value = LLMResponse(
            content=json.dumps(
                {
                    "findings": [
                        {
                            "statement": "Bad ref",
                            "rationale": "Uses foreign evidence id",
                            "evidence_refs": ["evidence-foreign-999"],
                            "finding_type": "synthesis",
                        },
                    ],
                },
            ),
        )
        engine = LlmAnalysisEngine(llm_client=mock_llm)
        service = AnalysisService(
            analysis_engine=InsightEchoEngine(engine),
            evidence_repository=evidence_repo,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=3,
            max_chars_per_batch=12000,
        )
        with self.assertRaises(AnalysisError) as ctx:
            service.analyze_for_context(
                _analysis_context(run_id=run_id, design=design),
            )
        message = str(ctx.exception)
        self.assertIn("total_engine_dropped=", message)
        self.assertIn("batch_count=1", message)

    def test_one_bad_batch_does_not_suppress_valid_findings_from_another(self) -> None:
        design = _live_like_design()
        run_id = "run-live-mixed-batches"
        evidence_repo = InMemoryEvidenceRepository()
        for item in _live_like_evidence(run_id=run_id, design_id=design.id):
            evidence_repo.create(item)

        responses = [
            LLMResponse(content="not-json"),
            LLMResponse(
                content=json.dumps(
                    {
                        "findings": [
                            {
                                "statement": "Competitors are fragmented",
                                "rationale": "Evidence supports fragmentation",
                                "evidence_refs": ["evidence-4a8eae0f-002"],
                                "research_question_refs": ["rq-competition"],
                                "finding_type": "synthesis",
                            },
                        ],
                    },
                ),
            ),
        ]
        mock_llm = Mock()
        mock_llm.generate.side_effect = responses + [
            LLMResponse(
                content=json.dumps(
                    {
                        "insights": [
                            {
                                "statement": "Insight",
                                "implication": "Implication",
                                "finding_refs": ["finding-placeholder"],
                            },
                        ],
                    },
                ),
            ),
        ]

        class MixedBatchEngine(LlmAnalysisEngine):
            def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
                finding_refs = tuple(item.id for item in analysis_input.persisted_findings)
                return [
                    InsightCandidate(
                        statement="Recovered insight",
                        implication="Still valid",
                        finding_refs=finding_refs,
                    ),
                ]

        engine = MixedBatchEngine(llm_client=mock_llm)
        service = AnalysisService(
            analysis_engine=engine,
            evidence_repository=evidence_repo,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=3,
            max_chars_per_batch=12000,
        )
        summary = service.analyze_for_context(
            _analysis_context(run_id=run_id, design=design),
        )
        self.assertEqual(len(summary.finding_ids), 1)
        self.assertEqual(summary.batch_failures, 1)

    def test_all_invalid_candidates_produce_analysis_error_with_diagnostics(self) -> None:
        design = _live_like_design()
        run_id = "run-live-all-invalid"
        evidence_repo = InMemoryEvidenceRepository()
        for item in _live_like_evidence(run_id=run_id, design_id=design.id)[:2]:
            evidence_repo.create(item)

        class RejectAllEngine:
            method_name = "test"

            def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
                return [
                    FindingCandidate(
                        statement="Bad",
                        rationale="Bad",
                        evidence_refs=("evidence-foreign-001",),
                        finding_type=FindingType.SYNTHESIS.value,
                    ),
                ]

            def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
                return []

        service = AnalysisService(
            analysis_engine=RejectAllEngine(),
            evidence_repository=evidence_repo,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=10,
            max_chars_per_batch=12000,
        )
        with self.assertRaises(AnalysisError) as ctx:
            service.analyze_for_context(
                _analysis_context(run_id=run_id, design=design),
            )
        message = str(ctx.exception)
        self.assertIn("No valid findings produced", message)
        self.assertIn("evidence_count=2", message)
        self.assertIn("total_rejected=", message)
        self.assertIn(REJECTION_CATEGORY_INVALID_EVIDENCE_REF, message)

    def test_llm_configuration_error_is_counted_as_batch_failure(self) -> None:
        design = _live_like_design()
        run_id = "run-live-llm-error"
        evidence_repo = InMemoryEvidenceRepository()
        for item in _live_like_evidence(run_id=run_id, design_id=design.id)[:1]:
            evidence_repo.create(item)

        mock_llm = Mock()
        mock_llm.generate.side_effect = RuntimeError("provider unavailable")

        class FailingEngine(LlmAnalysisEngine):
            def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
                raise AnalysisConfigurationError("LLM finding analysis failed")

        service = AnalysisService(
            analysis_engine=FailingEngine(llm_client=mock_llm),
            evidence_repository=evidence_repo,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=10,
            max_chars_per_batch=12000,
        )
        with self.assertRaises(AnalysisError) as ctx:
            service.analyze_for_context(
                _analysis_context(run_id=run_id, design=design),
            )
        self.assertIn("failure_category_summary=", str(ctx.exception))

    def test_multi_question_evidence_still_produces_findings(self) -> None:
        design = _live_like_design()
        run_id = "run-live-multi-question"
        evidence_repo = InMemoryEvidenceRepository()
        for item in _live_like_evidence(run_id=run_id, design_id=design.id):
            evidence_repo.create(item)

        mock_llm = Mock()
        mock_llm.generate.side_effect = [
            LLMResponse(
                content=json.dumps(
                    {
                        "findings": [
                            {
                                "statement": "Finding A",
                                "rationale": "Rationale A",
                                "evidence_refs": ["evidence-4a8eae0f-001"],
                                "research_question_refs": ["rq-market-size"],
                            },
                        ],
                    },
                ),
            ),
            LLMResponse(
                content=json.dumps(
                    {
                        "findings": [
                            {
                                "statement": "Finding B",
                                "rationale": "Rationale B",
                                "evidence_refs": ["evidence-4a8eae0f-002"],
                                "research_question_refs": ["rq-competition"],
                            },
                        ],
                    },
                ),
            ),
            LLMResponse(
                content=json.dumps(
                    {
                        "insights": [
                            {
                                "statement": "Combined insight",
                                "implication": "Implication",
                                "finding_refs": ["finding-placeholder"],
                            },
                        ],
                    },
                ),
            ),
        ]

        class MultiBatchEngine(LlmAnalysisEngine):
            def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
                finding_refs = tuple(item.id for item in analysis_input.persisted_findings)
                return [
                    InsightCandidate(
                        statement="Combined insight",
                        implication="Implication",
                        finding_refs=finding_refs,
                    ),
                ]

        engine = MultiBatchEngine(llm_client=mock_llm)
        service = AnalysisService(
            analysis_engine=engine,
            evidence_repository=evidence_repo,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=3,
            max_chars_per_batch=12000,
        )
        summary = service.analyze_for_context(
            _analysis_context(run_id=run_id, design=design),
        )
        self.assertGreaterEqual(len(summary.finding_ids), 2)


if __name__ == "__main__":
    unittest.main()
