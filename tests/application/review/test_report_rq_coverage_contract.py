from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.report.coverage_contract import (
    CONTRACT_KEY,
    CONTRACT_VERSION,
    CoverageContractError,
    ReportCoverageContract,
    build_report_coverage_contract,
    excluded_rq_limitation,
    required_research_question_texts,
    resolve_report_coverage_contract,
    validate_report_against_coverage_contract,
)
from application.review.deterministic_pre_review import run_deterministic_pre_review
from application.review.structural_review import run_structural_review
from application.review.review_service import ReviewService
from application.review.exceptions import ReviewError
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_review_repository import InMemoryReviewRepository
from infrastructure.review.deterministic_review_engine import DeterministicReviewEngine
from domain.findings.finding import Finding
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.research_brief import ResearchBrief
from domain.reviews.review_issue import ReviewIssueType


def _design() -> ResearchDesign:
    return ResearchDesign(
        id="design", research_questions=(
            ResearchQuestion("rq1", "Supported question", ("objective one",)),
            ResearchQuestion("rq2", "Unsupported question", ("objective two",)),
        ),
    )


def _finding() -> Finding:
    return Finding(
        id="f1", project_id="p", workflow_run_id="run",
        research_design_id="design", statement="Supported result.", rationale="R",
        evidence_refs=("e1",), created_at="2026-01-01",
        research_question_refs=("rq1",),
    )


def _report(
    *, contract: ReportCoverageContract | None, rq_refs: tuple[str, ...] = ("rq1",),
    limitations: tuple[str, ...] = (), metadata: dict | None = None,
) -> Report:
    stored = dict(metadata or {})
    if contract is not None:
        stored[CONTRACT_KEY] = contract.to_metadata()
        stored["report_scope"] = contract.mode
    return Report(
        id="report", project_id="p", workflow_run_id="run",
        research_design_id="design", title="Report", language="en",
        sections=(ReportSection(
            id="section", title="Supported", content="Supported result [S1].",
            research_question_refs=rq_refs, finding_refs=("f1",),
            evidence_refs=("e1",), citation_ids=("S1",),
        ),),
        executive_summary="Summary", limitations=limitations,
        created_at="2026-01-01", generation_method="test",
        finding_refs=("f1",), insight_refs=(), evidence_refs=("e1",),
        citation_registry={"S1": {"source_id": "s1"}}, metadata=stored,
    )


class ReportRqCoverageContractTests(unittest.TestCase):
    def test_complete_contract_requires_every_design_rq(self) -> None:
        complete = build_report_coverage_contract(
            design=_design(), limited=False, required_rq_ids=("rq1", "rq2"),
        )
        self.assertEqual(complete.mode, "complete")
        with self.assertRaises(CoverageContractError):
            build_report_coverage_contract(
                design=_design(), limited=False, required_rq_ids=("rq1",),
            )
        report = _report(contract=complete, rq_refs=("rq1",))
        issues = run_structural_review(
            report=report, brief=ResearchBrief(title="T", business_question="Q"),
            design=_design(), findings=[_finding()], coverage_contract=complete,
        )
        self.assertTrue(any(
            issue.research_question_refs == ("rq2",) for issue in issues
        ))

    def test_limited_contract_checks_only_required_and_disclosed_rqs(self) -> None:
        contract = build_report_coverage_contract(
            design=_design(), limited=True, required_rq_ids=("rq1",),
        )
        limitation = excluded_rq_limitation(contract)
        report = _report(contract=contract, limitations=(limitation,))
        deterministic = run_deterministic_pre_review(
            report=report, design=_design(), findings=[_finding()], insights=[],
            coverage_contract=contract,
        )
        structural = run_structural_review(
            report=report, brief=ResearchBrief(title="T", business_question="Q"),
            design=_design(), findings=[_finding()], coverage_contract=contract,
        )
        self.assertFalse(any(
            issue.issue_type == ReviewIssueType.COVERAGE_GAP
            for issue in deterministic + structural
        ))
        self.assertEqual(
            required_research_question_texts(design=_design(), contract=contract),
            ("Supported question",),
        )

    def test_limited_missing_required_rq_fails(self) -> None:
        contract = ReportCoverageContract("limited", ("rq1",), ("rq2",))
        report = _report(
            contract=contract, rq_refs=(),
            limitations=(excluded_rq_limitation(contract),),
        )
        issues = run_structural_review(
            report=report, brief=ResearchBrief(title="T", business_question="Q"),
            design=_design(), findings=[], coverage_contract=contract,
        )
        self.assertTrue(any(
            issue.issue_type == ReviewIssueType.COVERAGE_GAP for issue in issues
        ))

    def test_excluded_rq_claim_or_missing_disclosure_fails(self) -> None:
        contract = ReportCoverageContract("limited", ("rq1",), ("rq2",))
        claimed = _report(
            contract=contract, rq_refs=("rq1", "rq2"),
            limitations=(excluded_rq_limitation(contract),),
        )
        undisclosed = _report(contract=contract)
        self.assertEqual(
            validate_report_against_coverage_contract(report=claimed, contract=contract),
            ("coverage_contract_excluded_rq_claimed:rq2",),
        )
        self.assertEqual(
            validate_report_against_coverage_contract(
                report=undisclosed, contract=contract,
            ),
            ("coverage_contract_excluded_rq_not_disclosed:rq2",),
        )

    def test_malformed_and_foreign_contracts_fail_closed(self) -> None:
        malformed = _report(contract=None, metadata={CONTRACT_KEY: {"version": 0}})
        foreign = _report(contract=None, metadata={CONTRACT_KEY: {
            "version": CONTRACT_VERSION, "mode": "limited",
            "required_rq_ids": ["rq1"], "excluded_rq_ids": ["foreign"],
        }})
        with self.assertRaises(CoverageContractError):
            resolve_report_coverage_contract(report=malformed, design=_design())
        with self.assertRaises(CoverageContractError):
            resolve_report_coverage_contract(report=foreign, design=_design())

    def test_historical_report_uses_complete_fail_closed_fallback(self) -> None:
        report = _report(contract=None)
        resolved = resolve_report_coverage_contract(report=report, design=_design())
        self.assertEqual(resolved.mode, "complete")
        self.assertEqual(resolved.required_rq_ids, ("rq1", "rq2"))
        self.assertEqual(resolved.source, "historical_complete_fallback")

    def test_support_and_citation_checks_are_unchanged(self) -> None:
        contract = ReportCoverageContract("limited", ("rq1",), ("rq2",))
        report = _report(
            contract=contract, limitations=(excluded_rq_limitation(contract),),
        )
        report.citation_registry = {}
        issues = run_deterministic_pre_review(
            report=report, design=_design(), findings=[_finding()], insights=[],
            coverage_contract=contract,
        )
        self.assertTrue(any(
            issue.issue_type == ReviewIssueType.MISSING_CITATION for issue in issues
        ))

    def test_malformed_contract_fails_before_semantic_review_with_diagnostics(self) -> None:
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        from domain.project import Project
        from domain.task_definition import TaskDefinition
        from domain.value_objects.executor_type import ExecutorType
        from domain.workflow_template import WorkflowTemplate
        from runtime.workflow_context import WorkflowContext

        design = _design()
        report = _report(contract=None, metadata={CONTRACT_KEY: {"version": 0}})
        reports = InMemoryReportRepository()
        reports.create(report)
        template = WorkflowTemplate(
            id="template", name="Review", research_design_snapshot=design,
            research_brief_snapshot=ResearchBrief(title="T", business_question="Q"),
            task_definitions=[TaskDefinition(
                id="review", name="Review", executor_id="review",
                executor_type=ExecutorType.AGENT,
            )],
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run"
        context = WorkflowContext(
            project=Project(id="p", name="P"), workflow_template=template,
            workflow_run=run,
        )
        report_service = Mock()
        report_service._resolve_design.return_value = design
        report_service._resolve_brief.return_value = template.research_brief_snapshot
        semantic_engine = Mock(wraps=DeterministicReviewEngine())
        service = ReviewService(
            semantic_review_engine=semantic_engine,
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
            report_repository=reports,
            artifact_repository=InMemoryArtifactRepository(),
            review_repository=InMemoryReviewRepository(),
            report_service=report_service, max_revision_attempts=0,
        )
        with self.assertRaises(ReviewError):
            service.review_for_context(context)
        diagnostics = context.read_shared("review_diagnostics")
        self.assertEqual(diagnostics["phase"], "coverage_contract")
        self.assertEqual(diagnostics["category"], "structural_validation_rejection")
        self.assertEqual(diagnostics["rejection_codes"], ["coverage_contract_malformed"])
        semantic_engine.review_report.assert_not_called()

    def test_semantic_review_input_receives_same_bounded_contract(self) -> None:
        contract = ReportCoverageContract("limited", ("rq1",), ("rq2",))
        report = _report(
            contract=contract, limitations=(excluded_rq_limitation(contract),),
        )
        semantic_engine = Mock()
        semantic_engine.method_name = "mock"
        semantic_engine.review_report.return_value = ()
        service = ReviewService(
            semantic_review_engine=semantic_engine,
            finding_repository=Mock(), insight_repository=Mock(),
            evidence_repository=Mock(), report_repository=Mock(),
            artifact_repository=Mock(), review_repository=Mock(),
            report_service=Mock(), max_revision_attempts=0,
        )
        service._run_semantic_review(
            context=Mock(), project_id="p", workflow_run_id="run",
            design_id="design", report=report, brief_objectives=(),
            research_questions=required_research_question_texts(
                design=_design(), contract=contract,
            ),
            structural_issues=(), support_context=None,
            coverage_contract=contract,
        )
        review_input = semantic_engine.review_report.call_args.args[0]
        self.assertEqual(review_input.report_mode, "limited")
        self.assertEqual(review_input.required_research_question_ids, ("rq1",))
        self.assertEqual(review_input.excluded_research_question_ids, ("rq2",))
        self.assertEqual(review_input.research_questions, ("Supported question",))


if __name__ == "__main__":
    unittest.main()
