from __future__ import annotations

import copy
import inspect
import unittest
from dataclasses import replace
from hashlib import sha256
from unittest import mock

from application.report.h3_claim_generation import (
    H3ClaimOutcome, H3CoverageOutcome, generate_h3_structural_claims,
    restore_h3_claim_structure,
)
from application.report.typed_rendering import H3_CONTRACT_VERSION
from application.report.claim_first_report_service import ClaimFirstReportService
from application.evidence.grounding import verify_grounding
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.reports.report_claim import ReportClaim, ReportClaimContractError
from application.research_scope.authoritative_scope import SCOPE_KEY, SCOPE_VERSION
from infrastructure.persistence.memory.in_memory_report_claim_repository import InMemoryReportClaimRepository
from infrastructure.persistence.memory.in_memory_report_repository import InMemoryReportRepository
from domain.reports.report import Report
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.sources.source import Source
from domain.sources.retrieval_status import RetrievalStatus
from domain.workflow_template_builder import WorkflowTemplateBuilder
from domain.value_objects.executor_type import ExecutorType
from infrastructure.persistence.memory.in_memory_artifact_repository import InMemoryArtifactRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from runtime.workflow_context import WorkflowContext
from tests.fixtures.research_brief import sample_research_brief


def _scope(value: str = "7.8", periods: tuple[str, ...] = ("2026",), unit: str = "%"):
    return {
        "version": SCOPE_VERSION,
        "geography": ["ukraine"],
        "geography_anchors": [{"value": "ukraine", "level": "country"}],
        "periods": list(periods), "metrics": ["retail"],
        "population_dimensions": ["households"],
        "numeric_facts": [{
            "value": value, "unit": unit, "scale": "absolute",
            "geography": ["ukraine"], "periods": list(periods),
            "metrics": ["retail"], "population_dimensions": ["households"],
        }],
        "source": "validated_evidence_metadata",
    }


class _Fixture:
    def __init__(self, *, two: bool = False) -> None:
        rqs = [ResearchQuestion("rq-1", "Q1")]
        needs = [InformationNeed("in-1", "rq-1", "N1")]
        if two:
            rqs.append(ResearchQuestion("rq-2", "Q2")); needs.append(InformationNeed("in-2", "rq-2", "N2"))
        self.design = ResearchDesign("design-1", tuple(rqs), tuple(needs), language="uk")
        self.evidence = [self._evidence(1, "rq-1", "in-1", _scope())]
        self.findings = [self._finding(1, "rq-1", "in-1", self.evidence[0], _scope())]
        if two:
            scope = _scope("8.7", ("2025", "2026"))
            self.evidence.append(self._evidence(2, "rq-2", "in-2", scope))
            self.findings.append(self._finding(2, "rq-2", "in-2", self.evidence[1], scope))

    def _evidence(self, index, rq, need, scope):
        return Evidence(
            id=f"ev-{index}", project_id="project-1", source_id=f"source-{index}",
            source_content_checksum=f"checksum-{index}", workflow_run_id="source-run",
            research_design_id="design-1", statement="S", source_excerpt="E",
            created_at="2026-01-01T00:00:00Z", research_question_refs=(rq,),
            information_need_refs=(need,), metadata={SCOPE_KEY: scope},
        )

    def _finding(self, index, rq, need, evidence, scope):
        return Finding(
            id=f"finding-{index}", project_id="project-1", workflow_run_id="source-run",
            research_design_id="design-1", statement="F", rationale="R",
            evidence_refs=(evidence.id,), created_at="2026-01-01T00:00:00Z",
            research_question_refs=(rq,), information_need_refs=(need,),
            metadata={SCOPE_KEY: scope},
        )


def _valid_response(request, *, text="Рівень становив ", include_citation=True):
    claims = []
    for candidate in request["candidates"]:
        claim_id = candidate["claim_id"]
        catalog = candidate["authorized_catalog"]
        fact_ref = next(iter(catalog["facts"]))
        period_ref = next(iter(catalog["periods"]))
        nodes = [
            {"node_type": "TEXT", "text": text},
            {"node_type": "FACT_REF", "owner_claim_ref": claim_id, "authority_ref": fact_ref, "presentation_variant": "value_with_unit"},
            {"node_type": "TEXT", "text": " у "},
            {"node_type": "PERIOD_REF", "owner_claim_ref": claim_id, "authority_ref": period_ref, "presentation_variant": "year"},
        ]
        if include_citation and catalog["citations"]:
            nodes.append({"node_type": "CITATION_REF", "owner_claim_ref": claim_id, "authority_ref": next(iter(catalog["citations"]))})
        claims.append({"claim_id": claim_id, "kind": "observation", "certainty": "direct", "direction": "not_applicable", "nodes": nodes})
    return {"contract_version": H3_CONTRACT_VERSION, "claims": claims}


class H3ClaimGenerationTests(unittest.TestCase):
    def generate(self, fixture=None, provider=_valid_response, repair=None, required_rqs=None, required_ins=None):
        fixture = fixture or _Fixture()
        return generate_h3_structural_claims(
            project_id="project-1", source_workflow_run_id="source-run",
            report_workflow_run_id="report-run", design=fixture.design,
            findings=tuple(fixture.findings), insights=(),
            evidence_by_id={item.id: item for item in fixture.evidence},
            citation_id_by_source={f"source-{i + 1}": f"S{i + 1}" for i in range(len(fixture.evidence))},
            candidate_provider=provider, correction_provider=repair,
            required_research_question_ids=required_rqs or ("rq-1",),
            required_information_need_ids=required_ins or ("in-1",),
        )

    def test_valid_structural_claim_decimal_percent_period_citation(self):
        result = self.generate()
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.SUCCESS)
        self.assertEqual(result.provider_attempt_count, 1)
        claim = result.claims[0]
        self.assertIn("7,8", claim.proposition)
        self.assertIn("2026", claim.proposition)
        self.assertEqual(claim.version, H3_CONTRACT_VERSION)
        self.assertIsNotNone(claim.structural_assertion)

    def test_multiple_facts_overlapping_and_fact_local_periods(self):
        fixture = _Fixture()
        second = _scope("8.7", ("2025", "2026"))["numeric_facts"][0]
        fixture.evidence[0].metadata[SCOPE_KEY]["numeric_facts"].append(second)
        fixture.findings[0].metadata[SCOPE_KEY]["numeric_facts"].append(second)
        captured = {}
        def provider(request):
            captured.update(request["candidates"][0]["authorized_catalog"])
            return _valid_response(request)
        self.generate(fixture, provider)
        self.assertEqual(len(captured["facts"]), 2)
        self.assertEqual(len(captured["periods"]), 3)

    def test_standalone_authorized_period_is_structural(self):
        fixture = _Fixture()
        fixture.evidence[0].metadata[SCOPE_KEY]["periods"].append("2024")
        fixture.findings[0].metadata[SCOPE_KEY]["periods"].append("2024")
        captured = {}
        def provider(request):
            captured.update(request["candidates"][0]["authorized_catalog"])
            return _valid_response(request)
        self.generate(fixture, provider)
        standalone = [item for item in captured["periods"].values() if item["fact_ref"] is None]
        self.assertEqual([item["period"] for item in standalone], ["2024"])

    def test_text_and_punctuation_adjacency_nbsp_and_repeated_refs(self):
        for text in ("Значення ", "Значення:\u00a0", "Значення:\u202f"):
            with self.subTest(text=text):
                self.assertEqual(self.generate(provider=lambda req, text=text: _valid_response(req, text=text)).coverage_outcome, H3CoverageOutcome.SUCCESS)
        def repeated(request):
            response = _valid_response(request)
            nodes = response["claims"][0]["nodes"]
            response["claims"][0]["nodes"] = nodes + copy.deepcopy(nodes[1:])
            return response
        self.assertEqual(self.generate(provider=repeated).coverage_outcome, H3CoverageOutcome.SUCCESS)

    def test_unknown_cross_claim_unauthorized_period_and_citation_rejected(self):
        fixture = _Fixture(two=True)
        mutations = []
        def unknown(response): response["claims"][0]["nodes"][1]["authority_ref"] = "unknown-fact"
        mutations.append(unknown)
        def cross(response):
            other = response["claims"][1]["nodes"][1]["authority_ref"]
            response["claims"][0]["nodes"][1]["authority_ref"] = other
        mutations.append(cross)
        def period(response): response["claims"][0]["nodes"][3]["authority_ref"] = "unknown-period"
        mutations.append(period)
        def citation(response): response["claims"][0]["nodes"][-1]["authority_ref"] = "unknown-citation"
        mutations.append(citation)
        for mutation in mutations:
            def provider(request, mutation=mutation):
                response = _valid_response(request); mutation(response); return response
            with self.subTest(mutation=mutation):
                result = self.generate(fixture, provider, required_rqs=("rq-1", "rq-2"), required_ins=("in-1", "in-2"))
                self.assertEqual(result.coverage_outcome, H3CoverageOutcome.REPORT_INSUFFICIENT_COVERAGE)

    def test_numeric_url_id_and_fact_annotation_leakage_rejected(self):
        for text in ("Значення 12 ", "https://example.com ", "claim-x ", "метрика: продажі "):
            with self.subTest(text=text):
                result = self.generate(provider=lambda req, text=text: _valid_response(req, text=text))
                self.assertEqual(result.claims, ())
                self.assertEqual(result.diagnostics[0].outcome, H3ClaimOutcome.REJECTED_PROVIDER_INVALID)

    def test_malformed_schema_rejected(self):
        result = self.generate(provider=lambda _: {"claims": []})
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.REPORT_INSUFFICIENT_COVERAGE)
        self.assertEqual(result.provider_attempt_count, 1)

    def test_single_bounded_batch_repair_succeeds(self):
        fixture = _Fixture(two=True); calls = []
        def bad(request):
            calls.append(request); return _valid_response(request, text="Число 12 ")
        def repair(request):
            calls.append(request); return _valid_response(request)
        result = self.generate(fixture, bad, repair, required_rqs=("rq-1", "rq-2"), required_ins=("in-1", "in-2"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.repair_count, 1)
        self.assertEqual(len(result.claims), 2)

    def test_failed_or_malformed_repair_never_calls_third_time(self):
        for repair in (lambda _: {"bad": True}, lambda req: _valid_response(req, text="Ще 13 ")):
            calls = []
            def initial(request): calls.append(request); return _valid_response(request, text="Число 12 ")
            def wrapped(request, repair=repair): calls.append(request); return repair(request)
            with self.subTest(repair=repair):
                result = self.generate(provider=initial, repair=wrapped)
                self.assertEqual(len(calls), 2)
                self.assertEqual(result.coverage_outcome, H3CoverageOutcome.REPORT_INSUFFICIENT_COVERAGE)

    def test_valid_initial_has_no_repair(self):
        calls = []
        def provider(request): calls.append(request); return _valid_response(request)
        result = self.generate(provider=provider, repair=lambda request: calls.append(request))
        self.assertEqual((len(calls), result.repair_count), (1, 0))

    def test_renderer_system_failure_consumes_no_repair_call(self):
        calls = []
        def provider(request): calls.append("initial"); return _valid_response(request)
        def repair(request): calls.append("repair"); return _valid_response(request)
        with mock.patch("application.report.h3_claim_generation.render_typed_document", side_effect=RuntimeError("renderer")):
            result = self.generate(provider=provider, repair=repair)
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.TECHNICAL_ERROR)
        self.assertEqual(calls, ["initial"])
        self.assertEqual(result.repair_count, 0)

    def test_optional_rejection_can_be_limited(self):
        fixture = _Fixture(two=True)
        def provider(request):
            response = _valid_response(request)
            response["claims"][1]["nodes"][0]["text"] = "Погано 99 "
            return response
        result = self.generate(fixture, provider, required_rqs=("rq-1",), required_ins=("in-1",))
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.LIMITED)
        self.assertEqual(len(result.claims), 1)

    def test_explicit_unsupported_optional_claim_is_controlled_and_not_repaired(self):
        fixture = _Fixture(two=True); calls = []
        def provider(request):
            calls.append("initial")
            response = _valid_response(request)
            response["claims"][1] = {
                "claim_id": request["candidates"][1]["claim_id"],
                "outcome": "REJECTED_UNSUPPORTED", "category": "no_supported_semantic_assertion",
            }
            return response
        def repair(request): calls.append("repair"); return _valid_response(request)
        result = self.generate(fixture, provider, repair, required_rqs=("rq-1",), required_ins=("in-1",))
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.LIMITED)
        self.assertEqual(result.diagnostics[1].outcome, H3ClaimOutcome.REJECTED_UNSUPPORTED)
        self.assertEqual(calls, ["initial"])

    def test_required_rq_or_information_need_loss_is_controlled_insufficiency(self):
        fixture = _Fixture(two=True)
        def provider(request):
            response = _valid_response(request)
            response["claims"] = response["claims"][:1]
            return response
        for rqs, needs in (("rq-1 rq-2".split(), ("in-1",)), (("rq-1",), ("in-1", "in-2"))):
            with self.subTest(rqs=rqs, needs=needs):
                result = self.generate(fixture, provider, required_rqs=tuple(rqs), required_ins=tuple(needs))
                self.assertEqual(result.coverage_outcome, H3CoverageOutcome.REPORT_INSUFFICIENT_COVERAGE)

    def test_authority_corruption_is_technical_error_without_provider_call(self):
        fixture = _Fixture(); fixture.findings[0].workflow_run_id = "foreign"
        calls = []
        result = self.generate(fixture, provider=lambda request: calls.append(request))
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.TECHNICAL_ERROR)
        self.assertEqual(calls, [])

    def test_round_trip_and_digest_mutations_fail_without_prose_reparse(self):
        claim = self.generate().claims[0]
        self.assertEqual(ReportClaim.from_dict(claim.to_dict()), claim)
        document, catalog = restore_h3_claim_structure(claim)
        self.assertEqual(document.owner_id, claim.claim_id)
        self.assertIn(claim.claim_id, catalog.claims)
        for key in ("authority_input_digest", "source_authority_digest", "typed_ast_digest", "render_digest"):
            payload = claim.to_dict(); payload["structural_assertion"][key] = "0" * 64
            with self.subTest(key=key), self.assertRaises(ReportClaimContractError):
                ReportClaim.from_dict(payload)

    def test_memory_persistence_round_trip_h3_and_h2_compatibility(self):
        claim = self.generate().claims[0]
        report = Report(
            id="report", project_id="project-1", workflow_run_id="report-run",
            research_design_id="design-1", title="T", language="uk", sections=(),
            executive_summary="", limitations=(), created_at="2026-01-01T00:00:00Z",
            generation_method="h3", finding_refs=claim.finding_ids, insight_refs=(),
            evidence_refs=claim.evidence_ids, citation_registry={}, deduplication_key="d",
        )
        reports = InMemoryReportRepository(); repository = InMemoryReportClaimRepository(reports)
        repository.create_with_report(report, (claim,))
        self.assertEqual(repository.list_for_report("report", 1), [claim])
        from tests.application.report.test_report_claim_contract import ReportClaimContractTests
        legacy = ReportClaimContractTests(); legacy.setUp()
        self.assertEqual(ReportClaim.from_dict(legacy.claim().to_dict()), legacy.claim())

    def test_production_shaped_structural_fixture(self):
        fixture = _Fixture()
        fixture.evidence = [replace(fixture.evidence[0], id=f"ev-{i}", source_id=f"source-{i % 30}") for i in range(19)]
        fixture.findings = [replace(fixture.findings[0], id=f"finding-{i}", evidence_refs=tuple(item.id for item in fixture.evidence[i * 4:(i + 1) * 4] or fixture.evidence[:1])) for i in range(4)]
        insights = tuple(
            Insight(
                id=f"insight-{i}", project_id="project-1", workflow_run_id="source-run",
                research_design_id=fixture.design.id, statement="I", implication="I",
                finding_refs=(fixture.findings[i % 4].id,), created_at="2026-01-01T00:00:00Z",
                research_question_refs=("rq-1",),
            )
            for i in range(5)
        )
        result = generate_h3_structural_claims(
            project_id="project-1", source_workflow_run_id="source-run", report_workflow_run_id="replay-run",
            design=fixture.design, findings=tuple(fixture.findings), insights=insights,
            evidence_by_id={item.id: item for item in fixture.evidence},
            citation_id_by_source={f"source-{i}": f"S{i}" for i in range(30)},
            candidate_provider=_valid_response, correction_provider=None,
            required_research_question_ids=("rq-1",), required_information_need_ids=("in-1",),
        )
        self.assertEqual(result.coverage_outcome, H3CoverageOutcome.SUCCESS)
        self.assertEqual(len(result.claims), 4)
        self.assertEqual(len({ref for claim in result.claims for ref in claim.insight_ids}), 5)

    def test_real_claim_first_service_h3_branch_persists_structural_claim_stage(self):
        fixture = _Fixture(); project = ProjectFactory().create("H3")
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
        insights = InMemoryInsightRepository(); reports = InMemoryReportRepository()
        claims = InMemoryReportClaimRepository(reports)
        template = WorkflowTemplateBuilder(id="template", name="T").add_task(
            id="report", name="Write", executor_id="report", executor_type=ExecutorType.AGENT,
        ).build()
        template.research_brief_snapshot = replace(sample_research_brief(), timeframe="")
        template.research_design_snapshot = fixture.design
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id="source-run")
        run.project_id = project.id
        context = WorkflowContext(project=project, workflow_run=run, workflow_template=template, current_task=run.tasks[0])
        class Engine:
            method_name = "h3-test"
            def generate_h3_claim_candidates(self, request): return _valid_response(request)
            def repair_h3_claim_candidates(self, request): return _valid_response(request)
        service = ClaimFirstReportService(
            report_claim_repository=claims, report_contract_version=H3_CONTRACT_VERSION,
            report_engine=Engine(), finding_repository=findings, insight_repository=insights,
            evidence_repository=evidences, source_repository=sources,
            report_repository=reports, artifact_repository=InMemoryArtifactRepository(),
            max_findings_per_batch=10, max_chars_per_batch=10000,
        )
        summary = service.write_for_context(context)
        report = reports.get_by_id(summary.report_id)
        stored = claims.list_for_report(summary.report_id, 1)
        self.assertEqual(report.metadata["structured_claim_contract"], H3_CONTRACT_VERSION)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].report_workflow_run_id, "source-run")
        self.assertEqual(summary.artifact_id, "")

    def test_h3_generator_has_no_h2_prose_authority_dependencies(self):
        import application.report.h3_claim_generation as module
        source = inspect.getsource(module)
        for forbidden in (
            "claim_scope_validation", "compose_assertion", "validate_claim_proposition",
            "_validate_typed_h2_proposition", "claim_numeric_composition",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
