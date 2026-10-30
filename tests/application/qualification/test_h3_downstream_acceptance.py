"""Provider-free H3 downstream acceptance through the real delivery service."""

from __future__ import annotations

import copy
import inspect
import unittest
from dataclasses import replace
from hashlib import sha256
from unittest import mock

from application.deliverables.contracts import PdfSection, PdfSourceDocument, RENDERER_VERSION
from application.deliverables.service import DeliverableFinalizationError, ProjectDeliverablesService, ReportCatalogItem
from application.deliverables.store import InMemoryPdfStore
from application.report.claim_first_report_service import ClaimFirstReportService
from application.report.h3_claim_generation import (
    H3CoverageOutcome, H3ReportInsufficientCoverage, H3ReportTechnicalError,
    generate_h3_structural_claims,
)
from application.report.h3_editorial_delivery import (
    H3EditorialError,
    H3ReviewDecision,
    build_h3_editorial_catalog,
    compose_h3_editorial,
    load_approved_h3_delivery,
    run_h3_review_cycle,
)
from application.research_scope.authoritative_scope import SCOPE_KEY
from domain.findings.insight import Insight
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template_builder import WorkflowTemplateBuilder
from application.evidence.grounding import verify_grounding
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from runtime.workflow_context import WorkflowContext
from tests.application.deliverables.test_desk_approved_finalization import _Jobs, _Renderer
from tests.application.qualification.desk_downstream_fixture import production_shaped_authority_corpus
from tests.application.report.test_h3_claim_generation import _Fixture, _scope, _valid_response
from tests.application.report.test_h3_editorial_delivery import _editorial_payload, _report
from tests.fixtures.research_brief import sample_research_brief


def _production_result(*, provider=_valid_response, repair=None, source_run="source-run", report_run="report-run"):
    corpus = production_shaped_authority_corpus()
    fixture = _Fixture()
    scopes = (
        _scope("7.8", ("2026",), "%"),
        _scope("8.7", ("2025", "2026"), "%"),
        _scope("43", ("2021",), "%"),
        _scope("48705", ("2026",), "грн"),
    )
    groups = (range(0, 5), range(5, 10), range(10, 15), range(15, 19))
    fixture.evidence = [
        replace(
            fixture.evidence[0], id=f"ev-{index}", source_id=corpus.source_ids[index % 30],
            metadata={SCOPE_KEY: scopes[min(index // 5, 3)]},
        )
        for index in range(19)
    ]
    fixture.findings = [
        replace(
            fixture.findings[0], id=corpus.finding_ids[index],
            evidence_refs=tuple(fixture.evidence[item].id for item in groups[index]),
            metadata={SCOPE_KEY: scopes[index]},
        )
        for index in range(4)
    ]
    insights = tuple(
        Insight(
            id=corpus.insight_ids[index], project_id="project-1",
            workflow_run_id=source_run, research_design_id=fixture.design.id,
            statement="Bounded interpretation", implication="Bounded implication",
            finding_refs=(fixture.findings[index % 4].id,),
            created_at="2026-01-01T00:00:00Z", research_question_refs=("rq-1",),
        )
        for index in range(5)
    )
    for item in fixture.evidence:
        item.workflow_run_id = source_run
    for item in fixture.findings:
        item.workflow_run_id = source_run
    result = generate_h3_structural_claims(
        project_id="project-1", source_workflow_run_id=source_run,
        report_workflow_run_id=report_run, design=fixture.design,
        findings=tuple(fixture.findings), insights=insights,
        evidence_by_id={item.id: item for item in fixture.evidence},
        citation_id_by_source={source_id: f"S{index + 1}" for index, source_id in enumerate(corpus.source_ids)},
        candidate_provider=provider, correction_provider=repair,
        required_research_question_ids=("rq-1",),
        required_information_need_ids=("in-1",),
    )
    return corpus, fixture, insights, result


def _domain_review(report, result, *, review_id="review-1"):
    return ReviewResult(
        id=review_id, project_id=report.project_id,
        workflow_run_id=report.workflow_run_id,
        research_design_id=report.research_design_id, report_id=report.id,
        review_attempt=1, verdict=(ReviewVerdict.APPROVE if result.decision is H3ReviewDecision.APPROVE else ReviewVerdict.REVISE),
        quality_dimensions=(), issues=(), summary=result.decision.value,
        review_method="h3-structural", created_at="2026-01-01T00:00:00Z",
        deduplication_key=review_id,
    )


def _real_report_service(*, engine, editorial_provider):
    fixture = _Fixture(); project = ProjectFactory().create("H3 qualification")
    evidence = replace(fixture.evidence[0], project_id=project.id, deduplication_key="evidence")
    finding = replace(fixture.findings[0], project_id=project.id, deduplication_key="finding")
    source_text = "E"
    source = Source(
        id="source-1", project_id=project.id, url="https://example.com/source",
        canonical_url="https://example.com/source", title="Source",
        retrieved_at="2026-01-01T00:00:00Z", retrieval_status=RetrievalStatus.ACQUIRED,
        content_text=source_text, content_checksum=sha256(source_text.encode()).hexdigest(),
        research_question_refs=("rq-1",), information_need_refs=("in-1",),
        workflow_run_refs=("source-run",), research_design_refs=(fixture.design.id,),
    )
    evidence.source_content_checksum = source.content_checksum
    evidence.source_locator = verify_grounding(source_text=source_text, excerpt="E").to_dict()
    sources = InMemorySourceRepository(); sources.create(source)
    evidences = InMemoryEvidenceRepository(); evidences.create(evidence)
    findings = InMemoryFindingRepository(); findings.create(finding)
    reports = InMemoryReportRepository(); claims = InMemoryReportClaimRepository(reports)
    template = WorkflowTemplateBuilder(id="template", name="T").add_task(
        id="report", name="Write", executor_id="report", executor_type=ExecutorType.AGENT,
    ).build()
    template.research_brief_snapshot = replace(sample_research_brief(), timeframe="")
    template.research_design_snapshot = fixture.design
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id="source-run")
    run.project_id = project.id
    context = WorkflowContext(
        project=project, workflow_run=run, workflow_template=template,
        current_task=run.tasks[0],
    )
    service = ClaimFirstReportService(
        report_claim_repository=claims, report_contract_version="desk_h3_structural_claim_v1",
        report_engine=engine, h3_editorial_provider=editorial_provider,
        finding_repository=findings, insight_repository=InMemoryInsightRepository(),
        evidence_repository=evidences, source_repository=sources,
        report_repository=reports, artifact_repository=InMemoryArtifactRepository(),
        max_findings_per_batch=10, max_chars_per_batch=10000,
    )
    return service, context, reports, claims


def _finalize(test, *, report, claims, review):
    editorial = load_approved_h3_delivery(report=report, review=review, claims=claims)
    project = type("Project", (), {"id": report.project_id, "owner_principal_id": "owner"})()
    jobs = _Jobs(); store = InMemoryPdfStore(); artifacts = InMemoryArtifactRepository()
    pdf_renderer = _Renderer(b"%PDF-1.4\n"); pptx_renderer = _Renderer(b"PK\x03\x04")
    service = ProjectDeliverablesService(
        projects=type("Projects", (), {"get_project": lambda _, project_id: project})(),
        workflows=type("Workflows", (), {"get_task_results": lambda _, run_id: {}})(),
        reports=type("Reports", (), {"list_reports_for_project": lambda _, project_id: [report]})(),
        reviews=type("Reviews", (), {"list_reviews_for_project": lambda _, project_id, **filters: [review]})(),
        quantitative_state=None, store=store, renderer=pdf_renderer,
        presentation_jobs=jobs, pptx_renderer=pptx_renderer,
        report_claims=type("Claims", (), {"list_for_report": lambda _, report_id, revision: list(claims)})(),
        artifacts=artifacts,
    )
    document = service._desk(report.project_id, {report.workflow_run_id})[0]

    def source(*args, **kwargs):
        pdf = store.find(project_id=report.project_id, method="DESK", source_id=report.id,
            source_version=document.source_version, renderer_version=RENDERER_VERSION)
        pptx = store.find(project_id=report.project_id, method="DESK", source_id=report.id,
            source_version=document.source_version, renderer_version=pptx_renderer.version,
            format="PPTX", template_version=pptx_renderer.template_version)
        return ReportCatalogItem(document, pdf, jobs.job, pptx)

    service.source = source
    pending = service.finalize_approved_review(
        project_id=report.project_id, report_id=report.id, review_id=review.id,
    )
    test.assertEqual("pptx_pending", pending["status"])
    test.assertTrue(service.process_next_presentation("h3-worker"))
    final = source()
    test.assertEqual("finalization_complete", final.finalization_state)
    return service, document, final, artifacts, jobs


class H3DownstreamAcceptanceTests(unittest.TestCase):
    def _approved(self, *, claims, limitations=(), reviews=("APPROVE",), editorial_fail=False):
        report = replace(_report(claims), limitations=tuple(limitations))
        coverage_digest = "a" * 64
        catalog = build_h3_editorial_catalog(
            report=report, claims=claims, coverage_contract_digest=coverage_digest,
        )
        editorial_calls = []

        class Editorial:
            def compose(self, request):
                editorial_calls.append(request)
                payload = _editorial_payload(
                    request,
                    bad="unknown" if editorial_fail and len(editorial_calls) == 1 else None,
                )
                revision_call = len(editorial_calls) > (2 if editorial_fail else 1)
                if revision_call:
                    payload["typed_document"]["nodes"][0]["text"] = "Уточнений показник "
                return payload

        initial = compose_h3_editorial(report=report, catalog=catalog, provider=Editorial())
        review_calls = []

        class Review:
            def review(self, request):
                review_calls.append(request)
                decision = reviews[min(len(review_calls) - 1, len(reviews) - 1)]
                return {"decision": decision, "issues": []}

        approved, result = run_h3_review_cycle(
            report=report, claims=claims, presentation=initial,
            coverage_contract_digest=coverage_digest, review_provider=Review(),
            revision_provider=Editorial(),
        )
        metadata = dict(report.metadata); metadata["h3_presentation"] = approved.to_dict()
        return replace(report, metadata=metadata), result, editorial_calls, review_calls, initial, approved

    def test_production_shaped_approve_replay_ownership_and_complete(self):
        corpus, _, insights, generated = _production_result(source_run="source-run", report_run="report-run")
        self.assertEqual((30, 19, 4, 5), corpus.cardinalities)
        self.assertEqual(4, len(generated.claims))
        self.assertEqual(5, len({ref for claim in generated.claims for ref in claim.insight_ids}))
        facts = {
            (fact.value, fact.unit, tuple(fact.periods))
            for claim in generated.claims for fact in claim.scope.numeric_facts
        }
        self.assertIn(("7.8", "%", ("2026",)), facts)
        self.assertIn(("8.7", "%", ("2025", "2026")), facts)
        self.assertTrue(any("2026" in claim.scope.periods for claim in generated.claims))
        report, result, editorial_calls, review_calls, _, _ = self._approved(claims=generated.claims)
        self.assertEqual(H3ReviewDecision.APPROVE, result.decision)
        review = _domain_review(report, result)
        _, document, final, artifacts, jobs = _finalize(self, report=report, claims=generated.claims, review=review)
        self.assertEqual(("source-run", "report-run"), (
            document.approved_delivery_provenance.source_workflow_run_id,
            document.approved_delivery_provenance.report_workflow_run_id,
        ))
        self.assertEqual(1, len(editorial_calls)); self.assertEqual(1, len(review_calls))
        self.assertEqual(3, generated.provider_attempt_count + len(editorial_calls) + len(review_calls))
        self.assertEqual(1, len(artifacts.list_for_run("report-run")))
        self.assertEqual(final.pdf.approved_delivery_provenance, final.pptx.approved_delivery_provenance)
        self.assertEqual(jobs.job.approved_delivery_provenance, document.approved_delivery_provenance)

    def test_limited_can_complete_and_limitation_survives_all_surfaces(self):
        def provider(request):
            payload = _valid_response(request)
            payload["claims"][-1]["nodes"][0]["text"] = "Погано 99 "
            return payload
        corpus, _, _, generated = _production_result(provider=provider)
        self.assertEqual((30, 19, 4, 5), corpus.cardinalities)
        self.assertEqual(H3CoverageOutcome.LIMITED, generated.coverage_outcome)
        limitation = "Обмежено: optional structural claim unavailable."
        report, result, *_ = self._approved(claims=generated.claims, limitations=(limitation,))
        review = _domain_review(report, result)
        _, document, final, _, _ = _finalize(self, report=report, claims=generated.claims, review=review)
        self.assertIn(limitation, document.limitations)
        self.assertEqual(document.approved_delivery_provenance, final.pdf.approved_delivery_provenance)
        self.assertEqual(document.approved_delivery_provenance, final.pptx.approved_delivery_provenance)

    def test_insufficient_and_technical_do_zero_downstream_work(self):
        def incomplete(request):
            payload = _valid_response(request); payload["claims"] = []
            return payload
        corpus, _, _, insufficient = _production_result(provider=incomplete)
        self.assertEqual((30, 19, 4, 5), corpus.cardinalities)
        self.assertEqual(H3CoverageOutcome.REPORT_INSUFFICIENT_COVERAGE, insufficient.coverage_outcome)
        downstream_calls = []
        foreign = _Fixture(); foreign.findings[0].workflow_run_id = "third-run"; provider_calls = []
        technical = generate_h3_structural_claims(
            project_id="project-1", source_workflow_run_id="source-run", report_workflow_run_id="report-run",
            design=foreign.design, findings=tuple(foreign.findings), insights=(),
            evidence_by_id={item.id: item for item in foreign.evidence},
            citation_id_by_source={"source-1": "S1"},
            candidate_provider=lambda request: provider_calls.append(request), correction_provider=None,
            required_research_question_ids=("rq-1",), required_information_need_ids=("in-1",),
        )
        self.assertEqual(H3CoverageOutcome.TECHNICAL_ERROR, technical.coverage_outcome)
        self.assertEqual([], provider_calls)
        for outcome in (insufficient, technical):
            if outcome.coverage_outcome in {H3CoverageOutcome.SUCCESS, H3CoverageOutcome.LIMITED}:
                downstream_calls.append(outcome)
        self.assertEqual([], downstream_calls)

        editorial_calls = []
        editorial = type("Editorial", (), {
            "compose": lambda _, request: editorial_calls.append(request),
        })()

        class InsufficientEngine:
            method_name = "h3-insufficient"
            def generate_h3_claim_candidates(self, request):
                return {"contract_version": "desk_h3_structural_claim_v1", "claims": []}
            def repair_h3_claim_candidates(self, request):
                return {"contract_version": "desk_h3_structural_claim_v1", "claims": []}

        service, context, reports, claims = _real_report_service(
            engine=InsufficientEngine(), editorial_provider=editorial,
        )
        with self.assertRaises(H3ReportInsufficientCoverage):
            service.write_for_context(context)
        self.assertEqual([], editorial_calls)
        self.assertEqual([], reports.list_for_project(context.project.id))

        class TechnicalEngine:
            method_name = "h3-technical"
            def generate_h3_claim_candidates(self, request): return _valid_response(request)
            def repair_h3_claim_candidates(self, request):
                raise AssertionError("system failure must not enter provider repair")

        service2, context2, reports2, claims2 = _real_report_service(
            engine=TechnicalEngine(), editorial_provider=editorial,
        )
        with mock.patch(
            "application.report.h3_claim_generation.render_typed_document",
            side_effect=RuntimeError("synthetic renderer failure"),
        ), self.assertRaises(H3ReportTechnicalError):
            service2.write_for_context(context2)
        self.assertEqual([], editorial_calls)
        self.assertEqual([], reports2.list_for_project(context2.project.id))

    def test_revise_approve_completes_and_second_revise_is_terminal(self):
        corpus, _, _, generated = _production_result()
        self.assertEqual((30, 19, 4, 5), corpus.cardinalities)
        claims = generated.claims
        report, result, editorial_calls, review_calls, initial, revised = self._approved(
            claims=claims, reviews=("REVISE", "APPROVE"),
        )
        self.assertEqual(H3ReviewDecision.APPROVE, result.decision)
        self.assertEqual(2, len(editorial_calls)); self.assertEqual(2, len(review_calls))
        self.assertNotEqual(initial.presentation_digest, revised.presentation_digest)
        self.assertEqual(
            tuple((node.node_type, node.owner_claim_ref, node.authority_ref) for node in initial.typed_document.nodes if node.authority_ref),
            tuple((node.node_type, node.owner_claim_ref, node.authority_ref) for node in revised.typed_document.nodes if node.authority_ref),
        )
        _finalize(self, report=report, claims=claims, review=_domain_review(report, result))

        report2, terminal, editorial2, review2, *_ = self._approved(
            claims=claims, reviews=("REVISE", "REVISE"),
        )
        self.assertEqual(H3ReviewDecision.REVISE, terminal.decision)
        self.assertEqual((2, 2), (len(editorial2), len(review2)))
        with self.assertRaises(H3EditorialError):
            load_approved_h3_delivery(
                report=report2, review=_domain_review(report2, terminal), claims=claims,
            )

    def test_h3_downstream_modules_do_not_reparse_reader_facing_prose(self):
        import application.report.h3_editorial_delivery as h3_delivery
        source = inspect.getsource(h3_delivery)
        for forbidden in (
            "numeric_normalization", "claim_scope_validation", "extract_year",
            "geography_lexicon", "metric_lexicon", "citation_marker",
        ):
            self.assertNotIn(forbidden, source)

    def test_provider_ceiling_and_structural_provenance_mutations_fail_closed(self):
        _, claims = __import__("tests.application.report.test_h3_editorial_delivery", fromlist=["_claims"])._claims()
        report, result, editorial_calls, review_calls, _, presentation = self._approved(
            claims=claims, reviews=("REVISE", "APPROVE"), editorial_fail=True,
        )
        # One editorial repair plus one revision composition and two Reviews.
        self.assertEqual(5, len(editorial_calls) + len(review_calls))
        self.assertLessEqual(2 + len(editorial_calls) + len(review_calls), 7)
        review = _domain_review(report, result)
        self.assertIsNotNone(load_approved_h3_delivery(report=report, review=review, claims=claims))
        payload = presentation.to_dict()
        mutations = {
            "report_id": "foreign-report", "revision_number": 99,
            "authority_digest": "0" * 64, "presentation_digest": "0" * 64,
            "source_workflow_run_id": "third-run", "report_workflow_run_id": "third-run",
            "claim_set_digest": "0" * 64, "coverage_contract_digest": "0" * 64,
            "ast_digest": "0" * 64, "renderer_version": "foreign-renderer",
            "render_digest": "0" * 64,
        }
        for field, value in mutations.items():
            mutated = copy.deepcopy(payload); mutated[field] = value
            mutated_report = replace(report, metadata={**report.metadata, "h3_presentation": mutated})
            with self.subTest(field=field), self.assertRaises((H3EditorialError, ValueError)):
                load_approved_h3_delivery(report=mutated_report, review=review, claims=claims)
        wrong_review = replace(review, id="foreign-review")
        self.assertNotEqual(wrong_review.id, review.id)
        project = type("Project", (), {"id": report.project_id, "owner_principal_id": "owner"})()
        jobs = _Jobs(); store = InMemoryPdfStore()
        service = ProjectDeliverablesService(
            projects=type("Projects", (), {"get_project": lambda _, project_id: project})(),
            workflows=type("Workflows", (), {"get_task_results": lambda _, run_id: {}})(),
            reports=type("Reports", (), {"list_reports_for_project": lambda _, project_id: [report]})(),
            reviews=type("Reviews", (), {"list_reviews_for_project": lambda _, project_id, **filters: [review]})(),
            quantitative_state=None, store=store, renderer=_Renderer(b"%PDF-1.4\n"),
            presentation_jobs=jobs, pptx_renderer=_Renderer(b"PK\x03\x04"),
            report_claims=type("Claims", (), {"list_for_report": lambda _, report_id, revision: list(claims)})(),
            artifacts=InMemoryArtifactRepository(),
        )
        document = service._desk(report.project_id, {report.workflow_run_id})[0]
        wrong_document = replace(
            document,
            approved_delivery_provenance=replace(
                document.approved_delivery_provenance, review_id="foreign-review",
            ),
        )
        service.source = lambda *args, **kwargs: ReportCatalogItem(wrong_document, None, None, None)
        with self.assertRaises(DeliverableFinalizationError):
            service.finalize_approved_review(
                project_id=report.project_id, report_id=report.id, review_id=review.id,
            )


if __name__ == "__main__":
    unittest.main()
