from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from application.report.h3_claim_generation import generate_h3_structural_claims
from application.report.h3_editorial_delivery import (
    H3EditorialError, H3ReviewDecision, build_h3_canonical_delivery,
    build_h3_editorial_catalog, compose_h3_editorial,
    deterministic_h3_pre_review, load_approved_h3_delivery, make_h3_delivery_artifact,
    run_h3_review_cycle,
)
from application.report.typed_rendering import H3_CONTRACT_VERSION
from application.deliverables.contracts import PdfSection, PdfSourceDocument, RENDERER_VERSION
from application.deliverables.service import ProjectDeliverablesService, ReportCatalogItem
from application.deliverables.store import InMemoryPdfStore
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from tests.application.deliverables.test_desk_approved_finalization import _Jobs, _Renderer
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.reports.report import Report
from tests.application.report.test_h3_claim_generation import _Fixture, _valid_response


def _claims():
    fixture = _Fixture(two=True)
    result = generate_h3_structural_claims(
        project_id="project-1", source_workflow_run_id="source-run",
        report_workflow_run_id="report-run", design=fixture.design,
        findings=tuple(fixture.findings), insights=(),
        evidence_by_id={item.id: item for item in fixture.evidence},
        citation_id_by_source={"source-1": "S1", "source-2": "S2"},
        candidate_provider=_valid_response, correction_provider=None,
        required_research_question_ids=("rq-1", "rq-2"),
        required_information_need_ids=("in-1", "in-2"),
    )
    return fixture, result.claims


def _report(claims):
    return Report(
        id="report-1", project_id="project-1", workflow_run_id="report-run",
        research_design_id="design-1", title="Report", language="uk", sections=(),
        executive_summary="", limitations=(), created_at="2026-01-01T00:00:00Z",
        generation_method="claim-first:h3-structural",
        finding_refs=tuple(ref for claim in claims for ref in claim.finding_ids),
        insight_refs=(), evidence_refs=tuple(ref for claim in claims for ref in claim.evidence_ids),
        citation_registry={}, deduplication_key="report-1", revision_number=1,
        metadata={"structured_claim_contract": H3_CONTRACT_VERSION},
    )


def _editorial_payload(request, *, report_id="report-1", bad=None):
    catalog = request["authority_catalog"]
    claim_id = next(iter(catalog["claims"]))
    fact_ref = next(iter(catalog["facts"]))
    period_ref = next(iter(catalog["periods"]))
    nodes = [
        {"node_id": "n1", "node_type": "TEXT", "owner_claim_ref": None, "text": "Показник ", "authority_ref": None, "presentation_variant": None},
        {"node_id": "n2", "node_type": "FACT_REF", "owner_claim_ref": claim_id, "text": None, "authority_ref": fact_ref, "presentation_variant": "value_with_unit"},
        {"node_id": "n3", "node_type": "TEXT", "owner_claim_ref": None, "text": " у ", "authority_ref": None, "presentation_variant": None},
        {"node_id": "n4", "node_type": "PERIOD_REF", "owner_claim_ref": claim_id, "text": None, "authority_ref": period_ref, "presentation_variant": "year"},
    ]
    if bad == "number":
        nodes[0]["text"] = "Показник 99 "
    if bad == "unknown":
        nodes[1]["authority_ref"] = "foreign-fact"
    return {"contract_version": H3_CONTRACT_VERSION, "typed_document": {
        "contract_version": H3_CONTRACT_VERSION, "document_id": "report-1",
        "owner_id": report_id, "nodes": nodes,
    }}


class H3EditorialDeliveryTests(unittest.TestCase):
    def setUp(self):
        _, self.claims = _claims(); self.report = _report(self.claims)
        self.catalog = build_h3_editorial_catalog(
            report=self.report, claims=self.claims, coverage_contract_digest="coverage-1",
        )

    def test_direct_approve_pre_review_and_canonical_delivery(self):
        presentation = compose_h3_editorial(
            report=self.report, catalog=self.catalog,
            provider=type("P", (), {"compose": lambda _, request: _editorial_payload(request)})(),
        )
        deterministic_h3_pre_review(report=self.report, claims=self.claims, presentation=presentation, coverage_contract_digest="coverage-1")
        review_provider = type("R", (), {"review": lambda _, request: {"decision": "APPROVE", "issues": []}})()
        approved, review = run_h3_review_cycle(
            report=self.report, claims=self.claims, presentation=presentation,
            coverage_contract_digest="coverage-1", review_provider=review_provider,
        )
        delivery = build_h3_canonical_delivery(report=self.report, claims=self.claims, presentation=approved, review=review, coverage_contract_digest="coverage-1")
        self.assertEqual(review.decision, H3ReviewDecision.APPROVE)
        self.assertEqual(delivery["markdown"], presentation.rendered_presentation)
        self.assertEqual(delivery["claim_set_digest"], self.catalog.claim_set_digest)
        self.assertEqual(make_h3_delivery_artifact(kind="pdf", delivery=delivery, content=b"pdf").provenance["ast_digest"], presentation.ast_digest)
        self.assertEqual(make_h3_delivery_artifact(kind="pptx", delivery=delivery, content=b"pptx").kind, "pptx")

    def test_provider_unknown_ref_and_numeric_text_are_repairable_once(self):
        calls = []
        class Provider:
            def compose(self, request):
                calls.append(request)
                return _editorial_payload(request, bad="unknown" if len(calls) == 1 else None)
        presentation = compose_h3_editorial(report=self.report, catalog=self.catalog, provider=Provider())
        self.assertEqual(len(calls), 2)
        self.assertEqual(presentation.report_id, "report-1")

    def test_editorial_initial_and_repair_schema_are_identical(self):
        calls = []
        class Provider:
            def compose(self, request):
                calls.append(request)
                return _editorial_payload(request, bad="unknown" if len(calls) == 1 else None)
        compose_h3_editorial(report=self.report, catalog=self.catalog, provider=Provider())
        self.assertEqual(calls[0]["response_schema"], calls[1]["response_schema"])
        self.assertEqual(calls[0]["purpose"], "editorial")

    def test_review_invalid_decision_and_issue_shape_have_exact_paths(self):
        from application.report.h3_editorial_delivery import _review_once
        class BadDecision:
            def review(self, request): return {"decision": "MAYBE", "issues": []}
        with self.assertRaises(H3EditorialError) as decision:
            _review_once(BadDecision(), self.report, compose_h3_editorial(
                report=self.report, catalog=self.catalog,
                provider=type("P", (), {"compose": lambda _, request: _editorial_payload(request)})(),
            ))
        self.assertEqual(decision.exception.field_path, "decision")

    def test_editorial_invalid_node_type_reports_exact_path_and_repairs_once(self):
        calls = []
        class Provider:
            def compose(self, request):
                calls.append(request)
                payload = _editorial_payload(request)
                if len(calls) == 1:
                    payload["typed_document"]["nodes"][1]["node_type"] = "UNKNOWN"
                return payload
        presentation = compose_h3_editorial(
            report=self.report, catalog=self.catalog, provider=Provider(),
        )
        self.assertEqual(presentation.report_id, "report-1")
        self.assertEqual(len(calls), 2)

    def test_editorial_missing_node_field_is_exact_and_fail_closed(self):
        payload = _editorial_payload({"authority_catalog": self.catalog.authority.to_canonical_dict()})
        del payload["typed_document"]["nodes"][1]["authority_ref"]
        with self.assertRaises(H3EditorialError) as captured:
            from application.report.h3_editorial_delivery import _decode_editorial_document
            _decode_editorial_document(payload)
        self.assertEqual(captured.exception.field_path, "typed_document.nodes[1].authority_ref")

    def test_deterministic_provenance_failure_does_not_repair(self):
        calls = []
        class Provider:
            def compose(self, request):
                calls.append(request); return _editorial_payload(request, report_id="foreign-report")
        with self.assertRaises(H3EditorialError) as captured:
            compose_h3_editorial(report=self.report, catalog=self.catalog, provider=Provider())
        self.assertEqual(captured.exception.code, "h3_presentation_report_ownership")
        self.assertEqual(len(calls), 1)

    def test_presentation_reload_and_provenance_mutations_fail(self):
        presentation = compose_h3_editorial(report=self.report, catalog=self.catalog, provider=type("P", (), {"compose": lambda _, request: _editorial_payload(request)})())
        payload = presentation.to_dict()
        restored = type(presentation).from_dict(payload)
        deterministic_h3_pre_review(report=self.report, claims=self.claims, presentation=restored, coverage_contract_digest="coverage-1")
        for field in ("authority_digest", "claim_set_digest", "coverage_contract_digest", "ast_digest", "render_digest", "presentation_digest"):
            mutated = dict(payload); mutated[field] = "x"
            with self.subTest(field=field), self.assertRaises(H3EditorialError):
                deterministic_h3_pre_review(report=self.report, claims=self.claims, presentation=type(presentation).from_dict(mutated), coverage_contract_digest="coverage-1")

    def test_revise_approve_and_second_revise_is_terminal(self):
        presentation = compose_h3_editorial(report=self.report, catalog=self.catalog, provider=type("P", (), {"compose": lambda _, request: _editorial_payload(request)})())
        class Review:
            def __init__(self): self.calls = 0
            def review(self, request):
                self.calls += 1
                return {"decision": "REVISE" if self.calls == 1 else "APPROVE", "issues": []}
        revised, result = run_h3_review_cycle(
            report=self.report, claims=self.claims, presentation=presentation,
            coverage_contract_digest="coverage-1", review_provider=Review(),
            revision_provider=type("P", (), {"compose": lambda _, request: _editorial_payload(request)})(),
        )
        self.assertEqual(result.decision, H3ReviewDecision.APPROVE)
        self.assertEqual(result.provider_call_count, 3)

        class RejectingReview:
            def review(self, request): return {"decision": "REVISE", "issues": []}
        _, terminal = run_h3_review_cycle(
            report=self.report, claims=self.claims, presentation=presentation,
            coverage_contract_digest="coverage-1", review_provider=RejectingReview(),
            revision_provider=type("P", (), {"compose": lambda _, request: _editorial_payload(request)})(),
        )
        self.assertEqual(terminal.decision, H3ReviewDecision.REVISE)

    def test_foreign_claim_and_lineage_are_rejected(self):
        foreign = replace(self.claims[0], source_workflow_run_id="third-run")
        with self.assertRaises(H3EditorialError):
            build_h3_editorial_catalog(report=self.report, claims=(foreign, self.claims[1]), coverage_contract_digest="coverage-1")

    def test_real_deliverables_service_completes_h3_pdf_and_pptx(self):
        catalog = build_h3_editorial_catalog(
            report=self.report, claims=self.claims,
            coverage_contract_digest="a" * 64,
        )
        provider_calls = []
        presentation = compose_h3_editorial(
            report=self.report, catalog=catalog,
            provider=type("P", (), {"compose": lambda _, request: (
                provider_calls.append(request) or _editorial_payload(request)
            )})(),
        )
        metadata = dict(self.report.metadata)
        metadata["h3_presentation"] = presentation.to_dict()
        report = replace(self.report, metadata=metadata)
        review = ReviewResult(
            id="review-1", project_id=report.project_id,
            workflow_run_id=report.workflow_run_id,
            research_design_id=report.research_design_id, report_id=report.id,
            review_attempt=1, verdict=ReviewVerdict.APPROVE,
            quality_dimensions=(), issues=(), summary="approved",
            review_method="h3-test", created_at="2026-01-01T00:00:00Z",
            deduplication_key="review-1",
        )
        editorial = load_approved_h3_delivery(
            report=report, review=review, claims=self.claims,
        )
        project = type("Project", (), {"id": "project-1", "owner_principal_id": "owner"})()
        jobs = _Jobs()
        pdf_store = InMemoryPdfStore()
        pdf_renderer = _Renderer(b"%PDF-1.4\n")
        pptx_renderer = _Renderer(b"PK\x03\x04")
        service = ProjectDeliverablesService(
            projects=type("Projects", (), {"get_project": lambda _, project_id: project})(),
            workflows=type("Workflows", (), {"get_task_results": lambda _, run_id: {}})(),
            reports=type("Reports", (), {
                "list_reports_for_project": lambda _, project_id: [report],
            })(),
            reviews=type("Reviews", (), {
                "list_reviews_for_project": lambda _, project_id, **filters: [review],
            })(),
            quantitative_state=None, store=pdf_store, renderer=pdf_renderer,
            presentation_jobs=jobs, pptx_renderer=pptx_renderer,
            report_claims=type("Claims", (), {
                "list_for_report": lambda _, report_id, revision: list(self.claims),
            })(), artifacts=InMemoryArtifactRepository(),
        )
        catalog_document = service._desk("project-1", {report.workflow_run_id})[0]
        self.assertEqual(
            catalog_document.approved_delivery_provenance,
            editorial.provenance,
        )
        self.assertEqual(
            catalog_document.canonical_delivery.structural_provenance,
            editorial.document.structural_provenance,
        )

        def source(*args, **kwargs):
            document = PdfSourceDocument(
                project_id=report.project_id, method="DESK", run_id=report.workflow_run_id,
                study_id=None, source_id=report.id,
                source_version=editorial.provenance.presentation_digest,
                status="Схвалено", title=editorial.document.title,
                summary=" ".join(item.text for item in editorial.document.executive_summary),
                sections=tuple(PdfSection(section.title,
                    tuple(paragraph.text for paragraph in section.paragraphs),
                    tuple(key for paragraph in section.paragraphs for key in paragraph.citation_keys))
                    for section in editorial.document.sections),
                limitations=editorial.document.limitations, revision_number=report.revision_number,
                approval_review_id=review.id, approval_decision=review.verdict.value,
                source_run_id=editorial.provenance.source_workflow_run_id,
                claim_set_digest=editorial.provenance.claim_set_digest,
                coverage_contract_digest=editorial.provenance.coverage_contract_digest,
                approved_delivery_provenance=editorial.provenance,
                canonical_delivery=editorial.document,
            )
            pdf = pdf_store.find(project_id=report.project_id, method="DESK",
                source_id=report.id, source_version=document.source_version,
                renderer_version=RENDERER_VERSION)
            pptx = pdf_store.find(project_id=report.project_id, method="DESK",
                source_id=report.id, source_version=document.source_version,
                renderer_version=pptx_renderer.version, format="PPTX",
                template_version=pptx_renderer.template_version)
            return ReportCatalogItem(document, pdf, jobs.job, pptx)

        service.source = source
        pending = service.finalize_approved_review(
            project_id=report.project_id, report_id=report.id, review_id=review.id,
        )
        self.assertEqual(pending["status"], "pptx_pending")
        self.assertTrue(service.process_next_presentation("worker"))
        item = source()
        self.assertEqual(item.finalization_state, "finalization_complete")
        self.assertIsNotNone(item.pdf)
        self.assertIsNotNone(item.pptx)
        self.assertEqual(jobs.job.report_revision, report.revision_number)
        self.assertEqual(jobs.job.review_id, review.id)
        self.assertEqual(jobs.job.claim_set_digest, editorial.provenance.claim_set_digest)
        self.assertEqual(len(service.artifacts.list_for_run(report.workflow_run_id)), 1)
        self.assertEqual(len(provider_calls), 1)


if __name__ == "__main__":
    unittest.main()
