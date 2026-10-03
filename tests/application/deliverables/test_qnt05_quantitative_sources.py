"""QNT-05 exact approved-revision deliverable source regressions."""

from dataclasses import replace
from types import SimpleNamespace
import unittest

from application.deliverables.service import ProjectDeliverablesService
from application.deliverables.store import InMemoryPdfStore
from application.deliverables.quantitative_sources import (
    QuantitativeDeliverableSourceError,
    approved_quantitative_sources,
)
from domain.quantitative.workflow import QuantitativeStudyProjection
from application.methods.quantitative.pin import REVIEW_PIN, REVIEW_VERSION
from application.quantitative.workflow import CMF_QUANTITATIVE_WORKFLOW_ID
from tests.application.quantitative import test_qnt04_review as qnt04_fixture
from tests.api.ui import test_prf06f_presentation_ui as presentation_fixture


class _Projects:
    def __init__(self, project_id):
        self.project = SimpleNamespace(id=project_id, owner_principal_id="owner")

    def get_project(self, project_id):
        if project_id != self.project.id:
            raise ValueError("missing project")
        return self.project


class _Workflows:
    def __init__(self, project_id, run_id):
        self.run = SimpleNamespace(id=run_id, project_id=project_id,
                                   workflow_template_id=CMF_QUANTITATIVE_WORKFLOW_ID)

    def list_workflow_runs_for_project(self, project_id):
        return [self.run] if project_id == self.run.project_id else []

    def get_task_results(self, run_id):
        return {REVIEW_PIN: REVIEW_VERSION} if run_id == self.run.id else {}


class _PdfRenderer:
    def render(self, document):
        return b"%PDF-1.4\n" + document.source_id.encode() + document.source_version.encode()


class _EmptyReports:
    def list_reports_for_project(self, _project_id):
        return []


class _LoadOverrideState:
    def __init__(self, delegate, overrides):
        self.delegate = delegate
        self.overrides = overrides

    def list_for_run(self, *args, **kwargs):
        return self.delegate.list_for_run(*args, **kwargs)

    def require_record_scope(self, *args, **kwargs):
        return self.delegate.require_record_scope(*args, **kwargs)

    def load(self, record_id, **kwargs):
        return self.overrides.get(record_id, self.delegate.load(record_id, **kwargs))


class QuantitativeApprovedDeliverableSourceTests(unittest.TestCase):
    def setUp(self):
        fixture = qnt04_fixture.Qnt04ReviewTests(
            methodName="test_approved_revision_binds_exact_sources_and_replay_is_idempotent")
        fixture.setUp()
        self.fixture = fixture
        self.review, self.revision = fixture.service.review(
            project_id=fixture.project_id, run_id=fixture.run_id, state=fixture.state)
        fixture.state_service.persist(
            QuantitativeStudyProjection(
                "study-qnt05", fixture.project_id, fixture.run_id,
                "QNT-05 synthetic study", "offline", "COMPLETED",
                revision=1, fingerprint="study-fingerprint"),
            record_id="study-qnt05", project_id=fixture.project_id,
            run_id=fixture.run_id)

    def _sources(self):
        return approved_quantitative_sources(
            state=self.fixture.state_service, project_id=self.fixture.project_id,
            run_id=self.fixture.run_id)

    def _service(self):
        pptx = presentation_fixture._Renderer()
        service = ProjectDeliverablesService(
            projects=_Projects(self.fixture.project_id),
            workflows=_Workflows(self.fixture.project_id, self.fixture.run_id),
            reports=_EmptyReports(), reviews=None, quantitative_state=self.fixture.state_service,
            store=InMemoryPdfStore(), renderer=_PdfRenderer(),
            presentation_jobs=presentation_fixture._Jobs(), pptx_renderer=pptx)
        return service, pptx

    def test_only_exact_approved_revision_becomes_source(self):
        documents = self._sources()
        self.assertEqual(len(documents), 1)
        document = documents[0]
        self.assertEqual(document.source_id, self.revision.revision_id)
        self.assertEqual(document.source_version, self.revision.fingerprint)
        self.assertEqual(document.status, "Схвалено")
        self.assertEqual(document.study_id, "study-qnt05")
        self.assertEqual(document.title, "Synthetic report")
        self.assertTrue(document.tables)
        self.assertEqual(document.tables[0].rows[0][1], "42")
        self.assertIn("Interpret the synthetic sample cautiously.", document.limitations)

    def test_no_approved_revision_means_no_canonical_source(self):
        empty = qnt04_fixture.Qnt04ReviewTests(
            methodName="test_approved_revision_binds_exact_sources_and_replay_is_idempotent")
        empty.setUp()
        self.assertEqual(approved_quantitative_sources(
            state=empty.state_service, project_id=empty.project_id,
            run_id=empty.run_id), [])

    def test_stale_approved_revision_fails_closed(self):
        stale = replace(self.revision, revision_id="stale-revision",
                        dataset_fingerprint="foreign-dataset")
        self.fixture.state_service.persist(
            stale, record_id=stale.revision_id, project_id=self.fixture.project_id,
            run_id=self.fixture.run_id, accepted=True)
        with self.assertRaisesRegex(QuantitativeDeliverableSourceError,
                                    "Review binding is inconsistent"):
            self._sources()

    def test_nonapproved_review_and_stale_result_fail_closed(self):
        from domain.reviews.review_verdict import ReviewVerdict

        for label, overrides in (
            ("review", {self.review.review_id: replace(
                self.review, verdict=ReviewVerdict.REVISE)}),
            ("result", {"stat-result": replace(
                self.fixture.state_service.load(
                    "stat-result", project_id=self.fixture.project_id),
                dataset_fingerprint="replaced-dataset")}),
        ):
            with self.subTest(label=label):
                with self.assertRaises(QuantitativeDeliverableSourceError):
                    approved_quantitative_sources(
                        state=_LoadOverrideState(self.fixture.state_service, overrides),
                        project_id=self.fixture.project_id, run_id=self.fixture.run_id)

    def test_stale_finding_insight_review_and_method_bindings_fail_closed(self):
        cases = (
            {"revision_id": "stale-finding", "finding_generation_fingerprint": "other"},
            {"revision_id": "stale-insight", "insight_generation_fingerprint": "other"},
            {"revision_id": "stale-review", "review_fingerprint": "other"},
            {"revision_id": "other-method", "method_version": "DESK/1"},
        )
        for values in cases:
            with self.subTest(values=values):
                fixture = qnt04_fixture.Qnt04ReviewTests(
                    methodName="test_approved_revision_binds_exact_sources_and_replay_is_idempotent")
                fixture.setUp()
                _, revision = fixture.service.review(
                    project_id=fixture.project_id, run_id=fixture.run_id,
                    state=fixture.state)
                fixture.state_service.persist(
                    QuantitativeStudyProjection(
                        "study", fixture.project_id, fixture.run_id,
                        "Study", "", "COMPLETED", fingerprint="study-fp"),
                    record_id="study", project_id=fixture.project_id,
                    run_id=fixture.run_id)
                stale = replace(revision, **values)
                fixture.state_service.persist(
                    stale, record_id=stale.revision_id,
                    project_id=fixture.project_id, run_id=fixture.run_id,
                    accepted=True)
                with self.assertRaises(QuantitativeDeliverableSourceError):
                    approved_quantitative_sources(
                        state=fixture.state_service, project_id=fixture.project_id,
                        run_id=fixture.run_id)

    def test_cross_run_authority_fails_closed(self):
        foreign = replace(self.revision, revision_id="foreign-revision",
                          review_id="foreign-review")
        self.fixture.state_service.persist(
            self.review, record_id="foreign-review", project_id=self.fixture.project_id,
            run_id="foreign-run", accepted=True)
        self.fixture.state_service.persist(
            foreign, record_id=foreign.revision_id, project_id=self.fixture.project_id,
            run_id=self.fixture.run_id, accepted=True)
        with self.assertRaisesRegex(QuantitativeDeliverableSourceError,
                                    "authority is unavailable"):
            self._sources()

    def test_pdf_and_worker_pptx_are_immutable_and_bound_to_revision(self):
        service, pptx_renderer = self._service()
        source_id = self.revision.revision_id
        catalog = service.catalog(self.fixture.project_id, owner_id="owner")
        self.assertEqual(len(catalog.quantitative), 1)
        pdf = service.generate(self.fixture.project_id, "QUANTITATIVE", source_id,
                               owner_id="owner")
        self.assertEqual(pdf.source_version, self.revision.fingerprint)
        first = service.download(self.fixture.project_id, "QUANTITATIVE", source_id,
                                 pdf.id, owner_id="owner")[1]
        second = service.download(self.fixture.project_id, "QUANTITATIVE", source_id,
                                  pdf.id, owner_id="owner")[1]
        self.assertEqual(first, second)
        job = service.schedule_presentation(
            self.fixture.project_id, "QUANTITATIVE", source_id, owner_id="owner")
        self.assertEqual(job.source_version, self.revision.fingerprint)
        self.assertTrue(service.process_next_presentation("worker-qnt05"))
        item = service.source(self.fixture.project_id, "QUANTITATIVE", source_id,
                              owner_id="owner")
        self.assertEqual(item.presentation_job.state, "completed")
        first_pptx = service.download_presentation(
            self.fixture.project_id, "QUANTITATIVE", source_id, item.pptx.id,
            owner_id="owner")[1]
        second_pptx = service.download_presentation(
            self.fixture.project_id, "QUANTITATIVE", source_id, item.pptx.id,
            owner_id="owner")[1]
        self.assertEqual(first_pptx, second_pptx)
        self.assertEqual(pptx_renderer.calls, 1)

    def test_latest_unapproved_report_is_never_substituted(self):
        latest = replace(self.fixture.composition, composition_id="latest-composition",
                         composition_fingerprint="latest-fingerprint")
        self.fixture.state_service.persist(
            latest, record_id="latest-report-record", project_id=self.fixture.project_id,
            run_id=self.fixture.run_id)
        service, _ = self._service()
        item = service.catalog(self.fixture.project_id, owner_id="owner").quantitative[0]
        self.assertEqual(item.document.source_id, self.revision.revision_id)
        self.assertEqual(item.document.source_version, self.revision.fingerprint)
        self.assertNotEqual(item.document.source_version, latest.composition_fingerprint)


if __name__ == "__main__":
    unittest.main()
