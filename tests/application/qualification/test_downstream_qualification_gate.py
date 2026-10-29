"""Package A+C provider-free downstream qualification gate."""

from __future__ import annotations

import copy
import itertools
import unittest
from dataclasses import asdict, dataclass, replace

from application.deliverables.contracts import PdfSection, PdfSourceDocument, RENDERER_VERSION
from application.deliverables.editorial_delivery import (
    EditorialDeliveryError,
    load_approved_editorial_delivery,
    render_editorial_markdown,
)
from application.deliverables.service import (
    DeliverableFinalizationError, ProjectDeliverablesService, ReportCatalogItem,
)
from application.deliverables.store import InMemoryPdfStore
from application.report.claim_numeric_composition import (
    NumericCompositionError,
    build_fact_catalog,
    compose_assertion,
)
from application.report.editorial_contract import EDITORIAL_CONTRACT_VERSION
from application.report.presentation_persistence import (
    EDITORIAL_ENVELOPE_KEY,
    REPORT_CONTRACT_KEY,
    read_presentation_report,
    report_claims_authority_digest,
)
from application.replay.desk_downstream_replay import REPLAY_KEY
from application.review.review_service import ReviewService
from api.mappers.report_mappers import report_to_response
from domain.reports.report_claim import NumericFact
from domain.reviews.review_verdict import ReviewVerdict
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_review_repository import InMemoryReviewRepository
from tests.application.deliverables.test_desk_approved_finalization import _Jobs, _Renderer
from tests.application.qualification.desk_downstream_fixture import production_shaped_authority_corpus
from tests.application.report.hybrid_claim_helpers import LegacyClaimProviderAdapter
import tests.application.review.test_presentation_review_lifecycle as lifecycle
import tests.application.report.test_presentation_integration_3a as presentation_3a


def _assertion(*segments):
    return {
        "kind": "observation", "certainty": "direct",
        "direction": "not_applicable", "segments": list(segments),
    }


def _text(value):
    return {"type": "text", "text": value}


@dataclass(frozen=True)
class QualificationRecord:
    case_name: str
    expected: str
    typed_segments: tuple[str, ...]
    rendered_segments: tuple[str, ...]
    flattened_proposition: str
    actual_numeric_tokens: tuple[str, ...]
    expected_numeric_tokens: tuple[str, ...]
    resolved_fact_refs: tuple[str, ...]
    resolved_numeric_facts: tuple[dict, ...]
    resolved_period_refs: tuple[str, ...]
    resolved_period_values: tuple[str, ...]
    result: str
    category: str


class H2QualificationMatrixTests(unittest.TestCase):
    def setUp(self):
        self.corpus = production_shaped_authority_corpus()
        self.assertEqual((30, 19, 4, 5), self.corpus.cardinalities)

    def _run(self, name, facts, periods, build, *, expected="PASS", category=""):
        catalog = build_fact_catalog(claim_id=f"claim-{name}", facts=tuple(facts), periods=tuple(periods))
        segments = build(tuple(catalog.facts), tuple(catalog.periods))
        trace = {}
        try:
            composed, selected = compose_assertion(_assertion(*segments), catalog=catalog, trace=trace)
        except NumericCompositionError as error:
            record = QualificationRecord(
                name, expected, tuple(item.get("type", "") for item in segments),
                tuple(item.get("rendered_expression", "") for item in trace.get("segment_diagnostics", ())),
                "", tuple(trace.get("actual_numeric_tokens", ())),
                tuple(trace.get("expected_numeric_tokens", ())),
                tuple(trace.get("resolved_fact_refs", ())),
                tuple(trace.get("resolved_numeric_facts", ())),
                tuple(trace.get("period_refs", ())), tuple(trace.get("resolved_period_values", ())),
                "FAIL", error.diagnostics["validator_category"],
            )
            self.assertEqual("FAIL", expected, asdict(record))
            self.assertEqual(category, record.category, asdict(record))
            return record
        record = QualificationRecord(
            name, expected, tuple(item["type"] for item in segments),
            tuple(item.get("rendered_expression", "") for item in trace["segment_diagnostics"]),
            composed["proposition"], tuple(trace["actual_numeric_tokens"]),
            tuple(trace["expected_numeric_tokens"]), tuple(trace["resolved_fact_refs"]),
            tuple(item.to_dict() for item in selected), tuple(trace["period_refs"]),
            tuple(trace["resolved_period_values"]), "PASS", "",
        )
        self.assertEqual("PASS", expected, asdict(record))
        self.assertEqual(record.actual_numeric_tokens, record.expected_numeric_tokens, asdict(record))
        return record

    def test_uniform_thirty_class_matrix(self):
        c = self.corpus.facts
        cases = (
            ("01-single-fact", (c[0],), (), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}]),
            ("02-multiple-facts", (c[0], c[1]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("03-adjacent-facts", (c[6], c[7]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("04-fact-period", (c[6],), ("2025",), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}, {"type": "period_ref", "period_ref": p[0]}]),
            ("05-period-fact", (c[6],), ("2025",), lambda f, p: [{"type": "period_ref", "period_ref": p[0]}, {"type": "fact_ref", "fact_ref": f[0]}]),
            ("06-fact-period-fact", (c[6], c[7]), ("2025",), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}, {"type": "period_ref", "period_ref": p[0]}, {"type": "fact_ref", "fact_ref": f[1]}]),
            ("07-multiple-periods", (), ("2025", "2026"), lambda f, p: [{"type": "period_ref", "period_ref": x} for x in p]),
            ("08-same-period", (replace(c[6], periods=("2025",)), replace(c[7], periods=("2025",))), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("09-different-periods", (replace(c[6], periods=("2025",)), replace(c[7], periods=("2026",))), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("10-first-period-second-empty", (replace(c[6], periods=("2025",)), c[6]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("11-first-empty-second-period", (c[6], replace(c[7], periods=("2025",))), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("12-both-empty", (c[6], replace(c[7], periods=())), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("13-multi-period-fact", (c[1],), (), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}]),
            ("14-multi-period-matching-ref", (c[1],), ("2026",), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}, {"type": "period_ref", "period_ref": p[0]}]),
            ("15-unsupported-period-ref", (c[1],), (), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}, {"type": "period_ref", "period_ref": "period_missing"}], "FAIL", "period_ref_invalid"),
            ("16-same-geography", (c[0], replace(c[1], geography=("україна",))), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("17-different-geography", (c[0], c[7]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("18-metric-present-empty", (c[0], c[6]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("19-population-present-empty", (c[0], c[1]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in f]),
            ("20-decimal-comma-percent", (c[0],), (), lambda f, p: [_text("Частка "), {"type": "fact_ref", "fact_ref": f[0]}]),
            ("21-production-decimals", (c[0], c[1]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}, _text(" проти "), {"type": "fact_ref", "fact_ref": f[1]}]),
            ("22-decimal-billion", (c[3],), (), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}]),
            ("23-integer-billion", (c[4],), (), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}]),
            ("24-grouped-number", (c[5],), (), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}]),
            ("25-years-adjacent-percent", (c[0],), ("2025",), lambda f, p: [{"type": "period_ref", "period_ref": p[0]}, {"type": "fact_ref", "fact_ref": f[0]}]),
            ("26-year-between-facts", (c[0], c[1]), ("2024",), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}, {"type": "period_ref", "period_ref": p[0]}, {"type": "fact_ref", "fact_ref": f[1]}]),
            ("27-repeated-years", (replace(c[0], periods=("2025",)),), ("2025",), lambda f, p: [{"type": "fact_ref", "fact_ref": f[0]}, {"type": "period_ref", "period_ref": p[0]}]),
            ("28-initial-path", (c[9],), (), lambda f, p: [_text("Індекс "), {"type": "fact_ref", "fact_ref": f[0]}]),
            ("29-repair-path", (c[3],), (), lambda f, p: [_text("Уточнено: "), {"type": "fact_ref", "fact_ref": f[0]}]),
            ("30-ordering-permutation", (c[0], c[1], c[2]), (), lambda f, p: [{"type": "fact_ref", "fact_ref": x} for x in reversed(f)]),
        )
        records = []
        for raw in cases:
            name, facts, periods, build, *failure = raw
            records.append(self._run(name, facts, periods, build,
                expected=failure[0] if failure else "PASS", category=failure[1] if failure else ""))
        self.assertEqual(30, len(records))
        self.assertEqual(29, sum(item.result == "PASS" for item in records))
        self.assertEqual(1, sum(item.result == "FAIL" for item in records))

    def test_bounded_property_style_permutations_and_invalid_mutations(self):
        facts = self.corpus.facts[:3]
        valid_count = 0
        for size in (1, 2, 3):
            for chosen in itertools.permutations(facts, size):
                catalog = build_fact_catalog(claim_id=f"property-{size}-{valid_count}", facts=chosen, periods=("2024",))
                fact_segments = [{"type": "fact_ref", "fact_ref": ref} for ref in catalog.facts]
                period = {"type": "period_ref", "period_ref": next(iter(catalog.periods))}
                for segments in (fact_segments, [period, *fact_segments], [*fact_segments, period]):
                    first_trace, second_trace = {}, {}
                    first, first_facts = compose_assertion(_assertion(*segments), catalog=catalog, trace=first_trace)
                    second, second_facts = compose_assertion(_assertion(*copy.deepcopy(segments)), catalog=catalog, trace=second_trace)
                    self.assertEqual((first, first_facts, first_trace), (second, second_facts, second_trace))
                    self.assertEqual(first_trace["actual_numeric_tokens"], first_trace["expected_numeric_tokens"])
                    valid_count += 1
        self.assertEqual(45, valid_count)

        catalog = build_fact_catalog(claim_id="invalid-property", facts=(facts[0],), periods=("2025",))
        own_ref = next(iter(catalog.facts)); own_period = next(iter(catalog.periods))
        foreign = build_fact_catalog(claim_id="foreign", facts=(facts[0],), periods=("2025",))
        invalid = (
            ([{"type": "fact_ref", "fact_ref": "missing"}], "unknown_fact_ref"),
            ([{"type": "fact_ref", "fact_ref": next(iter(foreign.facts))}], "cross_claim_fact_ref"),
            ([{"type": "period_ref", "period_ref": "missing"}], "period_ref_invalid"),
            ([_text("2026")], "numeric_leakage"),
            ([_text("8,8%")], "numeric_leakage"),
            ([_text("10 млн грн")], "numeric_leakage"),
            ([{"type": "fact_ref", "fact_ref": own_ref}, {"type": "fact_ref", "fact_ref": own_ref}], "duplicate_fact_ref"),
            ([{"type": "period_ref", "period_ref": own_period}, {"type": "period_ref", "period_ref": "period_other"}], "period_ref_invalid"),
        )
        for segments, category in invalid:
            with self.subTest(category=category), self.assertRaises(NumericCompositionError) as captured:
                compose_assertion(_assertion(*segments), catalog=catalog)
            self.assertEqual(category, captured.exception.diagnostics["validator_category"])


class _Projects:
    def __init__(self, project): self.project = project
    def get_project(self, project_id): return self.project


class _Reports:
    def __init__(self, repository): self.repository = repository
    def list_reports_for_project(self, project_id): return self.repository.list_for_project(project_id)


class _Reviews:
    def __init__(self, repository): self.repository = repository
    def list_reviews_for_project(self, project_id, **filters): return self.repository.list_for_project(project_id, **filters)


class _Workflows:
    def __init__(self, source_run_id=None): self.source_run_id = source_run_id
    def get_task_results(self, run_id):
        return ({REPLAY_KEY: {"source_workflow_run_id": self.source_run_id}}
                if self.source_run_id else {})


class _EditorialJobs(_Jobs):
    """Provider-free scheduling boundary matching persisted provenance columns."""

    def schedule(self, **kwargs):
        provenance = kwargs.pop("approved_delivery_provenance", None)
        if provenance is not None:
            kwargs.update(
                report_revision=provenance.revision_number,
                review_id=provenance.review_id,
                source_run_id=provenance.source_workflow_run_id,
                claim_set_digest=provenance.claim_set_digest,
                coverage_contract_digest=provenance.coverage_contract_digest,
                authority_digest=provenance.authority_digest,
                presentation_digest=provenance.presentation_digest,
            )
        return super().schedule(**kwargs)


class CurrentContractQualificationE2ETests(unittest.TestCase):
    def _reviewed(self, **kwargs):
        provider = lifecycle._CitedEditorialProvider(fail_revision=kwargs.get("fail_revision", False))
        base = presentation_3a.PresentationRuntimeIntegrationTests()
        report_service, context, reports, claims, artifacts, _ = base._fixture(provider=provider)
        if kwargs.get("replay", False):
            context.workflow_run.id = "replay-run"
            context.write_shared(REPLAY_KEY, {
                "version": 1, "source_workflow_run_id": "source-run",
                "replay_attempt_id": "qualification-attempt",
            })
        h2 = LegacyClaimProviderAdapter()
        report_service._claim_candidate_provider = h2.initial(lambda authority: copy.deepcopy(authority))
        report_service._claim_correction_provider = h2.repair(lambda request: copy.deepcopy(request["authority"]))
        report_service.write_for_context(context)
        reviews = InMemoryReviewRepository()
        engine = lifecycle._PresentationEngine(
            revise_once=kwargs.get("revise_once", False),
            always_revise=kwargs.get("always_revise", False),
        )
        review_service = ReviewService(
            semantic_review_engine=engine,
            finding_repository=report_service._finding_repository,
            insight_repository=report_service._insight_repository,
            evidence_repository=report_service._evidence_repository,
            report_repository=reports, report_claim_repository=claims,
            artifact_repository=artifacts, review_repository=reviews,
            report_service=report_service, max_revision_attempts=5,
        )
        summary = review_service.review_for_context(context)
        report = reports.get_by_id(summary.report_id)
        review = reviews.get_by_id(summary.review_id)
        stored_claims = tuple(claims.list_for_report(report.id, report.revision_number))
        return provider, report_service, summary, report, review, stored_claims, context, reports, reviews, claims

    def _finalize(self, report, review, claims, context, reports, reviews):
        jobs = _EditorialJobs(); pdf_renderer = _Renderer(b"%PDF-1.4\n"); pptx_renderer = _Renderer(b"PK\x03\x04")
        stored = tuple(claims.list_for_report(report.id, report.revision_number))
        source_run_id = stored[0].source_workflow_run_id if stored and stored[0].source_workflow_run_id != report.workflow_run_id else None
        service = ProjectDeliverablesService(
            projects=_Projects(context.project), workflows=_Workflows(source_run_id), reports=_Reports(reports),
            reviews=_Reviews(reviews), quantitative_state=None, store=InMemoryPdfStore(),
            renderer=pdf_renderer, presentation_jobs=jobs, pptx_renderer=pptx_renderer,
            report_claims=claims, artifacts=InMemoryArtifactRepository(),
        )
        catalog = service._desk(report.project_id, {report.workflow_run_id})
        document = next(item for item in catalog if item.source_id == report.id)

        def source(*args, **kwargs):
            pdf = service.store.find(project_id=report.project_id, method="DESK", source_id=report.id,
                source_version=document.source_version, renderer_version=RENDERER_VERSION)
            pptx = service.store.find(project_id=report.project_id, method="DESK", source_id=report.id,
                source_version=document.source_version, renderer_version=pptx_renderer.version,
                format="PPTX", template_version=pptx_renderer.template_version)
            return ReportCatalogItem(document, pdf, jobs.job, pptx)

        service.source = source
        pending = service.finalize_approved_review(project_id=report.project_id, report_id=report.id, review_id=review.id)
        self.assertEqual("pptx_pending", pending["status"])
        self.assertTrue(service.process_next_presentation("qualification-worker"))
        final = source()
        self.assertEqual("finalization_complete", final.finalization_state)
        self.assertIsNotNone(final.pdf); self.assertIsNotNone(final.pptx)
        return document, final

    def test_editorial_approve_to_canonical_delivery_pdf_pptx(self):
        _, _, summary, report, review, stored_claims, context, reports, reviews, claims = self._reviewed()
        self.assertEqual("approve", summary.verdict)
        self.assertEqual(EDITORIAL_CONTRACT_VERSION, report.metadata[REPORT_CONTRACT_KEY])
        presentation = read_presentation_report(report, claims=stored_claims)
        delivery = load_approved_editorial_delivery(report=report, review=review, claims=stored_claims)
        response = report_to_response(report, delivery=delivery)
        markdown = render_editorial_markdown(delivery.document)
        document, final = self._finalize(report, review, claims, context, reports, reviews)
        self.assertEqual(report_claims_authority_digest(stored_claims), presentation.authority_digest)
        self.assertEqual(delivery.document.title, response.title)
        self.assertEqual(delivery.document.title, document.title)
        self.assertIn(delivery.document.title, markdown)
        self.assertEqual(delivery.provenance.presentation_digest, document.source_version)
        self.assertEqual(review.id, document.approval_review_id)
        self.assertEqual(final.pdf.source_version, final.pptx.source_version)
        self.assertNotIn("legacy", report.generation_method)

    def test_editorial_revise_once_delivers_only_exact_revised_revision(self):
        provider, _, summary, report, review, stored_claims, context, reports, reviews, claims = self._reviewed(revise_once=True)
        self.assertEqual(("approve", 1, 2), (summary.verdict, summary.revision_count, report.revision_number))
        self.assertEqual(2, len(provider.requests))
        self.assertEqual(report.id, review.report_id)
        self.assertEqual(report.revision_number, review.metadata["reviewed_revision_number"])
        initial = next(item for item in reports.list_for_project(report.project_id) if item.revision_number == 1)
        initial_claims = tuple(claims.list_for_report(initial.id, initial.revision_number))
        self.assertEqual(report_claims_authority_digest(initial_claims), report_claims_authority_digest(stored_claims))
        document, _ = self._finalize(report, review, claims, context, reports, reviews)
        self.assertEqual(2, document.revision_number)
        self.assertNotEqual(initial.id, document.source_id)

    def test_replay_keeps_source_authority_immutable_and_outputs_replay_owned(self):
        provider, service, summary, report, review, stored_claims, context, reports, reviews, claims = self._reviewed(replay=True)
        before = (
            copy.deepcopy(service._source_repository.list_for_project(context.project.id)),
            copy.deepcopy(service._evidence_repository.list_for_project(context.project.id, workflow_run_id="source-run")),
            copy.deepcopy(service._finding_repository.list_for_project(context.project.id, workflow_run_id="source-run")),
            copy.deepcopy(service._insight_repository.list_for_project(context.project.id, workflow_run_id="source-run")),
        )
        self.assertEqual({"source-run"}, {item.source_workflow_run_id for item in stored_claims})
        self.assertEqual({"replay-run"}, {item.report_workflow_run_id for item in stored_claims})
        self.assertEqual(("replay-run", "replay-run"), (report.workflow_run_id, review.workflow_run_id))
        document, _ = self._finalize(report, review, claims, context, reports, reviews)
        self.assertEqual(("source-run", "replay-run"), (
            document.approved_delivery_provenance.source_workflow_run_id,
            document.approved_delivery_provenance.report_workflow_run_id,
        ))
        after = (
            service._source_repository.list_for_project(context.project.id),
            service._evidence_repository.list_for_project(context.project.id, workflow_run_id="source-run"),
            service._finding_repository.list_for_project(context.project.id, workflow_run_id="source-run"),
            service._insight_repository.list_for_project(context.project.id, workflow_run_id="source-run"),
        )
        self.assertEqual(before, after)
        self.assertEqual(1, len(provider.requests))

    def test_second_revise_is_terminal_and_cannot_deliver_or_finalize(self):
        fixture = lifecycle.PresentationReviewLifecycleTests()
        _, _, review_service, reviews, context, reports, claims = fixture.fixture(always_revise=True)
        with self.assertRaises(Exception):
            review_service.review_for_context(context)
        persisted = reports.list_for_project(context.project.id)
        self.assertEqual([1, 2], sorted(item.revision_number for item in persisted))
        self.assertFalse(any(item.verdict == ReviewVerdict.APPROVE for item in reviews.list_for_project(context.project.id)))
        latest = max(persisted, key=lambda item: item.revision_number)
        with self.assertRaises(EditorialDeliveryError):
            load_approved_editorial_delivery(
                report=latest,
                review=reviews.list_for_project(context.project.id)[-1],
                claims=tuple(claims.list_for_report(latest.id, latest.revision_number)),
            )

    def test_approved_delivery_provenance_mutation_matrix_fails_closed(self):
        _, _, _, report, review, stored_claims, *_ = self._reviewed()
        self.assertIsNotNone(load_approved_editorial_delivery(report=report, review=review, claims=stored_claims))
        metadata_fields = (
            "approved_authority_digest", "approved_presentation_digest",
            "claim_set_digest", "coverage_contract_digest",
        )
        mutations = 0
        for field in metadata_fields:
            value = 99 if field == "approved_revision_number" else "wrong"
            mutated = replace(review, metadata={**review.metadata, field: value})
            with self.subTest(field=field), self.assertRaises(EditorialDeliveryError):
                load_approved_editorial_delivery(report=report, review=mutated, claims=stored_claims)
            mutations += 1
        for mutated in (replace(report, id="wrong-report"), replace(report, revision_number=99)):
            with self.assertRaises(EditorialDeliveryError):
                load_approved_editorial_delivery(
                    report=mutated if hasattr(mutated, "sections") else report,
                    review=mutated if hasattr(mutated, "verdict") else review,
                    claims=stored_claims,
                )
            mutations += 1
        for field, changed_claims in (
            ("source_workflow_run_id", (replace(stored_claims[0], source_workflow_run_id="wrong"), *stored_claims[1:])),
            ("report_workflow_run_id", (replace(stored_claims[0], report_workflow_run_id="wrong"), *stored_claims[1:])),
        ):
            with self.subTest(field=field), self.assertRaises(EditorialDeliveryError):
                load_approved_editorial_delivery(report=report, review=review, claims=changed_claims)
            mutations += 1
        class WrongReviewRepository:
            def list_for_project(self, project_id, **filters):
                return [replace(review, id="wrong-review")]
        service = ProjectDeliverablesService(
            projects=_Projects(type("Project", (), {
                "id": report.project_id, "owner_principal_id": "owner",
            })()),
            workflows=_Workflows(), reports=_Reports(type("Reports", (), {
                "list_for_project": lambda self, project_id: [report],
            })()),
            reviews=_Reviews(WrongReviewRepository()), quantitative_state=None,
            store=InMemoryPdfStore(), renderer=_Renderer(b"%PDF"),
            presentation_jobs=_EditorialJobs(), pptx_renderer=_Renderer(b"PK"),
            report_claims=type("Claims", (), {
                "list_for_report": lambda self, report_id, revision: list(stored_claims),
            })(), artifacts=InMemoryArtifactRepository(),
        )
        with self.assertRaises(DeliverableFinalizationError):
            service.finalize_approved_review(
                project_id=report.project_id, report_id=report.id, review_id=review.id,
            )
        mutations += 1
        self.assertEqual(9, mutations)

    def test_bounded_h2_observability_reconstructs_initial_and_repair_boundaries(self):
        fact = NumericFact("7.8", "%", "absolute", (), ("2026",), (), ())
        catalog = build_fact_catalog(claim_id="observability", facts=(fact,), periods=("2025",))
        fact_ref = next(iter(catalog.facts)); period_ref = next(iter(catalog.periods))
        trace = {}
        composed, _ = compose_assertion(_assertion(
            {"type": "fact_ref", "fact_ref": fact_ref},
            {"type": "period_ref", "period_ref": period_ref},
        ), catalog=catalog, trace=trace)
        self.assertTrue(composed["proposition"])
        for key in (
            "actual_numeric_tokens", "expected_numeric_tokens", "segment_diagnostics",
            "resolved_fact_refs", "resolved_numeric_facts", "period_refs", "resolved_period_values",
        ):
            self.assertIn(key, trace)
        failed = {}
        with self.assertRaises(NumericCompositionError):
            compose_assertion(_assertion(_text("7,9%")), catalog=catalog, trace=failed)
        self.assertEqual("failed", failed["numeric_leakage_result"])
        self.assertNotIn("7,9", str(failed))


if __name__ == "__main__":
    unittest.main()
