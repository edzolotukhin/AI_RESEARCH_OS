"""Live-shaped analysis regression with mocked LLM output."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.findings.finding_type import FindingType
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.research_brief import ResearchBrief

from application.analysis.analysis_service import AnalysisService
from application.analysis.deduplication import compute_finding_deduplication_key
from application.analysis.diagnostics import (
    REJECTION_CATEGORY_EXTENSION_INFORMATION_NEED_OWNERSHIP,
    REJECTION_CATEGORY_INVALID_EVIDENCE_REF,
)
from application.analysis.exceptions import AnalysisError, AnalysisConfigurationError
from application.authority_extension.selected_workflow import ExtensionBudgetExceeded
from application.authority_extension.stage_adapters import (
    ExtensionProviderBudgetProxy,
    _extension_dispatch,
)
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
from domain.findings.finding import Finding


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
    def _extension_ownership_fixture(self, candidates):
        design = ResearchDesign(
            id="design-extension-ownership",
            research_questions=(ResearchQuestion("rq-1", "Question"),),
            information_needs=(
                InformationNeed("in-1", "rq-1", "Need one"),
                InformationNeed("in-2", "rq-1", "Need two"),
            ),
        )
        run_id = "run-extension-ownership"
        context = _analysis_context(run_id=run_id, design=design)
        evidence_repo = InMemoryEvidenceRepository()
        for index, need_id in enumerate(("in-1", "in-2"), start=1):
            evidence_repo.create(Evidence(
                id=f"ev-{index}", project_id="project-live", source_id=f"source-{index}",
                source_content_checksum=f"checksum-{index}", workflow_run_id=run_id,
                research_design_id=design.id, statement=f"Fact {index}",
                source_excerpt=f"Fact {index}", created_at="2026-08-04T00:00:00+00:00",
                research_question_refs=("rq-1",), information_need_refs=(need_id,),
                deduplication_key=f"ev-{index}",
            ))

        class OwnershipEngine:
            method_name = "test"

            def analyze_findings(self, analysis_input):
                return list(candidates)

            def analyze_insights(self, analysis_input):
                return [InsightCandidate(
                    statement="Insight", implication="Implication",
                    finding_refs=tuple(item.id for item in analysis_input.persisted_findings),
                )]

        finding_repo = InMemoryFindingRepository()
        service = AnalysisService(
            analysis_engine=OwnershipEngine(), evidence_repository=evidence_repo,
            finding_repository=finding_repo,
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=20, max_chars_per_batch=12000,
        )
        return service, finding_repo, context

    def test_extension_single_need_finding_persists(self) -> None:
        candidate = FindingCandidate(
            statement="Single need", rationale="Supported", evidence_refs=("ev-1",),
            information_need_refs=("in-1",),
        )
        service, findings, context = self._extension_ownership_fixture((candidate,))
        context.write_shared("authority_extension_plan", {
            "selected_information_need_ids": ["in-1", "in-2"],
        })
        with patch(
            "application.analysis.analysis_service.qualifying_evidence",
            side_effect=lambda **kwargs: tuple(kwargs["evidence"]),
        ):
            summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 1)
        persisted = findings.list_for_project("project-live", workflow_run_id=context.workflow_run.id)[0]
        self.assertEqual(persisted.information_need_refs, ("in-1",))
        self.assertEqual(persisted.metadata["validation_status"], "validated")

    def test_successful_validation_overrides_candidate_status(self) -> None:
        candidate = FindingCandidate(
            statement="Status override", rationale="Supported", evidence_refs=("ev-1",),
            information_need_refs=("in-1",), metadata={"validation_status": "rejected"},
        )
        service, findings, context = self._extension_ownership_fixture((candidate,))
        with patch(
            "application.analysis.analysis_service.qualifying_evidence",
            side_effect=lambda **kwargs: tuple(kwargs["evidence"]),
        ):
            service.analyze_for_context(context)
        self.assertEqual(
            findings.list_for_project("project-live", workflow_run_id=context.workflow_run.id)[0].metadata["validation_status"],
            "validated",
        )

    def test_extension_multi_need_finding_is_rejected_before_persistence(self) -> None:
        candidate = FindingCandidate(
            statement="Multi need", rationale="Unsupported ownership",
            evidence_refs=("ev-1", "ev-2"),
            information_need_refs=("in-1", "in-2"),
        )
        service, findings, context = self._extension_ownership_fixture((candidate,))
        context.write_shared("authority_extension_plan", {
            "selected_information_need_ids": ["in-1", "in-2"],
        })
        with patch(
            "application.analysis.analysis_service.qualifying_evidence",
            side_effect=lambda **kwargs: tuple(kwargs["evidence"]),
        ):
            with self.assertRaises(AnalysisError) as raised:
                service.analyze_for_context(context)
        self.assertIn(
            REJECTION_CATEGORY_EXTENSION_INFORMATION_NEED_OWNERSHIP,
            str(raised.exception),
        )
        self.assertEqual(findings.list_for_project("project-live"), [])

    def test_ordinary_desk_multi_need_finding_remains_permitted(self) -> None:
        candidate = FindingCandidate(
            statement="Multi need", rationale="Ordinary Desk synthesis",
            evidence_refs=("ev-1", "ev-2"),
            information_need_refs=("in-1", "in-2"),
        )
        service, findings, context = self._extension_ownership_fixture((candidate,))
        with patch(
            "application.analysis.analysis_service.qualifying_evidence",
            side_effect=lambda **kwargs: tuple(kwargs["evidence"]),
        ):
            summary = service.analyze_for_context(context)
        self.assertEqual(len(summary.finding_ids), 1)
        self.assertEqual(len(findings.list_for_project("project-live")), 1)

    def test_extension_partial_success_persists_only_single_need_finding(self) -> None:
        candidates = (
            FindingCandidate(
                statement="Invalid multi need", rationale="Rejected",
                evidence_refs=("ev-1", "ev-2"),
                information_need_refs=("in-1", "in-2"),
            ),
            FindingCandidate(
                statement="Valid single need", rationale="Accepted",
                evidence_refs=("ev-1",), information_need_refs=("in-1",),
            ),
        )
        service, findings, context = self._extension_ownership_fixture(candidates)
        context.write_shared("authority_extension_plan", {
            "selected_information_need_ids": ["in-1", "in-2"],
        })
        with patch(
            "application.analysis.analysis_service.qualifying_evidence",
            side_effect=lambda **kwargs: tuple(kwargs["evidence"]),
        ):
            summary = service.analyze_for_context(context)
        persisted = findings.list_for_project("project-live", workflow_run_id=context.workflow_run.id)
        self.assertEqual([item.statement for item in persisted], ["Valid single need"])
        self.assertEqual(
            summary.rejection_counts,
            {REJECTION_CATEGORY_EXTENSION_INFORMATION_NEED_OWNERSHIP: 1},
        )

    def test_extension_dedup_rejects_historical_multi_need_finding(self) -> None:
        candidate = FindingCandidate(
            statement="Historical collision", rationale="candidate",
            evidence_refs=("ev-1",), information_need_refs=("in-1",),
        )
        service, findings, context = self._extension_ownership_fixture((candidate,))
        key = compute_finding_deduplication_key(
            workflow_run_id=context.workflow_run.id,
            statement=candidate.statement, evidence_refs=candidate.evidence_refs,
        )
        findings.create(Finding(
            id="historical-invalid", project_id="project-live",
            workflow_run_id=context.workflow_run.id,
            research_design_id="design-extension-ownership",
            research_question_refs=("rq-1",), information_need_refs=("in-1", "in-2"),
            statement=candidate.statement, rationale="historical",
            evidence_refs=candidate.evidence_refs, finding_type=FindingType.SYNTHESIS,
            confidence=0.8, analysis_method="historical", deduplication_key=key,
            created_at="2026-08-04T00:00:00+00:00", metadata={},
        ))
        with self.assertRaises(AnalysisError):
            service._persist_finding(
                candidate=candidate, project_id="project-live",
                workflow_run_id=context.workflow_run.id,
                research_design_id="design-extension-ownership",
                require_single_information_need=True,
            )
        self.assertEqual(findings.get_by_id("historical-invalid").information_need_refs, ("in-1", "in-2"))

    def test_extension_dedup_recovery_returns_compatible_concurrent_record(self) -> None:
        candidate = FindingCandidate(
            statement="Concurrent collision", rationale="candidate",
            evidence_refs=("ev-1",), information_need_refs=("in-1",),
        )
        service, findings, context = self._extension_ownership_fixture((candidate,))
        original_create = findings.create
        inserted = {"done": False}

        def concurrent_create(finding):
            if not inserted["done"]:
                inserted["done"] = True
                original_create(finding)
                from application.analysis.exceptions import DuplicateFindingError
                raise DuplicateFindingError("concurrent insert")
            return original_create(finding)

        findings.create = concurrent_create
        persisted_id = service._persist_finding(
            candidate=candidate, project_id="project-live",
            workflow_run_id=context.workflow_run.id,
            research_design_id="design-extension-ownership",
            require_single_information_need=True,
        )
        self.assertEqual(
            persisted_id,
            findings.list_for_project("project-live", workflow_run_id=context.workflow_run.id)[0].id,
        )
        self.assertEqual(len(findings.list_for_project("project-live")), 1)

    def test_extension_dedup_recovery_rejects_incompatible_concurrent_record(self) -> None:
        candidate = FindingCandidate(
            statement="Concurrent invalid collision", rationale="candidate",
            evidence_refs=("ev-1",), information_need_refs=("in-1",),
        )
        service, findings, context = self._extension_ownership_fixture((candidate,))
        original_create = findings.create
        inserted = {"done": False}

        def concurrent_invalid_create(finding):
            if not inserted["done"]:
                inserted["done"] = True
                invalid = Finding(
                    id="concurrent-invalid", project_id=finding.project_id,
                    workflow_run_id=finding.workflow_run_id,
                    research_design_id=finding.research_design_id,
                    research_question_refs=("rq-1",), information_need_refs=("in-1", "in-2"),
                    statement=finding.statement, rationale="historical",
                    evidence_refs=finding.evidence_refs, finding_type=FindingType.SYNTHESIS,
                    confidence=0.8, analysis_method="historical",
                    deduplication_key=finding.deduplication_key,
                    created_at="2026-08-04T00:00:00+00:00", metadata={},
                )
                original_create(invalid)
                from application.analysis.exceptions import DuplicateFindingError
                raise DuplicateFindingError("concurrent insert")
            return original_create(finding)

        findings.create = concurrent_invalid_create
        with self.assertRaises(AnalysisError):
            service._persist_finding(
                candidate=candidate, project_id="project-live",
                workflow_run_id=context.workflow_run.id,
                research_design_id="design-extension-ownership",
                require_single_information_need=True,
            )
        persisted = findings.get_by_id("concurrent-invalid")
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.information_need_refs, ("in-1", "in-2"))

    def test_extension_analysis_filters_composed_evidence_to_selected_needs(self) -> None:
        question = ResearchQuestion("rq-selected", "Selected question")
        design = ResearchDesign(
            id="design-scope",
            research_questions=(question,),
            information_needs=(
                InformationNeed("in-selected", "rq-selected", "Selected"),
                InformationNeed("in-other", "rq-selected", "Other"),
            ),
        )
        context = _analysis_context(run_id="run-scope", design=design)
        context.write_shared("authority_extension_members", {
            "workflow_run_ids": ["parent-scope", "run-scope"],
        })
        context.write_shared("authority_extension_plan", {
            "selected_information_need_ids": ["in-selected"],
        })
        evidence = InMemoryEvidenceRepository()
        for item_id, run_id, need_id in (
            ("parent-selected", "parent-scope", "in-selected"),
            ("parent-other", "parent-scope", "in-other"),
            ("extension-selected", "run-scope", "in-selected"),
        ):
            evidence.create(Evidence(
                id=item_id, project_id="project-live", source_id=f"source-{item_id}",
                source_content_checksum=f"checksum-{item_id}", workflow_run_id=run_id,
                research_design_id="design-scope", statement=item_id,
                source_excerpt=item_id, created_at="2026-08-04T00:00:00+00:00",
                research_question_refs=("rq-selected",),
                information_need_refs=(need_id,), deduplication_key=item_id,
            ))

        class RecordingEngine:
            def __init__(self):
                self.batch_ids = []
            def analyze_findings(self, analysis_input):
                self.batch_ids.append(tuple(item.id for item in analysis_input.evidence_batch))
                return []
            def analyze_insights(self, analysis_input):
                return []

        engine = RecordingEngine()
        service = AnalysisService(
            analysis_engine=engine, evidence_repository=evidence,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            max_evidence_per_batch=20, max_chars_per_batch=12000,
        )
        with patch(
            "application.analysis.analysis_service.qualifying_evidence",
            side_effect=lambda **kwargs: tuple(kwargs["evidence"]),
        ):
            with self.assertRaises(AnalysisError):
                service.analyze_for_context(context)
        self.assertEqual(engine.batch_ids, [("parent-selected", "extension-selected")])

    def test_extension_budget_exhaustion_is_not_masked_by_llm_engine(self) -> None:
        provider = Mock()

        class ExhaustedService:
            def dispatch_provider(self, run_id, operation, *, stage=None):
                raise ExtensionBudgetExceeded(
                    "authority_extension_analysis_budget_exhausted",
                )

        engine = LlmAnalysisEngine(
            llm_client=ExtensionProviderBudgetProxy(provider),
        )
        analysis_input = AnalysisInput(
            project_id="project-live",
            workflow_run_id="run-live-budget",
            research_design_id="design-4a8eae0f",
            brief=ResearchBrief("Live", "Market assessment"),
            design=_live_like_design(),
            evidence_batch=tuple(_live_like_evidence(
                run_id="run-live-budget", design_id="design-4a8eae0f",
            )[:1]),
        )
        token = _extension_dispatch.set((ExhaustedService(), "run-live-budget", "analysis"))
        try:
            with self.assertRaises(ExtensionBudgetExceeded) as raised:
                engine.analyze_findings(analysis_input)
        finally:
            _extension_dispatch.reset(token)
        self.assertEqual(
            str(raised.exception),
            "authority_extension_analysis_budget_exhausted",
        )
        provider.generate.assert_not_called()

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
        from tests.helpers.citation_fixtures import sources_for
        service._source_repository = sources_for(list(service._evidence_repository._evidence.values()))
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
            from tests.helpers.citation_fixtures import sources_for
            service._source_repository = sources_for(list(service._evidence_repository._evidence.values()))
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
        from tests.helpers.citation_fixtures import sources_for
        service._source_repository = sources_for(list(service._evidence_repository._evidence.values()))
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
            from tests.helpers.citation_fixtures import sources_for
            service._source_repository = sources_for(list(service._evidence_repository._evidence.values()))
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
            from tests.helpers.citation_fixtures import sources_for
            service._source_repository = sources_for(list(service._evidence_repository._evidence.values()))
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
        from tests.helpers.citation_fixtures import sources_for
        service._source_repository = sources_for(list(service._evidence_repository._evidence.values()))
        summary = service.analyze_for_context(
            _analysis_context(run_id=run_id, design=design),
        )
        self.assertGreaterEqual(len(summary.finding_ids), 2)


if __name__ == "__main__":
    unittest.main()
