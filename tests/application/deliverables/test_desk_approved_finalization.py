from __future__ import annotations

import unittest
from unittest.mock import Mock
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from application.deliverables.contracts import PdfSection, PdfSourceDocument
from application.deliverables.presentation_jobs import PresentationJob
from application.deliverables.service import ProjectDeliverablesService, ReportCatalogItem
from application.deliverables.store import InMemoryPdfStore
from application.executors.review_executor import ReviewExecutor
from application.executors.finalization_executor import FinalizationExecutor
from application.review.review_service import ReviewSummary
from application.persistence.exceptions import AccessDeniedError
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from runtime.workflow_context import WorkflowContext
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template_builder import WorkflowTemplateBuilder
from domain.workflow_status import WorkflowStatus
from application.deliverables.desk_finalization import claim_set_digest, coverage_contract_digest
from tests.application.report.test_report_claim_contract import ReportClaimContractTests


class _Values:
    def __init__(self, values): self.values = list(values)
    def list_reports_for_project(self, project_id):
        return [item for item in self.values if item.project_id == project_id]
    def list_reviews_for_project(self, project_id, **filters):
        return [item for item in self.values if item.project_id == project_id and
                all(getattr(item, key) == value for key, value in filters.items())]


class _Claims:
    def __init__(self, claims): self.claims = claims
    def list_for_report(self, report_id, report_revision): return list(self.claims)


class _Projects:
    def __init__(self, project): self.project = project
    def get_project(self, project_id):
        if project_id != self.project.id: raise AccessDeniedError("not found")
        return self.project


class _Workflows:
    def get_task_results(self, run_id): return {}


class _DurableWorkflows(_Workflows):
    def __init__(self, run): self.run, self.version, self.results = run, 1, {}
    def get_workflow_run(self, run_id): return self.run
    def get_workflow_run_version(self, run_id): return self.version
    def get_task_results(self, run_id): return dict(self.results)
    def save_workflow_run(self, run, *, expected_version, task_results):
        self.run, self.results, self.version = run, dict(task_results), self.version + 1


class _Renderer:
    def __init__(self, magic): self.magic, self.calls, self.fail = magic, 0, False
    version = "pptx-test-v1"
    template_version = "pptx-template-v1"
    media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    def render(self, document):
        self.calls += 1
        if self.fail: raise RuntimeError("synthetic")
        return self.magic + document.source_id.encode()


class _Jobs:
    def __init__(self): self.job = None
    def find(self, **kwargs): return self.job
    def schedule(self, **kwargs):
        if self.job is None:
            now = datetime.now(timezone.utc)
            initial_state = kwargs.pop("initial_state", "pending")
            self.job = PresentationJob(id="job", state=initial_state, attempts=0,
                lease_until=None, claimed_by=None, created_at=now, updated_at=now,
                completed_deliverable_id=None, failure_code=None, **kwargs)
        return self.job
    def retry(self, job_id):
        self.job = replace(self.job, state="pptx_pending", failure_code=None)
        return self.job
    def claim_next(self, worker_id):
        if self.job is None or self.job.state not in {"pending", "pptx_pending", "retry_wait"}: return None
        self.job = replace(self.job, state="pptx_processing", attempts=self.job.attempts + 1,
                           claimed_by=worker_id,
                           lease_until=datetime.now(timezone.utc) + timedelta(seconds=30))
        return self.job
    def complete(self, job_id, worker_id, deliverable_id):
        self.job = replace(self.job, state="finalization_complete", claimed_by=None, lease_until=None,
                           completed_deliverable_id=deliverable_id)
        return True
    def fail(self, job_id, worker_id, failure_code):
        self.job = replace(self.job, state=("failed_terminal" if self.job.attempts >= 3 else "retry_wait"), claimed_by=None, lease_until=None,
                           failure_code=failure_code)
        return True
    def transition(self, job_id, *, expected, state, failure_code=None):
        if self.job and self.job.state in expected:
            self.job = replace(self.job, state=state, failure_code=failure_code)
        return self.job


class DeskApprovedFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.project = type("Project", (), {"id": "project", "owner_principal_id": "owner"})()
        self.report = Report(id="report", project_id="project", workflow_run_id="run",
            research_design_id="design", title="Report", language="en",
            sections=(ReportSection("section", "Title", "Body"),), executive_summary="Summary",
            limitations=(), created_at="2026-01-01T00:00:00Z", generation_method="test",
            finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={},
            revision_number=3, approval_status="draft",
            metadata={"structured_claim_contract": "desk_report_claim_v1",
                      "rq_coverage_contract": {"version": 1, "mode": "complete",
                                               "required_rq_ids": ["rq-1"], "excluded_rq_ids": []}})
        fixture = ReportClaimContractTests(); fixture.setUp()
        self.claim = replace(fixture.claim(), project_id="project", source_workflow_run_id="run",
                             report_workflow_run_id="run", design_id="design")
        self.review = ReviewResult(id="review", project_id="project", workflow_run_id="run",
            research_design_id="design", report_id="report", review_attempt=1,
            verdict=ReviewVerdict.APPROVE, quality_dimensions=(), issues=(), summary="ok",
            review_method="test", created_at="2026-01-01T00:01:00Z", deduplication_key="review",
            metadata={"structured_claim_contract": "desk_report_claim_v1", "report_revision": 3,
                      "claim_set_digest": claim_set_digest((self.claim,)),
                      "coverage_contract_digest": coverage_contract_digest(self.report)})
        source_version = (
            f"revision-3-review-review-approve-claims-{claim_set_digest((self.claim,))[:16]}-"
            f"coverage-{coverage_contract_digest(self.report)[:16]}"
        )
        self.document = PdfSourceDocument(project_id="project", method="DESK", run_id="run",
            study_id=None, source_id="report", source_version=source_version,
            status="Схвалено", title="Report", summary="Summary",
            sections=(PdfSection("Title", ("Body",)),), limitations=(), revision_number=3,
            approval_review_id="review", approval_decision="approve", source_run_id="run",
            claim_set_digest=claim_set_digest((self.claim,)),
            coverage_contract_digest=coverage_contract_digest(self.report))
        self.jobs = _Jobs()
        self.pdf_renderer = _Renderer(b"%PDF-1.4\n")
        self.pptx_renderer = _Renderer(b"PK\x03\x04")
        self.service = ProjectDeliverablesService(projects=_Projects(self.project), workflows=_Workflows(),
            reports=_Values([self.report]), reviews=_Values([self.review]), quantitative_state=None,
            store=InMemoryPdfStore(), renderer=self.pdf_renderer,
            presentation_jobs=self.jobs, pptx_renderer=self.pptx_renderer,
            report_claims=_Claims((self.claim,)))
        self.service.source = lambda *args, **kwargs: self._item()

    def _item(self):
        pdf = self.service.store.find(project_id="project", method="DESK", source_id="report",
            source_version=self.document.source_version, renderer_version="prf07c-reportlab-2")
        pptx = self.service.store.find(project_id="project", method="DESK", source_id="report",
            source_version=self.document.source_version, renderer_version=self.pptx_renderer.version,
            format="PPTX", template_version=self.pptx_renderer.template_version)
        return ReportCatalogItem(self.document, pdf, self.jobs.job, pptx)

    def test_exact_approval_gate_rejects_absent_revise_reject_foreign_and_conflicting(self):
        self.assertEqual(self.service._approved_desk_review(self.report, [self.review]).id, "review")
        bad = [
            [],
            [replace(self.review, verdict=ReviewVerdict.REVISE)],
            [replace(self.review, verdict=ReviewVerdict.REJECT)],
            [replace(self.review, report_id="other")],
            [self.review, replace(self.review, id="conflict", verdict=ReviewVerdict.REJECT)],
        ]
        for reviews in bad:
            with self.subTest(reviews=reviews), self.assertRaises(AccessDeniedError):
                self.service._approved_desk_review(self.report, reviews)
        with self.assertRaises(AccessDeniedError):
            self.service._approved_desk_item(replace(self._item(), document=replace(
                self.document, approval_review_id=None, approval_decision=None)))

    def test_structured_gate_rejects_wrong_revision_digest_foreign_claim_and_legacy(self):
        bad_reviews = (
            replace(self.review, metadata={**self.review.metadata, "report_revision": 2}),
            replace(self.review, metadata={**self.review.metadata, "claim_set_digest": "0" * 64}),
        )
        for review in bad_reviews:
            with self.subTest(review=review.metadata), self.assertRaises(AccessDeniedError):
                self.service._structured_authority(self.report, review)
        foreign = replace(self.claim, source_workflow_run_id="third-run")
        self.service.report_claims = _Claims((foreign,))
        with self.assertRaises(AccessDeniedError):
            self.service._structured_authority(self.report, self.review)
        self.service.report_claims = _Claims((self.claim,))
        with self.assertRaises(AccessDeniedError):
            self.service._structured_authority(
                replace(self.report, metadata={}), self.review)

    def test_finalization_is_idempotent_and_tracks_exact_approval_until_pptx_complete(self):
        first = self.service.finalize_approved_review(
            project_id="project", report_id="report", review_id="review")
        second = self.service.finalize_approved_review(
            project_id="project", report_id="report", review_id="review")
        self.assertEqual(first["status"], "pptx_pending")
        self.assertEqual(first["pdf_id"], second["pdf_id"])
        self.assertEqual(first["pptx_job_id"], second["pptx_job_id"])
        self.assertEqual((first["report_revision"], first["review_id"], first["review_decision"]),
                         ("3", "review", "approve"))
        self.assertEqual(self.pdf_renderer.calls, 1)
        self.assertEqual(self._item().finalization_state, "pptx_pending")
        self.assertTrue(self.service.process_next_presentation("worker"))
        item = self._item()
        self.assertEqual(item.finalization_state, "finalization_complete")
        self.assertEqual(item.pdf.checksum, __import__("hashlib").sha256(
            self.service.store.get(item.pdf.id)[1]).hexdigest())
        self.assertEqual(item.pptx.checksum, __import__("hashlib").sha256(
            self.service.store.get(item.pptx.id)[1]).hexdigest())
        self.assertIn("revision-3-review-review-approve", item.pdf.source_version)
        self.assertEqual(self.service.download("project", "DESK", "report", item.pdf.id,
                                               owner_id="owner")[0].id, item.pdf.id)
        self.assertEqual(self.service.download_presentation(
            "project", "DESK", "report", item.pptx.id, owner_id="owner")[0].id, item.pptx.id)

    def test_missing_or_failed_pptx_retries_without_regenerating_pdf(self):
        self.service.finalize_approved_review(project_id="project", report_id="report", review_id="review")
        self.pptx_renderer.fail = True
        self.service.process_next_presentation("worker")
        self.assertEqual(self._item().finalization_state, "pptx_retry_wait")
        self.pptx_renderer.fail = False
        state = self.service.finalize_approved_review(
            project_id="project", report_id="report", review_id="review")
        self.assertEqual(state["status"], "pptx_pending")
        self.assertEqual(self.pdf_renderer.calls, 1)
        self.service.process_next_presentation("worker")
        self.assertEqual(self._item().finalization_state, "finalization_complete")

    def test_pptx_retries_automatically_three_times_then_terminal(self):
        self.service.finalize_approved_review(project_id="project", report_id="report", review_id="review")
        self.pptx_renderer.fail = True
        for attempt in (1, 2):
            self.assertTrue(self.service.process_next_presentation("worker"))
            self.assertEqual((self.jobs.job.attempts, self.jobs.job.state), (attempt, "retry_wait"))
        self.assertTrue(self.service.process_next_presentation("worker"))
        self.assertEqual((self.jobs.job.attempts, self.jobs.job.state), (3, "failed_terminal"))
        self.assertEqual(self._item().finalization_state, "finalization_failed")
        self.assertEqual(self.pdf_renderer.calls, 1)

    def test_resume_after_pdf_and_reconcile_existing_pptx_without_duplicate(self):
        self.service.finalize_approved_review(project_id="project", report_id="report", review_id="review")
        self.assertEqual(self.jobs.job.state, "pptx_pending")
        self.assertTrue(self.service.process_next_presentation("worker"))
        pptx_id = self._item().pptx.id
        self.jobs.job = replace(self.jobs.job, state="retry_wait", completed_deliverable_id=None,
                                attempts=1)
        self.assertTrue(self.service.process_next_presentation("worker"))
        self.assertEqual(self._item().pptx.id, pptx_id)
        self.assertEqual(self.pptx_renderer.calls, 1)

    def test_review_approve_starts_finalization_and_records_nonterminal_pptx_state(self):
        review_service = Mock()
        review_service.review_for_context.return_value = ReviewSummary(
            review_id="review", verdict="approve", report_id="report", artifact_id=None,
            review_attempt=1, revision_count=0, issue_count=0)
        finalizer = Mock()
        finalizer.finalize_approved_review.return_value = {
            "status": "pptx_queued", "report_id": "report", "review_id": "review"}
        state = {}
        context = Mock()
        context.project.id = "project"
        context.current_task = None
        context.write_shared.side_effect = lambda key, value: state.__setitem__(key, value)
        ReviewExecutor(review_service=review_service, deliverable_finalizer=finalizer).run(context)
        finalizer.finalize_approved_review.assert_called_once_with(
            project_id="project", report_id="report", review_id="review")
        self.assertEqual(state["desk_deliverable_finalization"]["status"], "pptx_queued")

    def test_review_boundary_pauses_until_both_deliverables_are_complete(self):
        review_service = Mock()
        review_service.review_for_context.return_value = ReviewSummary(
            review_id="review", verdict="approve", report_id="report", artifact_id=None,
            review_attempt=1, revision_count=0, issue_count=0)
        finalizer = Mock()
        finalizer.finalize_approved_review.return_value = {
            "status": "pptx_pending", "report_id": "report", "review_id": "review"}
        run = Mock(); run.id = "run"
        context = WorkflowContext(project=self.project, workflow_template=Mock(), workflow_run=run)
        context.current_task = Mock(id="review-task", definition_id="review")
        ReviewExecutor(review_service=review_service, deliverable_finalizer=finalizer).run(context)
        context.current_task.pause.assert_called_once_with()
        context.workflow_run.pause.assert_called_once_with()

    def test_explicit_finalization_task_owns_new_workflow_pause(self):
        finalizer = Mock()
        finalizer.finalize_approved_review.return_value = {
            "status": "pptx_pending", "report_id": "report", "review_id": "review"}
        run = Mock(); run.id = "run"
        context = WorkflowContext(project=self.project, workflow_template=Mock(), workflow_run=run)
        context.write_shared("review", {"verdict": "approve", "report_id": "report",
                                        "review_id": "review"})
        context.current_task = Mock(id="finalization-task", definition_id="finalization")
        FinalizationExecutor(finalizer).run(context)
        context.current_task.pause.assert_called_once_with()
        context.workflow_run.pause.assert_called_once_with()

    def test_terminal_workflow_is_settled_only_after_pptx_success_or_exhaustion(self):
        template = (WorkflowTemplateBuilder(id="t", name="T")
                    .add_task(id="review", name="Review", executor_id="finalization",
                              executor_type=ExecutorType.AGENT).build())
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id="run")
        run.project_id = "project"; run.ready(); run.start()
        task = run.tasks[0]; task.ready(); task.start(); task.pause(); run.pause()
        workflows = _DurableWorkflows(run); self.service.workflows = workflows
        completed = replace(self.jobs.schedule(
            project_id="project", method="DESK", run_id="run", study_id=None,
            source_id="report", source_version=self.document.source_version,
            status_snapshot="Схвалено", template_version="t", renderer_version="r",
            initial_state="finalization_complete", report_revision=3, review_id="review",
            source_run_id="run", claim_set_digest=self.document.claim_set_digest,
            coverage_contract_digest=self.document.coverage_contract_digest),
            state="finalization_complete", completed_deliverable_id="pptx")
        self.service._settle_structured_workflow(completed)
        self.assertEqual(workflows.run.status, WorkflowStatus.COMPLETED)
        self.assertEqual(workflows.results["desk_deliverable_finalization"]["status"],
                         "finalization_complete")


if __name__ == "__main__":
    unittest.main()
