"""Full production composition; only external providers use synthetic fixtures."""
from dataclasses import replace
import json
import tempfile
import io
import os
import re
from pathlib import Path
from sqlalchemy import text
from decimal import Decimal
from openpyxl import load_workbook
from http.server import BaseHTTPRequestHandler
from uuid import uuid4
from hashlib import sha256

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.report.typed_rendering import H3_CONTRACT_VERSION
from domain.ai.llm_response import LLMResponse
from domain.research_brief import ResearchBrief
from domain.planning.research_design import InformationNeed
from domain.planning.derivation import InformationNeedKind
from domain.sources.source_candidate import SourceCandidate
from domain.sources.source import Source
from domain.evidence.evidence import Evidence
from application.evidence.grounding import verify_grounding
from application.evidence.citation_integrity import citation_is_valid
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever
from tests.api.helpers import drain_background_runs
from tests.application.analysis.test_executable_derivations import derived_design, ProviderFixture
from tests.application.evidence.test_structured_production import workbook_rows
from tests.application.report.test_h3_claim_generation import _valid_response
from tests.integration.postgresql import test_capability_acquisition as http_fixture
from tests.integration.postgresql.helpers import postgresql_application_config


class PipelineProvider(ProviderFixture):
    def generate(self, prompt, **kwargs):
        if getattr(self, "fail_analysis", False) and prompt.system.startswith("You are a desk research analyst. Evidence"):
            raise RuntimeError("Synthetic Analysis provider outage")
        if prompt.system.startswith("You evaluate whether existing research evidence"):
            return LLMResponse(json.dumps(dict(supported_aspects=["level", "timepoint", "geography"],
                missing_aspects=[], semantic_conflicts=[], confidence=0.99, reason="Synthetic data meets explicit aspects.")))
        if prompt.system.startswith("Generate typed H3"):
            request = json.loads(prompt.user)
            response = _valid_response(request)
            for claim, candidate in zip(response["claims"], request["candidates"]):
                catalog = candidate["authorized_catalog"]
                claim["nodes"] = [{"node_type": "TEXT", "text": "Підтверджені показники: "}]
                for ref in catalog["facts"]:
                    claim["nodes"].append(dict(node_type="FACT_REF", owner_claim_ref=claim["claim_id"], authority_ref=ref,
                        presentation_variant="value_with_unit"))
                    for period, value in catalog["periods"].items():
                        if value.get("fact_ref") == ref:
                            claim["nodes"].append(dict(node_type="PERIOD_REF", owner_claim_ref=claim["claim_id"],
                                authority_ref=period, presentation_variant="year"))
                for ref in catalog["citations"]:
                    claim["nodes"].append(dict(node_type="CITATION_REF", owner_claim_ref=claim["claim_id"], authority_ref=ref))
            return LLMResponse(json.dumps(response))
        return super().generate(prompt, **kwargs)


class EditorialProvider:
    def compose(self, request):
        catalog = request["authority_catalog"]
        nodes = []
        for claim_id in catalog["claims"]:
            nodes.append(dict(node_id=str(len(nodes)), node_type="CLAIM_REF", owner_claim_ref=claim_id,
                text=None, authority_ref=claim_id, presentation_variant=None))
        nodes.append(dict(node_id=str(len(nodes)), node_type="TEXT", owner_claim_ref=None, text="Підтверджені показники: ",
            authority_ref=None, presentation_variant=None))
        for ref, fact in catalog["facts"].items():
            nodes.append(dict(node_id=str(len(nodes)), node_type="FACT_REF", owner_claim_ref=fact["owner_claim_ref"],
                text=None, authority_ref=ref, presentation_variant="value_with_unit"))
            for period, value in catalog["periods"].items():
                if value.get("fact_ref") == ref:
                    nodes.append(dict(node_id=str(len(nodes)), node_type="PERIOD_REF", owner_claim_ref=fact["owner_claim_ref"],
                        text=None, authority_ref=period, presentation_variant="year"))
        for ref, citation in catalog["citations"].items():
            nodes.append(dict(node_id=str(len(nodes)), node_type="CITATION_REF", owner_claim_ref=citation["owner_claim_ref"],
                text=None, authority_ref=ref, presentation_variant=None))
        return {"contract_version": H3_CONTRACT_VERSION, "typed_document": {
            "contract_version": H3_CONTRACT_VERSION, "document_id": "synthetic-editorial",
            "owner_id": request["report_id"], "nodes": nodes}}


class ReviewProvider:
    def __init__(self):
        self.calls = 0

    def review(self, request):
        self.calls += 1
        if self.calls == 1:
            return {"decision": "REVISE", "issues": [{"code": "clarity", "severity": "minor", "message": "Уточніть подання без зміни фактів."}]}
        return {"decision": "APPROVE", "issues": []}


class IntegratedResearchAcceptanceTests(http_fixture.CapabilityAcquisitionTests):
    def test_full_research_production_container(self):
        self.execute_pipeline()

    def test_missing_required_year_is_insufficient_without_report(self):
        self.execute_pipeline(missing_year=True)

    def test_analysis_provider_failure_is_failed_not_insufficient(self):
        self.execute_pipeline(technical_failure=True)

    def test_incompatible_units_reject_derived_computation(self):
        self.execute_pipeline(incompatible_units=True)

    def test_conflicting_geography_rejects_derived_computation(self):
        self.execute_pipeline(geography_conflict=True)

    def test_invalid_persisted_checksum_is_not_qualifying(self):
        from tests.integration.postgresql.test_structured_evidence_pipeline import StructuredEvidencePipelineTests
        from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
        from application.evidence.temporal_scope import qualifying_evidence
        run, context, service, evidence, provider, design, brief = StructuredEvidencePipelineTests.setup_pipeline(self)
        source = self.acquire(run)
        service.extract_for_source_ids(context, (source.id,), allow_empty=True)
        original = evidence.list_for_project(self.project.id, workflow_run_id=run)[0]
        invalid = replace(original, id=str(uuid4()), deduplication_key="invalid-citation", source_content_checksum="invalid")
        evidence.create(invalid)
        loaded = PostgreSQLEvidenceRepository(DatabaseSessionFactory(self.engine)).get_by_id(invalid.id)
        self.assertEqual(qualifying_evidence(design=design, evidence=(loaded,), brief=brief, source_repository=self.repo), ())
        self.assertTrue(citation_is_valid(original, source))
        provider.generate.assert_not_called()

    def test_postgresql_finding_write_failure_is_failed(self):
        def cleanup():
            with self.engine.begin() as connection:
                connection.execute(text("DROP TRIGGER IF EXISTS patch7_reject_finding ON findings"))
                connection.execute(text("DROP FUNCTION IF EXISTS patch7_reject_finding()"))
        self.addCleanup(cleanup)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE FUNCTION patch7_reject_finding() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic persistence failure'; END $$"))
            connection.execute(text("CREATE TRIGGER patch7_reject_finding BEFORE INSERT ON findings FOR EACH ROW EXECUTE FUNCTION patch7_reject_finding()"))
        self.execute_pipeline(persistence_failure=True)

    def execute_pipeline(self, *, missing_year=False, technical_failure=False, incompatible_units=False, persistence_failure=False, geography_conflict=False):
        self.body = workbook_rows()
        if missing_year:
            book = load_workbook(io.BytesIO(self.body))
            book.active.delete_rows(3)
            stream = io.BytesIO(); book.save(stream); self.body = stream.getvalue()
        if incompatible_units:
            book = load_workbook(io.BytesIO(self.body))
            for row in range(2, 5):
                book.active.cell(row, 3, "thousands")
            stream = io.BytesIO(); book.save(stream); self.body = stream.getvalue()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                owner.hits.append(inner.path)
                key = inner.path.rsplit("/", 1)[-1]
                if inner.path.startswith("/download/"):
                    body, mime = owner.body, "application/octet-stream"
                else:
                    target = "resource" if inner.path.startswith("/landing/") else "download"
                    body = f'<a href="/{target}/{key}">Population Ukraine 2019 2020 2021 XLSX table download</a>'.encode()
                    mime = "text/html"
                inner.send_response(200)
                inner.send_header("Content-Type", mime)
                inner.end_headers()
                inner.wfile.write(body)
            def log_message(self, *args):
                pass
        self.server.RequestHandlerClass = Handler
        class SearchProvider:
            def supports_retrieval_arm(self, arm, query):
                return False

            def search(self, query):
                if query.information_need_id != "in-pop":
                    return []
                return [SourceCandidate("synthetic-search", owner.origin + f"/landing/{index}", "Population Ukraine 2019 2020 2021",
                    "Population Ukraine annual table", query.id, index) for index in range(1, 4)]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = replace(postgresql_application_config(evidence_extractor="llm", analysis_engine="llm",
            report_engine="llm", research_sufficiency_assessor="llm", desk_report_contract_version=H3_CONTRACT_VERSION),
            projects_root=directory.name)
        provider = PipelineProvider()
        provider.fail_analysis = technical_failure
        container = create_application_container(config=config, overrides=ApplicationOverrides(
            llm_client=provider, search_provider=SearchProvider(), source_retriever=HttpSourceRetriever(),
            h3_editorial_provider=EditorialProvider(), h3_review_provider=ReviewProvider()))
        self.addCleanup(container.shutdown)
        container.agency.initialize()
        project = container.project_service.get_project(self.project.id)
        project.research_brief = ResearchBrief(title="Синтетична чисельність населення", business_question="Population Ukraine",
            timeframe="2019–2021", language="uk")
        model = derived_design()
        if geography_conflict:
            model = replace(model, information_needs=tuple(replace(n, derivation=replace(n.derivation, geography="Poland")) if n.derivation else n for n in model.information_needs))
        project.current_research_design = replace(model, information_needs=(
            *(replace(n, output_format="table") if n.kind == InformationNeedKind.OUTPUT else n for n in model.information_needs),
            InformationNeed("chart", "rq-pop", "Динаміка синтетичного показника", kind=InformationNeedKind.OUTPUT,
                depends_on_information_need_ids=("in-pop",), output_format="chart")))
        project.research_design_status = "APPROVED"
        container.project_service.save_project(project)
        template = ResearchDesignWorkflowMapper(desk_report_contract_version=H3_CONTRACT_VERSION).from_research_design(project.current_research_design, project)
        historical_run = self.run_id()
        legacy = Source(str(uuid4()), project.id, self.origin + "/landing/1", self.origin + "/landing/1", "Legacy HTML",
            "2026-01-01T00:00:00Z", content_text="legacy", content_checksum=sha256(b"legacy").hexdigest(),
            workflow_run_refs=(historical_run,), research_design_refs=("design",))
        self.repo.create(legacy)
        historical_evidence = Evidence(str(uuid4()), project.id, legacy.id, legacy.content_checksum, historical_run,
            "design", "legacy", "legacy", "2026-01-01T00:00:00Z", deduplication_key="historical-citation",
            source_locator=verify_grounding(source_text="legacy", excerpt="legacy").to_dict())
        PostgreSQLEvidenceRepository(self.session_factory).create(historical_evidence)
        legacy_before = self.repo.get_by_id(legacy.id).to_dict()
        run = container.agency.start_research_from_template(project, template, run_id=str(uuid4())).workflow_run
        if technical_failure or persistence_failure:
            with self.assertRaises(Exception):
                drain_background_runs(container)
            stored = container.workflow_service.get_workflow_run(run.id)
            self.assertEqual(stored.status.value, "failed")
            self.assertEqual(next(t.status.value for t in stored.tasks if t.definition_id == "task-analyze"), "failed")
            self.assertEqual(container.research_run_result_query_service.get_for_run(run.id).outcome.value, "FAILED")
            self.assertEqual(container.report_query_service.list_reports_for_project(project.id, workflow_run_id=run.id), [])
            return
        drain_background_runs(container)
        stored = container.workflow_service.get_workflow_run(run.id)
        if incompatible_units or geography_conflict:
            findings = container.finding_service.list_findings_for_project(project.id, workflow_run_id=run.id)
            self.assertTrue(findings)
            self.assertFalse(any(f.metadata.get("derivation") for f in findings))
            self.assertNotEqual(container.research_run_result_query_service.get_for_run(run.id).outcome.value, "COMPLETED")
            self.assertEqual(container.report_query_service.list_reports_for_project(project.id, workflow_run_id=run.id), [])
            self.assertIn("geography_mismatch" if geography_conflict else "unit_mismatch", str(container.workflow_service.get_task_results(run.id)))
            return
        if missing_year:
            self.assertEqual(stored.status.value, "completed")
            self.assertEqual(container.research_run_result_query_service.get_for_run(run.id).outcome.value, "INSUFFICIENT")
            self.assertEqual(container.finding_service.list_findings_for_project(project.id, workflow_run_id=run.id), [])
            self.assertTrue(all(t.status.value == "skipped" for t in stored.tasks if t.executor_id in {"report", "review", "revision", "finalization"}))
            self.assertEqual(container.report_query_service.list_reports_for_project(project.id, workflow_run_id=run.id), [])
            from application.query.research_outcome_presentation import present_research_outcome
            self.assertEqual(present_research_outcome(stored.status.value, "INSUFFICIENT").label, "Недостатньо матеріалів")
            return
        self.assertEqual(stored.status.value, "completed", [(t.definition_id, t.status.value) for t in stored.tasks])
        self.assertEqual(container.research_run_result_query_service.get_for_run(run.id).outcome.value, "COMPLETED")
        reports = container.report_query_service.list_reports_for_project(project.id, workflow_run_id=run.id)
        self.assertTrue(reports)
        self.assertTrue(self.hits)
        self.assertEqual(self.repo.get_by_id(legacy.id).to_dict(), legacy_before)
        self.assertTrue(citation_is_valid(historical_evidence, self.repo.get_by_id(legacy.id)))
        paths = self.repo.list_acquisition_paths(project.id, run.id)
        self.assertTrue(any(p.diagnostics.get("capability_decision") == "REFETCH" for p in paths))
        self.assertTrue(all(len(p.navigation_chain) == 3 for p in paths))
        findings = container.finding_service.list_findings_for_project(project.id, workflow_run_id=run.id)
        self.assertEqual(len(findings), 7)
        derived = [f for f in findings if f.metadata.get("derivation")]
        self.assertEqual(len(derived), 6)
        values = {(f.metadata["derivation"]["operation_type"], f.metadata["derivation"]["parameters"]["to_period"]):
            Decimal(f.metadata["derivation"]["rounded_result"]) for f in derived}
        expected = {("YEAR_OVER_YEAR_ABSOLUTE_CHANGE", "2020"): Decimal(-50), ("YEAR_OVER_YEAR_ABSOLUTE_CHANGE", "2021"): Decimal(-50),
            ("YEAR_OVER_YEAR_PERCENT_CHANGE", "2020"): Decimal(-5), ("YEAR_OVER_YEAR_PERCENT_CHANGE", "2021"): Decimal("-5.263158"),
            ("CUMULATIVE_ABSOLUTE_CHANGE", "2021"): Decimal(-100), ("CUMULATIVE_PERCENT_CHANGE", "2021"): Decimal(-10)}
        self.assertEqual(values, expected)
        evidence = container.evidence_service.list_evidence_for_project(project.id, workflow_run_id=run.id)
        self.assertEqual({(e.metadata["observation_period"], Decimal(str(e.metadata["normalized_numeric_value"]))) for e in evidence},
            {("2019", Decimal(1000)), ("2020", Decimal(950)), ("2021", Decimal(900))})
        self.assertTrue(all(e.source_locator["structured"]["cell"] and e.source_locator["structured"]["header_checksum"] for e in evidence))
        self.assertTrue(all(f.metadata["validation_status"] == "validated" and f.metadata["derivation"]["dependency_finding_ids"] for f in derived))
        insights = container.insight_service.list_insights_for_project(project.id, workflow_run_id=run.id)
        self.assertTrue(insights, "Full research must persist Findings-backed Insights")
        finding_ids = {f.id for f in findings}
        self.assertTrue(all(i.finding_refs and set(i.finding_refs) <= finding_ids for i in insights))
        self.assertTrue(all(i.project_id == project.id and i.workflow_run_id == run.id
                            and i.research_design_id == project.current_research_design.id for i in insights))
        snapshots = container.workflow_service.get_task_results(run.id)
        coverages = [s["shared_state"]["analysis_coverage"] for s in snapshots.values() if isinstance(s, dict) and "analysis_coverage" in s.get("shared_state", {})]
        self.assertTrue(coverages and coverages[-1]["fully_covered"])
        report = max(reports, key=lambda item: item.revision_number)
        self.assertEqual(report.revision_number, 2)
        claims = tuple(container.project_deliverables_service.report_claims.list_for_report(report.id, report.revision_number))
        self.assertTrue(claims)
        self.assertTrue(all(c.status == "validated" and c.citation_ids and set(c.finding_ids) <= finding_ids
                            and set(c.support_evidence_ids) <= {e.id for e in evidence} for c in claims))
        self.assertEqual({ref for c in claims for ref in c.information_need_ids},
                         {n.id for n in project.current_research_design.information_needs if n.kind != InformationNeedKind.OUTPUT})
        confirmed_values = {Decimal(str(e.metadata["normalized_numeric_value"])) for e in evidence} | set(expected.values())
        self.assertTrue(all(Decimal(f.value) in confirmed_values for c in claims for f in c.scope.numeric_facts))
        self.assertTrue(all(t.status.value == "completed" for t in stored.tasks if t.executor_id in {"review", "revision", "finalization"}))
        self.assertEqual(report.metadata["output_obligations"]["verification_state"], "verified")
        materials = report.metadata["output_materials"]
        self.assertEqual(materials["tables"][0]["rows"], [["2019", "1000", "persons"], ["2020", "950", "persons"], ["2021", "900", "persons"]])
        self.assertEqual(materials["charts"][0]["values"], [1000.0, 950.0, 900.0])
        catalog = container.project_deliverables_service.catalog(project.id, owner_id=project.owner_principal_id)
        item = next(item for item in catalog.desk if item.document.source_id == report.id)
        self.assertIsNotNone(item.pdf)
        self.assertIsNotNone(item.pptx)
        from io import BytesIO
        from zipfile import ZipFile
        from pypdf import PdfReader
        _, pdf_data = container.project_deliverables_service.store.get(item.pdf.id)
        _, pptx_data = container.project_deliverables_service.store.get(item.pptx.id)
        pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf_data)).pages)
        normalized_pdf_text = re.sub(r"\s+", " ", pdf_text)
        self.assertTrue(all(number in normalized_pdf_text for number in ("2019", "2020", "2021", "1000", "950", "900")))
        self.assertTrue(all(number in normalized_pdf_text for number in ("-50 persons", "-5 percent", "-5,263158 percent", "-100 persons", "-10 percent")))
        with ZipFile(BytesIO(pptx_data)) as package:
            self.assertTrue(any(name.startswith("ppt/charts/chart") for name in package.namelist()))
            self.assertTrue(any(b"<a:tbl>" in package.read(name) for name in package.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")))
            from xml.etree import ElementTree
            chart_values = {element.text for name in package.namelist() if name.startswith("ppt/charts/chart") and name.endswith(".xml")
                for element in ElementTree.fromstring(package.read(name)).iter("{http://schemas.openxmlformats.org/drawingml/2006/chart}v")}
            self.assertTrue({"2019", "2020", "2021", "1000", "950", "900"} <= chart_values)
        fresh = create_application_container(config=config, overrides=ApplicationOverrides(llm_client=provider))
        self.addCleanup(fresh.shutdown)
        self.assertEqual(fresh.workflow_service.get_task_results(run.id), snapshots)
        self.assertEqual(fresh.research_run_result_query_service.get_for_run(run.id).outcome.value, "COMPLETED")
        self.assertEqual(fresh.project_deliverables_service.store.get(item.pdf.id)[1], pdf_data)
        self.assertEqual(fresh.project_deliverables_service.store.get(item.pptx.id)[1], pptx_data)
        artifacts_before = fresh.artifact_service.count_for_run(project.id, run.id)
        sources_before = {s.id for s in fresh.source_service.list_sources_for_run(run.id, project_id=project.id)}
        evidence_before = {e.id for e in fresh.evidence_service.list_evidence_for_project(project.id, workflow_run_id=run.id)}
        drain_background_runs(fresh)
        self.assertEqual(fresh.workflow_service.get_task_results(run.id), snapshots)
        self.assertEqual({f.id for f in fresh.finding_service.list_findings_for_project(project.id, workflow_run_id=run.id)}, {f.id for f in findings})
        self.assertEqual(fresh.artifact_service.count_for_run(project.id, run.id), artifacts_before)
        self.assertEqual({s.id for s in fresh.source_service.list_sources_for_run(run.id, project_id=project.id)}, sources_before)
        self.assertEqual({e.id for e in fresh.evidence_service.list_evidence_for_project(project.id, workflow_run_id=run.id)}, evidence_before)
        self.assertEqual({i.id for i in fresh.insight_service.list_insights_for_project(project.id, workflow_run_id=run.id)}, {i.id for i in insights})
        artifact_dir = os.environ.get("AIROS_ACCEPTANCE_ARTIFACT_DIR")
        if artifact_dir:
            target = Path(artifact_dir)
            target.mkdir(parents=True, exist_ok=True)
            (target / "e2e-c-report.pdf").write_bytes(pdf_data)
            (target / "e2e-c-report.pptx").write_bytes(pptx_data)
            (target / "fixture-population.xlsx").write_bytes(self.body)
            proof = dict(synthetic_data=True, workflow_run_id=run.id, research_outcome="COMPLETED",
                workflow_status=stored.status.value, task_statuses={t.definition_id: t.status.value for t in stored.tasks},
                analysis_coverage=coverages[-1], fresh_reload_verified=True, replay_drain_idempotent=True,
                pdf_sha256=sha256(pdf_data).hexdigest(), pptx_sha256=sha256(pptx_data).hexdigest(),
                historical_source_before=legacy_before, historical_source_after=self.repo.get_by_id(legacy.id).to_dict(),
                historical_evidence=historical_evidence.to_dict(), historical_citation_valid=True,
                design=project.current_research_design.to_dict(), report_id=report.id, report_revision=report.revision_number,
                output_materials=materials, evidence=[dict(id=e.id, source_id=e.source_id, metadata=e.metadata, source_locator=e.source_locator) for e in evidence],
                findings=[dict(id=f.id, evidence_refs=f.evidence_refs, metadata=f.metadata) for f in findings],
                insights=[i.to_dict() for i in insights], claims=[c.to_dict() for c in claims],
                acquisition_paths=[dict(source_id=p.source_id, navigation_chain=p.navigation_chain, diagnostics=p.diagnostics) for p in paths])
            (target / "e2e-c-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
