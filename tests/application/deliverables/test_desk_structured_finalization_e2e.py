"""Provider-free structured Desk Report -> Review -> PDF/PPTX acceptance."""

from __future__ import annotations

import copy
import unittest

from application.deliverables.contracts import PdfSection, PdfSourceDocument, RENDERER_VERSION
from application.deliverables.service import ProjectDeliverablesService, ReportCatalogItem
from application.deliverables.store import InMemoryPdfStore
from application.replay.desk_downstream_replay import REPLAY_KEY
from infrastructure.review.deterministic_review_engine import DeterministicReviewEngine
from tests.application.deliverables.test_desk_approved_finalization import _Jobs, _Renderer
from tests.application.review.test_claim_aware_review import (
    ClaimAwareReviewPipelineTests,
    _ReviseOnceEngine,
)


class _Projects:
    def __init__(self, project): self.project = project
    def get_project(self, project_id):
        if project_id != self.project.id: raise KeyError(project_id)
        return self.project


class _Reports:
    def __init__(self, repository): self.repository = repository
    def list_reports_for_project(self, project_id): return self.repository.list_for_project(project_id)


class _Reviews:
    def __init__(self, repository): self.repository = repository
    def list_reviews_for_project(self, project_id, **filters):
        return self.repository.list_for_project(project_id, **filters)


class _Workflows:
    def __init__(self, replay): self.replay = replay
    def get_task_results(self, run_id): return ({REPLAY_KEY: self.replay} if self.replay else {})


class StructuredDeskFinalizationE2ETests(unittest.TestCase):
    def _run(self, semantic_engine, *, replay=False):
        pipeline = ClaimAwareReviewPipelineTests()
        review_service, context, reports, claims, reviews, source_artifacts = pipeline._pipeline(
            semantic_engine, replay=replay)
        source_snapshot = copy.deepcopy(source_artifacts)
        summary = review_service.review_for_context(context)
        report = reports.get_by_id(summary.report_id)
        review = reviews.get_by_id(summary.review_id)
        replay_state = ({"source_workflow_run_id": "source-run"} if replay else None)
        jobs = _Jobs(); pdf_renderer = _Renderer(b"%PDF-1.4\n"); pptx_renderer = _Renderer(b"PK\x03\x04")
        service = ProjectDeliverablesService(
            projects=_Projects(context.project), workflows=_Workflows(replay_state),
            reports=_Reports(reports), reviews=_Reviews(reviews), quantitative_state=None,
            store=InMemoryPdfStore(), renderer=pdf_renderer, presentation_jobs=jobs,
            pptx_renderer=pptx_renderer, report_claims=claims,
        )
        authority = service._structured_authority(report, review)

        def source(*args, **kwargs):
            document = PdfSourceDocument(
                project_id=report.project_id, method="DESK", run_id=report.workflow_run_id,
                study_id=None, source_id=report.id, source_version=authority.source_version,
                status="Схвалено", title=report.title, summary=report.executive_summary,
                sections=tuple(PdfSection(item.title, (item.content,), item.citation_ids)
                               for item in report.sections), limitations=report.limitations,
                revision_number=report.revision_number, previous_report_id=report.previous_report_id,
                approval_review_id=review.id, approval_decision="approve",
                source_run_id=authority.source_run_id,
                claim_set_digest=authority.claim_set_digest,
                coverage_contract_digest=authority.coverage_contract_digest,
            )
            pdf = service.store.find(project_id=report.project_id, method="DESK",
                source_id=report.id, source_version=authority.source_version,
                renderer_version=RENDERER_VERSION)
            pptx = service.store.find(project_id=report.project_id, method="DESK",
                source_id=report.id, source_version=authority.source_version,
                renderer_version=pptx_renderer.version, format="PPTX",
                template_version=pptx_renderer.template_version)
            return ReportCatalogItem(document, pdf, jobs.job, pptx)

        service.source = source
        pending = service.finalize_approved_review(
            project_id=report.project_id, report_id=report.id, review_id=review.id)
        self.assertEqual(pending["status"], "pptx_pending")
        self.assertTrue(service.process_next_presentation("worker"))
        item = source()
        self.assertEqual(item.finalization_state, "finalization_complete")
        self.assertIsNotNone(item.pdf); self.assertIsNotNone(item.pptx)
        self.assertEqual(item.pdf.source_version, item.pptx.source_version)
        self.assertEqual(item.pdf.source_version, authority.source_version)
        self.assertEqual(source_artifacts, source_snapshot)
        return report, review, authority, source_artifacts

    def test_normal_claim_first_review_approve_both_deliverables(self):
        report, review, authority, _ = self._run(DeterministicReviewEngine())
        self.assertEqual(review.report_id, report.id)
        self.assertEqual(authority.report_revision, report.revision_number)

    def test_replay_29_50_5_5_is_replay_owned_and_source_immutable(self):
        report, review, authority, source = self._run(DeterministicReviewEngine(), replay=True)
        self.assertEqual(tuple(map(len, source)), (29, 50, 5, 5))
        self.assertEqual((authority.source_run_id, authority.report_run_id),
                         ("source-run", "replay-run"))
        self.assertEqual((report.workflow_run_id, review.workflow_run_id),
                         ("replay-run", "replay-run"))

    def test_revise_then_approve_finalizes_only_revised_revision(self):
        report, review, authority, _ = self._run(_ReviseOnceEngine())
        self.assertEqual((report.revision_number, review.metadata["report_revision"]), (2, 2))
        self.assertEqual(authority.report_revision, 2)


if __name__ == "__main__":
    unittest.main()
