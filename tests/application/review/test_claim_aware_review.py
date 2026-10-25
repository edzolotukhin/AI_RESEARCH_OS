from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from hashlib import sha256

from application.evidence.grounding import verify_grounding
from application.ports.review_ports import ReviewIssueCandidate
from application.report.claim_rendering import render_validated_claims
from application.report.coverage_contract import ReportCoverageContract
from application.report.claim_first_report_service import ClaimFirstReportService
from application.review.claim_review import review_structured_claim_contract
from application.review.review_service import ReviewService
from application.review.exceptions import ReviewError
from application.replay.desk_downstream_replay import REPLAY_KEY
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.reports.report import Report
from domain.findings.insight import Insight
from domain.reviews.review_issue import ReviewIssueSeverity, ReviewIssueType
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template_builder import WorkflowTemplateBuilder
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_review_repository import InMemoryReviewRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from infrastructure.review.deterministic_review_engine import DeterministicReviewEngine
from runtime.workflow_context import WorkflowContext
from tests.fixtures.research_brief import sample_research_brief
import tests.application.report.test_report_claim_contract as claim_fixtures


class _ReviseOnceEngine:
    method_name = "deterministic-targeted"

    def review_report(self, review_input):
        if review_input.report.revision_number > 1:
            return ()
        section = review_input.report.sections[0]
        return (ReviewIssueCandidate(
            issue_type=ReviewIssueType.UNSUPPORTED_CLAIM.value,
            severity=ReviewIssueSeverity.MAJOR.value,
            message="Rendered wording is not entailed by the referenced claim",
            report_section_id=section.id,
            claim_refs=section.claim_refs,
            research_question_refs=section.research_question_refs,
            report_revision=review_input.report.revision_number,
            suggested_action="Rerender this section from its validated claims",
        ),)


class _AlwaysReviseEngine(_ReviseOnceEngine):
    def review_report(self, review_input):
        section = review_input.report.sections[0]
        return (ReviewIssueCandidate(issue_type=ReviewIssueType.UNSUPPORTED_CLAIM.value, severity=ReviewIssueSeverity.MAJOR.value, message="Still blocking", report_section_id=section.id, claim_refs=section.claim_refs, research_question_refs=section.research_question_refs, report_revision=review_input.report.revision_number, suggested_action="Rerender"),)


class _SummaryReviseOnceEngine(_ReviseOnceEngine):
    def review_report(self, review_input):
        if review_input.report.revision_number > 1:
            return ()
        return (ReviewIssueCandidate(issue_type=ReviewIssueType.UNSUPPORTED_CLAIM.value, severity=ReviewIssueSeverity.MAJOR.value, message="Summary wording is not entailed", report_revision=1, suggested_action="Rerender summary unit", metadata={"summary_unit_indices": [0]}),)


class ClaimAwareReviewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        self.fixture = fixture
        base_claim = fixture.claim()
        payload = base_claim.to_dict(); payload["support"]["citation_ids"] = ["S1"]
        self.claim = base_claim.__class__.from_dict(payload)
        rendered = render_validated_claims(claims=(self.claim,), design=fixture.design)
        self.contract = ReportCoverageContract("complete", ("rq-1",), ())
        self.report = Report(
            id="report-1", project_id="project-1", workflow_run_id="source-run",
            research_design_id=fixture.design.id, title="R", language="en",
            sections=rendered.sections, executive_summary=rendered.executive_summary,
            limitations=("Known limitation",), created_at="2026-01-01T00:00:00Z",
            generation_method="claim-first:deterministic",
            finding_refs=self.claim.finding_ids, insight_refs=(),
            evidence_refs=self.claim.evidence_ids,
            citation_registry={"S1": {"source_id": self.claim.source_ids[0]}},
            deduplication_key="report-1", revision_number=1,
            metadata={
                "structured_claim_contract": "desk_report_claim_v1",
                "rq_coverage_contract": self.contract.to_metadata(),
                "summary_units": list(rendered.summary_units),
            },
        )

    def issues(self, *, report=None, claims=None, findings=None, evidence=None, source_run="source-run"):
        return review_structured_claim_contract(
            report=report or self.report, claims=claims if claims is not None else (self.claim,),
            design=self.fixture.design,
            findings=findings if findings is not None else [self.fixture.finding],
            insights=[], evidence_items=evidence if evidence is not None else [self.fixture.evidence],
            source_workflow_run_id=source_run, coverage_contract=self.contract,
        )

    def test_valid_claim_contract_passes_and_corruption_fails_closed(self) -> None:
        self.assertEqual(self.issues(), ())
        cases = {
            "missing": self.issues(claims=()),
            "foreign": self.issues(claims=(replace(self.claim, report_workflow_run_id="foreign"),)),
            "digest": self.issues(claims=(replace(self.claim, authority_digest="wrong"),)),
            "unknown_section": self.issues(report=replace(self.report, sections=(replace(self.report.sections[0], claim_refs=("unknown",)),))),
            "unknown_summary": self.issues(report=replace(self.report, metadata={**self.report.metadata, "summary_units": [{"text": "x", "claim_ids": ["unknown"], "classification": "factual"}]})),
            "citation": self.issues(report=replace(self.report, sections=(replace(self.report.sections[0], citation_ids=("S2",)),))),
        }
        for label, issues in cases.items():
            with self.subTest(label=label):
                self.assertTrue(issues)
                self.assertTrue(all(issue.metadata.get("non_repairable") for issue in issues))
                self.assertTrue(all(issue.report_revision == 1 for issue in issues))

    def test_claim_backed_complete_and_limited_coverage_are_shared(self) -> None:
        self.assertEqual(self.issues(), ())
        limited = ReportCoverageContract("limited", ("rq-1",), ("rq-excluded",))
        report = replace(self.report, metadata={**self.report.metadata, "rq_coverage_contract": limited.to_metadata()})
        issues = review_structured_claim_contract(
            report=report, claims=(self.claim,), design=self.fixture.design,
            findings=[self.fixture.finding], insights=[], evidence_items=[self.fixture.evidence],
            source_workflow_run_id="source-run", coverage_contract=limited,
        )
        self.assertEqual(issues, ())


class ClaimAwareReviewPipelineTests(unittest.TestCase):
    def _pipeline(self, semantic_engine, *, replay: bool = False):
        fixture = claim_fixtures.ReportClaimContractTests(); fixture.setUp()
        project = ProjectFactory().create("Claim-aware Review")
        source_text = "E"; checksum = sha256(source_text.encode()).hexdigest()
        sources = tuple(Source(id=f"source-{index}", project_id=project.id, url=f"https://example.com/source-{index}", canonical_url=f"https://example.com/source-{index}", title=f"Source {index}", retrieved_at="2026-01-01T00:00:00Z", retrieval_status=RetrievalStatus.ACQUIRED, content_text=source_text, content_checksum=checksum, research_question_refs=("rq-1",), information_need_refs=("in-1",), workflow_run_refs=("source-run",), research_design_refs=(fixture.design.id,)) for index in range(29))
        source_repo = InMemorySourceRepository()
        for source in sources: source_repo.create(source)
        evidence_items = tuple(replace(fixture.evidence, id=f"evidence-{index}", project_id=project.id, source_id=sources[index % 29].id, deduplication_key=f"evidence-{index}") for index in range(50))
        evidence_repo = InMemoryEvidenceRepository()
        for evidence in evidence_items:
            evidence.source_content_checksum = checksum; evidence.source_locator = verify_grounding(source_text=source_text, excerpt="E").to_dict(); evidence_repo.create(evidence)
        findings = tuple(replace(fixture.finding, id=f"finding-{index}", project_id=project.id, evidence_refs=tuple(item.id for item in evidence_items[index * 10:(index + 1) * 10]), deduplication_key=f"finding-{index}") for index in range(5))
        finding_repo = InMemoryFindingRepository()
        for finding in findings: finding_repo.create(finding)
        insight_repo = InMemoryInsightRepository()
        insights = tuple(Insight(id=f"insight-{index}", project_id=project.id, workflow_run_id="source-run", research_design_id=fixture.design.id, statement="Supported implication", implication="Supported implication", finding_refs=(findings[index].id,), created_at="2026-01-01T00:00:00Z", research_question_refs=("rq-1",), deduplication_key=f"insight-{index}") for index in range(5))
        for insight in insights: insight_repo.create(insight)
        report_repo = InMemoryReportRepository(); claim_repo = InMemoryReportClaimRepository(report_repo)
        artifact_repo = InMemoryArtifactRepository(); review_repo = InMemoryReviewRepository()
        template = WorkflowTemplateBuilder(id="template", name="T").add_task(id="report", name="Write", executor_id="report", executor_type=ExecutorType.AGENT).build()
        template.research_brief_snapshot = replace(sample_research_brief(), timeframe=""); template.research_design_snapshot = fixture.design
        report_run_id = "replay-run" if replay else "source-run"
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id=report_run_id); run.project_id = project.id
        context = WorkflowContext(project=project, workflow_run=run, workflow_template=template, current_task=run.tasks[0])
        if replay:
            context.write_shared(REPLAY_KEY, {"version": 1, "source_workflow_run_id": "source-run", "replay_attempt_id": "attempt-1"})
        report_service = ClaimFirstReportService(report_claim_repository=claim_repo, report_engine=DeterministicReportEngine(), finding_repository=finding_repo, insight_repository=insight_repo, evidence_repository=evidence_repo, source_repository=source_repo, report_repository=report_repo, artifact_repository=artifact_repo, max_findings_per_batch=10, max_chars_per_batch=10000)
        report_service.write_for_context(context)
        service = ReviewService(semantic_review_engine=semantic_engine, finding_repository=finding_repo, insight_repository=insight_repo, evidence_repository=evidence_repo, report_repository=report_repo, report_claim_repository=claim_repo, artifact_repository=artifact_repo, review_repository=review_repo, report_service=report_service, max_revision_attempts=5)
        return service, context, report_repo, claim_repo, review_repo, (sources, evidence_items, findings, insights)

    def test_provider_free_valid_report_approves(self) -> None:
        service, context, report_repo, claim_repo, review_repo, _ = self._pipeline(DeterministicReviewEngine())
        summary = service.review_for_context(context)
        self.assertEqual(summary.verdict, "approve")
        self.assertEqual(summary.revision_count, 0)
        report = report_repo.get_by_id(summary.report_id)
        self.assertTrue(claim_repo.list_for_report(report.id, report.revision_number))
        self.assertEqual(len(claim_repo.list_for_report(report.id, report.revision_number)), 5)
        review = review_repo.list_for_project(context.project.id, workflow_run_id="source-run")[0]
        self.assertEqual(len(review.metadata["claim_set_digest"]), 64)
        self.assertEqual(len(review.metadata["coverage_contract_digest"]), 64)

    def test_one_real_targeted_revision_then_approve_preserves_old_revision(self) -> None:
        service, context, report_repo, claim_repo, review_repo, source_artifacts = self._pipeline(_ReviseOnceEngine())
        source_snapshot = copy.deepcopy(source_artifacts)
        original = max(report_repo.list_for_project(context.project.id, workflow_run_id="source-run"), key=lambda item: item.revision_number)
        original_claims = claim_repo.list_for_report(original.id, 1)
        summary = service.review_for_context(context)
        self.assertEqual(summary.verdict, "approve")
        self.assertEqual(summary.revision_count, 1)
        self.assertEqual(summary.review_attempt, 2)
        revised = report_repo.get_by_id(summary.report_id)
        self.assertEqual(revised.revision_number, 2)
        self.assertEqual(revised.previous_report_id, original.id)
        self.assertEqual(report_repo.get_by_id(original.id), original)
        self.assertEqual(claim_repo.list_for_report(original.id, 1), original_claims)
        self.assertTrue(claim_repo.list_for_report(revised.id, 2))
        reviews = review_repo.list_for_project(context.project.id, workflow_run_id="source-run")
        self.assertEqual([item.verdict.value for item in reviews], ["revise", "approve"])
        self.assertEqual(reviews[0].report_id, original.id)
        self.assertEqual(reviews[1].report_id, revised.id)
        blocking = next(item for item in reviews[0].issues if item.severity == ReviewIssueSeverity.MAJOR)
        self.assertEqual(blocking.report_revision, 1)
        self.assertTrue(blocking.report_section_id)
        self.assertTrue(blocking.claim_refs)
        self.assertTrue(blocking.research_question_refs)
        self.assertEqual(source_artifacts, source_snapshot)

    def test_second_blocking_review_fails_closed_after_one_real_revision(self) -> None:
        service, context, report_repo, _, review_repo, _ = self._pipeline(_AlwaysReviseEngine())
        with self.assertRaises(ReviewError):
            service.review_for_context(context)
        reports = report_repo.list_for_project(context.project.id, workflow_run_id="source-run")
        reviews = review_repo.list_for_project(context.project.id, workflow_run_id="source-run")
        self.assertEqual(len(reports), 2)
        self.assertEqual(len(reviews), 2)
        self.assertEqual([item.verdict.value for item in reviews], ["revise", "revise"])

    def test_summary_issue_targets_exact_unit_and_claims_for_revision(self) -> None:
        service, context, report_repo, claim_repo, review_repo, _ = self._pipeline(_SummaryReviseOnceEngine())
        summary = service.review_for_context(context)
        self.assertEqual((summary.verdict, summary.revision_count), ("approve", 1))
        first_review = review_repo.list_for_project(context.project.id, workflow_run_id="source-run")[0]
        issue = next(item for item in first_review.issues if item.severity == ReviewIssueSeverity.MAJOR)
        self.assertEqual(issue.metadata["summary_unit_indices"], [0])
        self.assertTrue(issue.claim_refs)
        revised = report_repo.get_by_id(summary.report_id)
        revised_claim_ids = {item.claim_id for item in claim_repo.list_for_report(revised.id, 2)}
        self.assertTrue(set(revised.metadata["summary_units"][0]["claim_ids"]) <= revised_claim_ids)

    def test_replay_review_and_revision_are_replay_owned_with_source_authority(self) -> None:
        service, context, report_repo, claim_repo, review_repo, source_artifacts = self._pipeline(_ReviseOnceEngine(), replay=True)
        source_snapshot = copy.deepcopy(source_artifacts)
        summary = service.review_for_context(context)
        report = report_repo.get_by_id(summary.report_id)
        claims = claim_repo.list_for_report(report.id, report.revision_number)
        self.assertEqual(report.workflow_run_id, "replay-run")
        self.assertTrue(all(item.report_workflow_run_id == "replay-run" for item in claims))
        self.assertTrue(all(item.source_workflow_run_id == "source-run" for item in claims))
        self.assertTrue(all(item.workflow_run_id == "replay-run" for item in review_repo.list_for_project(context.project.id, workflow_run_id="replay-run")))
        self.assertEqual(source_artifacts, source_snapshot)


if __name__ == "__main__":
    unittest.main()
