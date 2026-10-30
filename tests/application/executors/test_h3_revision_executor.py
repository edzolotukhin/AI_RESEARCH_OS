from __future__ import annotations

import unittest
import copy
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from application.executors.revision_executor import RevisionExecutor
from application.executors.finalization_executor import FinalizationExecutor
from application.report.claim_first_report_service import ClaimFirstReportService
from application.report.claim_contract import canonical_digest
from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
from application.report.coverage_contract import resolve_report_coverage_contract
from application.report.deduplication import DR06_RESEARCH_REPORT_TYPE, compute_report_deduplication_key
from application.report.h3_editorial_delivery import (
    H3PresentationEnvelope,
    build_h3_editorial_catalog,
    compose_h3_editorial,
)
from application.report.presentation_persistence import report_claims_authority_digest
from application.review.h3_review_branch import (
    H3ReviewBranchController, H3_REVIEW_BRANCH_KEY, H3_REVIEW_EXHAUSTED,
)
from application.review.review_service import ReviewSummary
from application.task_scheduler import TaskScheduler
from domain.project import Project
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from runtime.workflow_context import WorkflowContext
from tests.application.report.test_h3_claim_generation import _Fixture
from tests.application.report.test_h3_editorial_delivery import _claims, _editorial_payload, _report
from tests.helpers.workflow_run_builder import make_task, make_workflow_run


class _Engine:
    method_name = "unused"


class _CountingEditorialProvider:
    def __init__(self, report_id: str, *, invalid: bool = False) -> None:
        self.report_id = report_id
        self.invalid = invalid
        self.calls = 0

    def compose(self, request):
        self.calls += 1
        return _editorial_payload(
            request,
            report_id=self.report_id,
            bad="unknown" if self.invalid else None,
        )


def _review(report_id: str) -> ReviewResult:
    return ReviewResult(
        id="review-1", project_id="project-1", workflow_run_id="report-run",
        research_design_id="design-1", report_id=report_id, review_attempt=1,
        verdict=ReviewVerdict.REVISE, quality_dimensions=(), issues=(),
        summary="revise", review_method="h3-test",
        created_at="2026-01-01T00:00:00Z", deduplication_key="review-1",
    )


def _context(design, *, approve_path: bool = False) -> WorkflowContext:
    tasks = (
        make_task("report", executor_id="report", task_id="report", status=TaskStatus.COMPLETED),
        make_task("task-review-report-1", executor_id="review", task_id="review-1", depends_on=["report"], status=TaskStatus.RUNNING if approve_path else TaskStatus.COMPLETED),
        make_task("task-revise-report", executor_id="revision", task_id="revision", depends_on=["task-review-report-1"], status=TaskStatus.CREATED if approve_path else TaskStatus.RUNNING),
        make_task("task-review-report-2", executor_id="review", task_id="review-2", depends_on=["task-revise-report"], status=TaskStatus.CREATED),
        make_task("task-finalize-deliverables", executor_id="finalization", task_id="final", depends_on=["task-review-report-1", "task-revise-report", "task-review-report-2"]),
    )
    run = make_workflow_run(*tasks)
    run.id = "report-run"
    run.project_id = "project-1"
    run.ready(); run.start()
    template = type("Template", (), {
        "research_design_snapshot": design,
        "research_brief_snapshot": None,
    })()
    context = WorkflowContext(
        workflow_run=run, project=Project(id="project-1", name="Project"),
        workflow_template=template,
        current_task=next(item for item in tasks if item.id == "revision"),
    )
    context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
    return context


class H3RevisionExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture, self.authority = _claims()
        self.r1 = _report(self.authority)
        self.reports = InMemoryReportRepository()
        self.claims = InMemoryReportClaimRepository(self.reports)
        self.claims.create_with_report(self.r1, self.authority)
        self.context = _context(self.fixture.design)
        self.review = _review(self.r1.id)
        self.context.write_shared("review_1", self.review.to_dict())
        H3ReviewBranchController().reconcile(self.context)
        self.r2_id = str(uuid5(
            NAMESPACE_URL, f"h3-revision:report-run:{self.r1.id}:2",
        ))
        self.provider = _CountingEditorialProvider(self.r2_id)
        self.service = ClaimFirstReportService(
            report_claim_repository=self.claims,
            report_contract_version=H3_REPORT_CONTRACT,
            h3_editorial_provider=self.provider,
            report_engine=_Engine(),
            finding_repository=InMemoryFindingRepository(),
            insight_repository=InMemoryInsightRepository(),
            evidence_repository=InMemoryEvidenceRepository(),
            source_repository=InMemorySourceRepository(),
            report_repository=self.reports,
            artifact_repository=InMemoryArtifactRepository(),
            max_findings_per_batch=10,
            max_chars_per_batch=10_000,
        )

    def _run(self):
        RevisionExecutor(self.service).run(self.context)
        return self.reports.get_by_id(self.r2_id)

    def test_revision_executor_creates_durable_r2_from_revise1(self):
        r2 = self._run()
        self.assertIsNotNone(r2)
        self.assertNotEqual(self.r1.id, r2.id)
        self.assertEqual(2, r2.revision_number)
        self.assertEqual(self.r1.id, r2.previous_report_id)
        self.assertEqual(self.r2_id, r2.id)
        self.context.current_task.complete()
        TaskScheduler().schedule(self.context.workflow_run)
        review_two = next(item for item in self.context.workflow_run.tasks if item.id == "review-2")
        self.assertEqual(TaskStatus.READY, review_two.status)

    def test_revision_reuses_exact_r1_claim_authority(self):
        before_count = len(self.claims._claims)
        r2 = self._run()
        r1_claims = tuple(self.claims.list_for_report(self.r1.id, 1))
        r2_claims = tuple(self.claims.list_for_report(r2.id, 2))
        self.assertEqual(tuple(item.claim_id for item in r1_claims), tuple(item.claim_id for item in r2_claims))
        self.assertEqual(tuple(item.authority_digest for item in r1_claims), tuple(item.authority_digest for item in r2_claims))
        self.assertEqual(report_claims_authority_digest(r1_claims), report_claims_authority_digest(r2_claims))
        self.assertEqual(
            tuple((item.source_workflow_run_id, item.report_workflow_run_id, item.project_id, item.design_id, item.finding_ids, item.evidence_ids, item.structural_assertion) for item in r1_claims),
            tuple((item.source_workflow_run_id, item.report_workflow_run_id, item.project_id, item.design_id, item.finding_ids, item.evidence_ids, item.structural_assertion) for item in r2_claims),
        )
        self.assertEqual(before_count, len(self.claims._claims))

    def test_revision_executor_retry_is_idempotent(self):
        first = self._run()
        second = self._run()
        revisions = self.reports.list_for_project("project-1", workflow_run_id="report-run")
        self.assertEqual(first.id, second.id)
        self.assertEqual([1, 2], sorted(item.revision_number for item in revisions))
        self.assertEqual(1, self.provider.calls)
        self.assertEqual(len(self.authority), len(self.claims._memberships) // 2)

    def test_restart_after_r2_persisted_before_membership_attaches_same_authority(self):
        dedup = compute_report_deduplication_key(
            workflow_run_id="report-run", report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method=self.r1.generation_method, revision_number=2,
        )
        partial = replace(
            self.r1, id=self.r2_id, revision_number=2,
            previous_report_id=self.r1.id, deduplication_key=dedup,
            metadata={**self.r1.metadata, "revision_of": self.r1.id},
        )
        catalog = build_h3_editorial_catalog(
            report=partial, claims=self.authority,
            coverage_contract_digest=canonical_digest(
                resolve_report_coverage_contract(
                    report=self.r1, design=self.fixture.design,
                ).to_metadata()
            ),
        )
        presentation = compose_h3_editorial(
            report=partial, catalog=catalog, provider=self.provider, revision_number=2,
        )
        partial = replace(partial, metadata={**partial.metadata, "h3_presentation": presentation.to_dict()})
        self.reports.create(partial)
        calls_before_restart = self.provider.calls
        restarted_service = replace_service(self.service)
        RevisionExecutor(restarted_service).run(self.context)
        self.assertEqual(calls_before_restart, self.provider.calls)
        self.assertEqual(
            tuple(item.claim_id for item in self.authority),
            tuple(item.claim_id for item in self.claims.list_for_report(self.r2_id, 2)),
        )

    def test_unsupported_revision_authority_fails_closed(self):
        invalid = _CountingEditorialProvider(self.r2_id, invalid=True)
        self.service._h3_editorial_provider = invalid
        with self.assertRaises(Exception):
            self._run()
        self.assertIsNone(self.reports.get_by_id(self.r2_id))
        self.assertEqual(2, invalid.calls)
        self.assertEqual(len(self.authority), len(self.claims._claims))

    def test_finalization_after_approve1_resolves_exact_r1(self):
        calls = []
        self.context = _context(self.fixture.design, approve_path=True)
        summary = ReviewSummary("review-approve-1", "approve", self.r1.id, None, 1, 0, 0)
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "review-1"
        )
        H3ReviewBranchController().apply_review_result(self.context, summary)
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "final"
        )
        finalizer = type("Finalizer", (), {
            "finalize_approved_review": lambda _, **kwargs: (
                calls.append(kwargs) or {"status": "finalization_complete"}
            ),
        })()
        FinalizationExecutor(finalizer).run(self.context)
        self.assertEqual(self.r1.id, calls[0]["report_id"])
        self.assertEqual(0, self.provider.calls)
        self.assertIsNone(self.reports.get_by_id(self.r2_id))

    def test_finalization_after_approve2_resolves_exact_r2(self):
        r2 = self._run()
        summary = ReviewSummary("review-approve-2", "approve", r2.id, None, 1, 0, 0)
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "review-2"
        )
        H3ReviewBranchController().apply_review_result(self.context, summary)
        calls = []
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "final"
        )
        finalizer = type("Finalizer", (), {
            "finalize_approved_review": lambda _, **kwargs: (
                calls.append(kwargs) or {"status": "finalization_complete"}
            ),
        })()
        FinalizationExecutor(finalizer).run(self.context)
        self.assertEqual(r2.id, calls[0]["report_id"])

    def test_finalization_rejects_unapproved_r2(self):
        self._run()
        calls = []
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "final"
        )
        with self.assertRaisesRegex(RuntimeError, "h3_finalization_not_eligible"):
            FinalizationExecutor(type("Finalizer", (), {
                "finalize_approved_review": lambda _, **kwargs: calls.append(kwargs),
            })()).run(self.context)
        self.assertEqual([], calls)

    def test_h3_durable_r2_revise2_exhausts_without_r3_or_delivery(self):
        r2 = self._run()
        review_two = ReviewSummary("review-revise-2", "revise", r2.id, None, 1, 0, 0)
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "review-2"
        )
        H3ReviewBranchController().apply_review_result(self.context, review_two)
        branch = self.context.read_shared(H3_REVIEW_BRANCH_KEY)
        revisions = self.reports.list_for_project("project-1", workflow_run_id="report-run")
        finalization_calls = []

        self.assertEqual(r2.id, review_two.report_id)
        self.assertEqual(2, branch["round"])
        self.assertEqual("revise", branch["decision"])
        self.assertEqual(1, branch["revision_count"])
        self.assertFalse(branch["finalization_eligible"])
        self.assertEqual(H3_REVIEW_EXHAUSTED, branch["terminal_reason"])
        self.assertEqual(WorkflowStatus.FAILED, self.context.workflow_run.status)
        self.assertEqual([1, 2], sorted(item.revision_number for item in revisions))
        self.assertEqual(1, self.provider.calls)
        self.assertEqual([], finalization_calls)
        self.assertEqual([], self.service._artifact_repository.list_for_run("report-run"))
        final = next(item for item in self.context.workflow_run.tasks if item.id == "final")
        self.assertEqual(TaskStatus.SKIPPED, final.status)

    def test_h3_approve2_restart_finalizes_exact_durable_r2(self):
        r2 = self._run()
        review_two = ReviewSummary("review-approve-2", "approve", r2.id, None, 1, 0, 0)
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "review-2"
        )
        H3ReviewBranchController().apply_review_result(self.context, review_two)
        persisted_shared = copy.deepcopy(self.context.shared_state)
        restarted_context = WorkflowContext(
            workflow_run=copy.deepcopy(self.context.workflow_run),
            project=copy.deepcopy(self.context.project),
            workflow_template=self.context.workflow_template,
            shared_state=persisted_shared,
        )
        restarted_context.current_task = next(
            item for item in restarted_context.workflow_run.tasks if item.id == "final"
        )
        restarted_service = replace_service(self.service)
        stored = restarted_service._report_repository.get_by_id(r2.id)
        presentation = H3PresentationEnvelope.from_dict(stored.metadata["h3_presentation"])
        calls = []
        fresh_finalizer = type("Finalizer", (), {
            "finalize_approved_review": lambda _, **kwargs: (
                calls.append(kwargs) or {
                    "status": "finalization_complete",
                    "report_id": kwargs["report_id"],
                    "review_id": kwargs["review_id"],
                    "revision_number": stored.revision_number,
                    "presentation_digest": presentation.presentation_digest,
                }
            ),
        })()
        FinalizationExecutor(fresh_finalizer).run(restarted_context)

        self.assertEqual(r2.id, calls[0]["report_id"])
        self.assertEqual("review-approve-2", calls[0]["review_id"])
        self.assertEqual(2, stored.revision_number)
        self.assertEqual(r2.id, presentation.report_id)
        self.assertNotEqual(self.r1.id, presentation.report_id)
        self.assertEqual(
            report_claims_authority_digest(self.claims.list_for_report(self.r1.id, 1)),
            report_claims_authority_digest(self.claims.list_for_report(r2.id, 2)),
        )

    def test_h3_replay_revise1_r2_approve2_preserves_split_ownership(self):
        r2 = self._run()
        r1_claims = tuple(self.claims.list_for_report(self.r1.id, 1))
        r2_claims = tuple(self.claims.list_for_report(r2.id, 2))
        self.assertTrue(r1_claims)
        for claim in (*r1_claims, *r2_claims):
            self.assertEqual("source-run", claim.source_workflow_run_id)
            self.assertEqual("report-run", claim.report_workflow_run_id)
        self.assertEqual(
            tuple(item.claim_id for item in r1_claims),
            tuple(item.claim_id for item in r2_claims),
        )
        self.assertEqual(
            tuple(item.authority_digest for item in r1_claims),
            tuple(item.authority_digest for item in r2_claims),
        )
        review_two = ReviewSummary("replay-review-2", "approve", r2.id, None, 1, 0, 0)
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "review-2"
        )
        H3ReviewBranchController().apply_review_result(self.context, review_two)
        calls = []
        self.context.current_task = next(
            item for item in self.context.workflow_run.tasks if item.id == "final"
        )
        FinalizationExecutor(type("Finalizer", (), {
            "finalize_approved_review": lambda _, **kwargs: (
                calls.append(kwargs) or {"status": "finalization_complete"}
            ),
        })()).run(self.context)
        self.assertEqual(r2.id, calls[0]["report_id"])
        self.assertEqual(self.r1.id, r2.previous_report_id)

    def test_h3_revision_persists_presentation_before_membership_attachment(self):
        order = []
        original_create = self.reports.create
        original_attach = self.claims.attach_claims_to_report_revision

        def create(report):
            self.assertIn("h3_presentation", report.metadata)
            order.append("presentation_report")
            return original_create(report)

        def attach(report, claims):
            persisted = self.reports.get_by_id(report.id)
            self.assertIsNotNone(persisted)
            self.assertIn("h3_presentation", persisted.metadata)
            order.append("membership")
            return original_attach(report, claims)

        self.reports.create = create
        self.claims.attach_claims_to_report_revision = attach
        self._run()
        self.assertEqual(["presentation_report", "membership"], order)

        failing_reports = InMemoryReportRepository()
        failing_claims = InMemoryReportClaimRepository(failing_reports)
        failing_claims.create_with_report(self.r1, self.authority)
        failing_service = replace_service(self.service)
        failing_service._report_repository = failing_reports
        failing_service._report_claim_repository = failing_claims
        failing_service._h3_editorial_provider = _CountingEditorialProvider(
            self.r2_id, invalid=True,
        )
        with self.assertRaises(Exception):
            RevisionExecutor(failing_service).run(self.context)
        self.assertIsNone(failing_reports.get_by_id(self.r2_id))
        self.assertEqual([], failing_claims.list_for_report(self.r2_id, 2))


def replace_service(service: ClaimFirstReportService) -> ClaimFirstReportService:
    """Simulate a process restart while retaining durable repository instances."""
    return ClaimFirstReportService(
        report_claim_repository=service._report_claim_repository,
        report_contract_version=H3_REPORT_CONTRACT,
        h3_editorial_provider=service._h3_editorial_provider,
        report_engine=_Engine(),
        finding_repository=service._finding_repository,
        insight_repository=service._insight_repository,
        evidence_repository=service._evidence_repository,
        source_repository=service._source_repository,
        report_repository=service._report_repository,
        artifact_repository=service._artifact_repository,
        max_findings_per_batch=10,
        max_chars_per_batch=10_000,
    )


if __name__ == "__main__":
    unittest.main()
