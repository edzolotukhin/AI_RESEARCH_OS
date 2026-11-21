"""IR-6 provider-free global PostgreSQL acceptance."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import zipfile
from uuid import uuid4
from unittest.mock import Mock

from openpyxl import load_workbook

from sqlalchemy import update

from application.analysis.analysis_service import AnalysisService
from application.analysis.exceptions import AnalysisError
from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.deliverables.service import DeliverableFinalizationError
from application.persistence.exceptions import AccessDeniedError
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.evidence.temporal_scope import qualify_evidence_with_temporal_decisions
from application.analysis.numeric_integrity import project_numeric_evidence_for_design
from application.report.claim_first_report_service import ClaimFirstReportService
from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
from application.report.exceptions import ReportError
from application.report.h3_claim_generation import H3ReportOutcomeError
from application.review.h3_workflow_review_adapter import H3WorkflowReviewAdapter
from application.review.h3_review_branch import H3_REVIEW_1_DEFINITION
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from application.research_quality.readiness_result_codec import (
    extract_research_readiness,
    extract_research_product_outcome,
)
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.authoritative_outcome import derive_authoritative_outcome
from application.sources.search_factory import build_source_acquisition_service
from application.ports.source_ports import SearchProvider
from domain.research_brief import ResearchBrief
from domain.workflow_template import WorkflowTemplate
from domain.planning.derivation import DerivationOperation, InformationNeedKind
from domain.factories.project_factory import ProjectFactory
from domain.sources.source_candidate import SourceCandidate
from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import PostgreSQLArtifactRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import PostgreSQLFindingRepository
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import PostgreSQLInsightRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_claim_repository import PostgreSQLReportClaimRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import PostgreSQLReportRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_review_repository import PostgreSQLReviewRepository
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.models.report_claim_model import ReportClaimModel
from infrastructure.persistence.postgresql.models.report_model import ReportModel
from infrastructure.persistence.postgresql.models.finding_model import FindingModel
from infrastructure.persistence.postgresql.models.evidence_model import EvidenceModel
from infrastructure.persistence.postgresql.models.pdf_deliverable_model import PdfDeliverableModel
from infrastructure.persistence.postgresql.models.presentation_job_model import PresentationJobModel
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever
from runtime.workflow_context import WorkflowContext
from domain.ai.llm_response import LLMResponse
from tests.application.analysis.test_ir4_canonical_authority_projection import (
    CanonicalAnalysisEngine,
    acquired_assessment,
    ir4_design,
)
from tests.application.evidence.test_ir3_structured_numeric_closure import ir3_zip
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.integration.postgresql.test_ir5_canonical_report_completion import (
    IR5CanonicalReportCompletionPostgreSQLTests as _IR5CanonicalReportCompletionPostgreSQLTests,
)


class IR6GlobalPostgreSQLAcceptanceTests(
    _IR5CanonicalReportCompletionPostgreSQLTests,
):
    @staticmethod
    def _canonical_quantitative_planner_llm():
        """Return canonical Design JSON through the real PlannerAgent boundary."""
        payload = ir4_design().to_dict()
        payload.update({
            "source_strategy": ["official statistical XLSX source"],
            "analysis_plan": [
                "Analyze the validated annual resident-population series.",
            ],
            "deliverable_plan": ["Research report"],
        })
        client = Mock()
        client.generate.side_effect = lambda prompt, options=None: LLMResponse(
            content=json.dumps(payload),
        )
        return client

    def _report_service(self):
        return ClaimFirstReportService(
            report_claim_repository=PostgreSQLReportClaimRepository(self.session_factory),
            report_engine=DeterministicReportEngine(),
            finding_repository=PostgreSQLFindingRepository(self.session_factory),
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=self.repo,
            report_repository=PostgreSQLReportRepository(self.session_factory),
            artifact_repository=PostgreSQLArtifactRepository(self.session_factory),
            max_findings_per_batch=10,
            max_chars_per_batch=10_000,
        )

    def _h3_negative_report_service(self):
        class H3Engine:
            method_name = "h3-negative-test"

            @staticmethod
            def generate_h3_claim_candidates(request):
                raise AssertionError("invalid authority must stop before H3 provider")

            @staticmethod
            def repair_h3_claim_candidates(request):
                raise AssertionError("invalid authority must stop before H3 repair")

        return ClaimFirstReportService(
            report_claim_repository=PostgreSQLReportClaimRepository(self.session_factory),
            report_contract_version=H3_REPORT_CONTRACT,
            report_engine=H3Engine(),
            finding_repository=PostgreSQLFindingRepository(self.session_factory),
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=self.repo,
            report_repository=PostgreSQLReportRepository(self.session_factory),
            artifact_repository=PostgreSQLArtifactRepository(self.session_factory),
            max_findings_per_batch=10,
            max_chars_per_batch=10_000,
        )

    class _FixtureSearchProvider(SearchProvider):
        def __init__(self, origin):
            self.origin = origin

        def search(self, query):
            return [
                SourceCandidate(
                    provider="ir6-local-fixture",
                    provider_result_id=f"{query.id}-fixture-{index}",
                    url=f"{self.origin}/download/{index}",
                    title=f"Official statistical XLSX fixture {index}",
                    snippet=f"Resident population Ukraine {query.timeframe}",
                    query_id=query.id,
                    rank=index,
                    source_type="official statistics",
                )
                for index in range(1, 4)
            ]

    def _persisted_planning_context(self):
        planner_llm = self._canonical_quantitative_planner_llm()
        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(
                llm_client=planner_llm,
            ),
        )
        self.addCleanup(container.shutdown)
        project_service = container.project_service
        project = project_service.get_project(self.project.id)
        project.owner_principal_id = "ir6-owner"
        project.selected_methods = ("DESK",)
        project_service.save_project(project)

        brief = ResearchBrief(
            title="Resident population",
            business_question="Resident population of Ukraine",
            timeframe="2015–2021",
        )
        planning = container.project_planning_service
        planning.save_brief(project, brief)
        project = project_service.get_project(self.project.id)
        planning.generate_design(project)
        project = project_service.get_project(self.project.id)
        approved = planning.approve_design(
            project,
            actor_id="ir6-owner",
            expected_design_id=project.current_research_design.id,
        )
        self.assertEqual(approved.research_design_status, "APPROVED")
        self.assertEqual(approved.research_design_approved_by, "ir6-owner")
        self.assertTrue(approved.research_design_input_fingerprint)

        project = project_service.get_project(self.project.id)
        source_template = ResearchDesignWorkflowMapper(
            desk_report_contract_version=H3_REPORT_CONTRACT,
        ).from_research_design(
            project.current_research_design,
            project,
        )
        source_template.id = "ir6-approved-template"
        source_template.name = "IR-6 approved planning snapshot"
        container.workflow_service.publish_template_snapshot(
            source_template, project_id=project.id,
        )
        template = container.workflow_service.get_template(source_template.id)
        self.assertEqual(template.research_brief_snapshot, project.research_brief)
        self.assertEqual(template.research_design_snapshot, project.current_research_design)
        workflow = container.workflow_service.create_workflow_run(
            template,
            project_id=project.id,
            run_id=str(uuid4()),
        )
        reloaded_project = project_service.get_project(project.id)
        reloaded_template = container.workflow_service.get_template(template.id)
        reloaded_run = container.workflow_service.get_workflow_run(workflow.id)
        self.assertEqual(reloaded_project.research_design_status, "APPROVED")
        self.assertEqual(reloaded_run.workflow_template_id, reloaded_template.id)
        persisted_design = reloaded_template.research_design_snapshot
        self.assertEqual(len(persisted_design.information_needs), 2)
        self.assertEqual(
            {need.id for need in persisted_design.information_needs},
            {"in", "change"},
        )
        need = next(item for item in persisted_design.information_needs if item.id == "in")
        self.assertEqual(need.kind, InformationNeedKind.ACQUIRED)
        self.assertEqual(need.evidence_expectation.nature.value, "quantitative")
        self.assertTrue(need.evidence_expectation.requires_quantitative_evidence)
        self.assertIsNotNone(need.evidence_coverage)
        self.assertEqual(need.evidence_coverage.required_metric, "Resident population")
        self.assertEqual(need.evidence_coverage.required_unit, "persons")
        self.assertEqual(
            need.evidence_coverage.required_periods,
            tuple(str(year) for year in range(2015, 2022)),
        )
        self.assertEqual(need.evidence_coverage.geography, "Ukraine")
        derived_need = next(
            item for item in persisted_design.information_needs if item.id == "change"
        )
        self.assertEqual(derived_need.kind, InformationNeedKind.DERIVED)
        self.assertEqual(derived_need.depends_on_information_need_ids, ("in",))
        self.assertIsNotNone(derived_need.derivation)
        assert derived_need.derivation is not None
        self.assertEqual(
            derived_need.derivation.operation_type,
            DerivationOperation.CUMULATIVE_ABSOLUTE_CHANGE,
        )
        self.assertEqual(derived_need.derivation.metric, "Resident population")
        self.assertEqual(derived_need.derivation.input_unit, "persons")
        self.assertEqual(derived_need.derivation.geography, "Ukraine")
        self.assertEqual(
            derived_need.derivation.required_periods,
            tuple(str(year) for year in range(2015, 2022)),
        )
        self.assertEqual(
            reloaded_template.research_design_snapshot.id,
            reloaded_project.current_research_design.id,
        )
        return reloaded_project, reloaded_template, reloaded_run

    def _distinct_b2_zip(self, marker):
        source = ir3_zip()
        with zipfile.ZipFile(io.BytesIO(source), "r") as archive:
            workbook_name = next(
                name for name in archive.namelist() if name.endswith(".xlsx")
            )
            workbook = load_workbook(io.BytesIO(archive.read(workbook_name)))
        workbook.active["F1"] = marker
        workbook_stream = io.BytesIO()
        workbook.save(workbook_stream)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(workbook_name, workbook_stream.getvalue())
        return output.getvalue()

    def _canonical_analysis(self, *, analyze=True, source_retriever=None):
        self.body = ir3_zip()
        project, template, workflow = self._persisted_planning_context()
        context = WorkflowContext(
            project=project,
            workflow_template=template,
            workflow_run=workflow,
        )
        acquisition = build_source_acquisition_service(
            config=postgresql_application_config(),
            overrides=ApplicationOverrides(
                search_provider=self._FixtureSearchProvider(self.origin),
                source_retriever=source_retriever or HttpSourceRetriever(
                    xlsx_extraction_revision="xlsx-structured-v2",
                ),
            ),
            source_repository=self.repo,
        )
        summary = acquisition.acquire_for_context(context)
        self.assertEqual(summary.sources_acquired, 3)
        self.assertTrue(summary.coverage_target_satisfied)
        self.assertEqual(len(summary.source_ids), 3)
        source_repository = PostgreSQLSourceRepository(self.session_factory)
        sources = [
            source_repository.get_by_id(source_id)
            for source_id in summary.source_ids
        ]
        self.assertTrue(all(source is not None for source in sources))
        self.assertEqual(len({source.id for source in sources if source is not None}), 3)
        source = sources[0]
        assert source is not None
        for persisted in sources:
            assert persisted is not None
            if source_retriever is None:
                self.assertEqual(persisted.content_checksum, source.content_checksum)
            else:
                self.assertEqual(
                    persisted.content_checksum,
                    sha256((persisted.content_text or "").encode("utf-8")).hexdigest(),
                )
            self.assertIn(workflow.id, persisted.workflow_run_refs)
            self.assertIn(template.research_design_snapshot.id, persisted.research_design_refs)
        # Public acquisition must scope the Source to the persisted run/template.
        self.assertIn(workflow.id, source.workflow_run_refs)
        self.assertIn(template.research_design_snapshot.id, source.research_design_refs)
        evidence_repository = PostgreSQLEvidenceRepository(self.session_factory)
        finding_repository = PostgreSQLFindingRepository(self.session_factory)
        insight_repository = PostgreSQLInsightRepository(self.session_factory)
        provider = __import__("unittest.mock", fromlist=["Mock"]).Mock()
        provider.generate.side_effect = AssertionError(
            "structured extraction must not call a provider"
        )
        extraction = build_evidence_extraction_service(
            config=postgresql_application_config(evidence_extractor="llm"),
            overrides=ApplicationOverrides(),
            evidence_repository=evidence_repository,
            source_repository=self.repo,
            llm_client=provider,
        )
        extraction.extract_for_source_ids(context, (source.id,), allow_empty=True)
        provider.generate.assert_not_called()
        readiness = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            evidence_repository=evidence_repository,
            source_repository=self.repo,
        ).assess_and_apply(context)
        analysis = None
        if analyze:
            analysis = AnalysisService(
                analysis_engine=CanonicalAnalysisEngine(),
                evidence_repository=evidence_repository,
                finding_repository=finding_repository,
                insight_repository=insight_repository,
                max_evidence_per_batch=100,
                max_chars_per_batch=1_000_000,
                source_repository=self.repo,
            ).analyze_for_context(context)
        accepted_ids = tuple(
            acquired_assessment(readiness).prerequisite_diagnostics[
                "qualifying_evidence_ids"
            ]
        )
        self.assertTrue(readiness.ready_for_analysis)
        self.assertEqual(len(accepted_ids), 7)
        if analyze:
            assert analysis is not None
            self.assertTrue(analysis.finding_ids and analysis.insight_ids)
        return context, source, accepted_ids, analysis

    def test_global_pipeline_persists_and_reloads_canonical_product(self):
        context, source, accepted_ids, analysis = self._canonical_analysis()
        summary = self._report_service().write_for_context(context)
        reports = PostgreSQLReportRepository(self.session_factory)
        claims = PostgreSQLReportClaimRepository(self.session_factory)
        report = reports.get_by_id(summary.report_id)
        stored_claims = claims.list_for_report(report.id, report.revision_number)
        self.assertTrue(stored_claims)
        self.assertEqual(
            {ref for claim in stored_claims for ref in claim.evidence_ids},
            set(accepted_ids),
        )
        self.assertTrue(set(report.finding_refs) <= set(analysis.finding_ids))
        self.assertTrue(set(report.insight_refs) <= set(analysis.insight_ids))
        findings = PostgreSQLFindingRepository(self.session_factory).list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )
        derived = [item for item in findings if item.metadata.get("derivation")]
        self.assertTrue(derived)
        self.assertTrue(all(
            item.metadata["derivation"]["validation_status"] == "validated"
            and set(item.metadata["derivation"]["input_evidence_ids"]) == set(item.evidence_refs)
            for item in derived
        ))
        self.assertTrue(report.citation_registry)

        fresh = DatabaseSessionFactory(self.engine)
        fresh_report = PostgreSQLReportRepository(fresh).get_by_id(report.id)
        fresh_claims = PostgreSQLReportClaimRepository(fresh).list_for_report(
            report.id, report.revision_number,
        )
        fresh_source = PostgreSQLSourceRepository(fresh).get_by_id(source.id)
        self.assertEqual(fresh_report.evidence_refs, report.evidence_refs)
        self.assertTrue(all(
            claim.evidence_content_digests and claim.source_ids
            for claim in fresh_claims
        ))
        evidence = PostgreSQLEvidenceRepository(fresh).list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )
        self.assertTrue(all(
            item.source_content_checksum == fresh_source.content_checksum
            for item in evidence if item.id in accepted_ids
        ))

    def test_h3_report_claims_persist_and_reload_with_structural_authority(self):
        context, source, accepted_ids, analysis = self._canonical_analysis()
        context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)

        def h3_candidates(request):
            claims = []
            for candidate in request["candidates"]:
                claim_id = candidate["claim_id"]
                catalog = candidate["authorized_catalog"]
                nodes = [{"node_type": "TEXT", "text": "Validated finding: "}]
                fact_ref = next(iter(catalog["facts"]), None)
                period_ref = next(iter(catalog["periods"]), None)
                if fact_ref is not None:
                    nodes.append({
                        "node_type": "FACT_REF", "owner_claim_ref": claim_id,
                        "authority_ref": fact_ref, "presentation_variant": "value_with_unit",
                    })
                if period_ref is not None:
                    nodes.extend((
                        {"node_type": "TEXT", "text": " in "},
                        {"node_type": "PERIOD_REF", "owner_claim_ref": claim_id,
                         "authority_ref": period_ref, "presentation_variant": "year"},
                    ))
                citation_ref = next(iter(catalog["citations"]), None)
                if citation_ref is not None:
                    nodes.append({
                        "node_type": "CITATION_REF", "owner_claim_ref": claim_id,
                        "authority_ref": citation_ref,
                    })
                claims.append({
                    "claim_id": claim_id, "kind": "observation",
                    "certainty": "direct", "direction": "not_applicable", "nodes": nodes,
                })
            return {"contract_version": H3_REPORT_CONTRACT, "claims": claims}

        class H3Engine:
            method_name = "h3-deterministic-test"

            @staticmethod
            def generate_h3_claim_candidates(request):
                return h3_candidates(request)

            @staticmethod
            def repair_h3_claim_candidates(request):
                return h3_candidates(request)

        class H3EditorialProvider:
            @staticmethod
            def compose(request):
                catalog = request["authority_catalog"]
                claim_id = next(iter(catalog["claims"]))
                fact_ref = next(iter(catalog["facts"]), None)
                period_ref = next(iter(catalog["periods"]), None)
                nodes = [{
                    "node_id": "n1", "node_type": "TEXT",
                    "owner_claim_ref": None, "text": "Validated result ",
                    "authority_ref": None, "presentation_variant": None,
                }]
                if fact_ref is not None:
                    nodes.append({
                        "node_id": "n2", "node_type": "FACT_REF",
                        "owner_claim_ref": claim_id, "text": None,
                        "authority_ref": fact_ref, "presentation_variant": "value_with_unit",
                    })
                if period_ref is not None:
                    nodes.extend((
                        {"node_id": "n3", "node_type": "TEXT",
                         "owner_claim_ref": None, "text": " in ",
                         "authority_ref": None, "presentation_variant": None},
                        {"node_id": "n4", "node_type": "PERIOD_REF",
                         "owner_claim_ref": claim_id, "text": None,
                         "authority_ref": period_ref, "presentation_variant": "year"},
                    ))
                return {
                    "contract_version": H3_REPORT_CONTRACT,
                    "typed_document": {
                        "contract_version": H3_REPORT_CONTRACT,
                        "document_id": request["report_id"],
                        "owner_id": request["report_id"],
                        "nodes": nodes,
                    },
                }

        service = ClaimFirstReportService(
            report_claim_repository=PostgreSQLReportClaimRepository(self.session_factory),
            report_contract_version=H3_REPORT_CONTRACT,
            report_engine=H3Engine(),
            h3_editorial_provider=H3EditorialProvider(),
            finding_repository=PostgreSQLFindingRepository(self.session_factory),
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=self.repo,
            report_repository=PostgreSQLReportRepository(self.session_factory),
            artifact_repository=PostgreSQLArtifactRepository(self.session_factory),
            max_findings_per_batch=10,
            max_chars_per_batch=10_000,
        )
        summary = service.write_for_context(context)
        reports = PostgreSQLReportRepository(self.session_factory)
        claims = PostgreSQLReportClaimRepository(self.session_factory)
        report = reports.get_by_id(summary.report_id)
        stored = claims.list_for_report(report.id, report.revision_number)
        self.assertEqual(report.metadata["structured_claim_contract"], H3_REPORT_CONTRACT)
        self.assertTrue(stored)
        self.assertTrue(all(item.contract_version == H3_REPORT_CONTRACT for item in stored))
        self.assertTrue(all(item.structural_assertion for item in stored))
        self.assertTrue(all(set(item.evidence_ids) <= set(accepted_ids) for item in stored))
        self.assertTrue(all(item.source_ids and item.citation_ids for item in stored))
        self.assertTrue(set(report.finding_refs) <= set(analysis.finding_ids))

        fresh = DatabaseSessionFactory(self.engine)
        fresh_report = PostgreSQLReportRepository(fresh).get_by_id(report.id)
        fresh_claims = PostgreSQLReportClaimRepository(fresh).list_for_report(
            report.id, report.revision_number,
        )
        fresh_source = PostgreSQLSourceRepository(fresh).get_by_id(source.id)
        self.assertEqual(fresh_report.metadata["structured_claim_contract"], H3_REPORT_CONTRACT)
        self.assertEqual(
            {item.claim_id for item in fresh_claims},
            {item.claim_id for item in stored},
        )
        self.assertTrue(all(item.contract_version == H3_REPORT_CONTRACT for item in fresh_claims))
        self.assertTrue(all(item.source_ids and item.citation_ids for item in fresh_claims))
        self.assertIsNotNone(fresh_source)

    def test_h3_approved_review_finalizes_and_reloads_pdf(self):
        # Reuse the existing production H3 report/claim fixture.
        self.test_h3_report_claims_persist_and_reload_with_structural_authority()
        reports = PostgreSQLReportRepository(self.session_factory)
        report = max(
            reports.list_for_project(self.project.id),
            key=lambda item: item.revision_number,
        )
        claims = PostgreSQLReportClaimRepository(self.session_factory)
        before = claims.list_for_report(report.id, report.revision_number)

        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(container.shutdown)
        project = container.project_service.get_project(self.project.id)
        run = container.workflow_service.get_workflow_run(report.workflow_run_id)
        template = container.workflow_service.get_template(run.workflow_template_id)
        review_task = next(
            task for task in run.tasks
            if getattr(task, "definition_id", None) == H3_REVIEW_1_DEFINITION
        )
        context = WorkflowContext(
            project=project, workflow_template=template, workflow_run=run,
            current_task=review_task,
        )
        context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)

        class ApprovedH3ReviewProvider:
            def review(self, request):
                return {"decision": "APPROVE", "issues": []}

        review = H3WorkflowReviewAdapter(
            report_repository=reports,
            report_claim_repository=claims,
            review_repository=PostgreSQLReviewRepository(self.session_factory),
            review_provider=ApprovedH3ReviewProvider(),
        ).review_for_context(context)
        self.assertEqual(review.verdict, "approve")
        persisted_review = PostgreSQLReviewRepository(self.session_factory).get_by_id(review.review_id)
        self.assertIsNotNone(persisted_review)
        self.assertEqual(persisted_review.verdict.value, "approve")

        finalized = container.project_deliverables_service.finalize_approved_review(
            project_id=self.project.id,
            report_id=report.id,
            review_id=review.review_id,
        )
        self.assertEqual(finalized["report_id"], report.id)
        self.assertEqual(finalized["review_id"], review.review_id)
        self.assertTrue(finalized["pdf_id"])

        after = claims.list_for_report(report.id, report.revision_number)
        self.assertEqual(
            {item.claim_id: item.authority_digest for item in after},
            {item.claim_id: item.authority_digest for item in before},
        )
        pdf, data = container.project_deliverables_service.download(
            self.project.id, "DESK", report.id, finalized["pdf_id"],
            owner_id=project.owner_principal_id,
        )
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertEqual(len(data), pdf.byte_size)
        self.assertEqual(sha256(data).hexdigest(), pdf.checksum)
        self.assertEqual(pdf.run_id, report.workflow_run_id)
        self.assertEqual(pdf.source_id, report.id)
        self.assertEqual(pdf.approved_delivery_provenance.review_id, review.review_id)

        fresh = DatabaseSessionFactory(self.engine)
        fresh_reports = PostgreSQLReportRepository(fresh)
        fresh_report = fresh_reports.get_by_id(report.id)
        fresh_review = PostgreSQLReviewRepository(fresh).get_by_id(review.review_id)
        fresh_claims = PostgreSQLReportClaimRepository(fresh).list_for_report(
            report.id, report.revision_number,
        )
        self.assertEqual(fresh_report.id, report.id)
        self.assertEqual(fresh_review.verdict.value, "approve")
        self.assertEqual(
            {item.claim_id for item in fresh_claims},
            {item.claim_id for item in before},
        )
        fresh_pdf, fresh_data = container.project_deliverables_service.download(
            self.project.id, "DESK", report.id, finalized["pdf_id"],
            owner_id=project.owner_principal_id,
        )
        self.assertEqual(fresh_data, data)
        self.assertEqual(fresh_pdf.checksum, pdf.checksum)
        self.assertEqual(
            fresh_pdf.approved_delivery_provenance.review_id,
            review.review_id,
        )

    def test_h3_approved_review_finalizes_and_reloads_pptx(self):
        # Reuse the complete production H3 Review -> finalization fixture.
        self.test_h3_approved_review_finalizes_and_reloads_pdf()
        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(container.shutdown)
        project = container.project_service.get_project(self.project.id)
        report = max(
            container.report_query_service.list_reports_for_project(self.project.id),
            key=lambda item: item.revision_number,
        )
        catalog_item = container.project_deliverables_service.source(
            self.project.id, "DESK", report.id,
            owner_id=project.owner_principal_id,
        )
        self.assertIsNotNone(catalog_item.presentation_job)
        job = catalog_item.presentation_job
        if job.state not in {"completed", "finalization_complete"}:
            self.assertTrue(
                container.project_deliverables_service.process_next_presentation(
                    "ir6-c3-pptx-worker",
                )
            )
            catalog_item = container.project_deliverables_service.source(
                self.project.id, "DESK", report.id,
                owner_id=project.owner_principal_id,
            )
            job = catalog_item.presentation_job
        self.assertIn(job.state, {"completed", "finalization_complete"})
        self.assertIsNotNone(catalog_item.pptx)
        pptx = catalog_item.pptx
        record, data = container.project_deliverables_service.download_presentation(
            self.project.id, "DESK", report.id, pptx.id,
            owner_id=project.owner_principal_id,
        )
        self.assertTrue(data.startswith(b"PK\x03\x04"))
        self.assertEqual(len(data), record.byte_size)
        self.assertEqual(sha256(data).hexdigest(), record.checksum)
        self.assertEqual(record.project_id, self.project.id)
        self.assertEqual(record.run_id, report.workflow_run_id)
        self.assertEqual(record.source_id, report.id)
        self.assertEqual(record.approved_delivery_provenance.review_id, job.review_id)
        self.assertEqual(
            record.approved_delivery_provenance.claim_set_digest,
            job.claim_set_digest,
        )
        self.assertEqual(
            record.approved_delivery_provenance.coverage_contract_digest,
            job.coverage_contract_digest,
        )

        fresh = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        fresh_project = fresh.project_service.get_project(self.project.id)
        fresh_report = max(
            fresh.report_query_service.list_reports_for_project(self.project.id),
            key=lambda item: item.revision_number,
        )
        fresh_item = fresh.project_deliverables_service.source(
            self.project.id, "DESK", fresh_report.id,
            owner_id=fresh_project.owner_principal_id,
        )
        self.assertIsNotNone(fresh_item.presentation_job)
        self.assertIn(fresh_item.presentation_job.state, {"completed", "finalization_complete"})
        fresh_record, fresh_data = fresh.project_deliverables_service.download_presentation(
            self.project.id, "DESK", fresh_report.id, fresh_item.pptx.id,
            owner_id=fresh_project.owner_principal_id,
        )
        self.assertEqual(fresh_data, data)
        self.assertEqual(fresh_record.checksum, record.checksum)
        self.assertEqual(
            fresh_record.approved_delivery_provenance,
            record.approved_delivery_provenance,
        )

    def _h3_review_without_finalization(self):
        self.test_h3_report_claims_persist_and_reload_with_structural_authority()
        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(container.shutdown)
        project = container.project_service.get_project(self.project.id)
        report = max(
            container.report_query_service.list_reports_for_project(self.project.id),
            key=lambda item: item.revision_number,
        )
        run = container.workflow_service.get_workflow_run(report.workflow_run_id)
        template = container.workflow_service.get_template(run.workflow_template_id)
        task = next(
            item for item in run.tasks
            if getattr(item, "definition_id", None) == H3_REVIEW_1_DEFINITION
        )
        context = WorkflowContext(
            project=project, workflow_template=template, workflow_run=run,
            current_task=task,
        )
        context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)

        class ApprovedProvider:
            @staticmethod
            def review(request):
                return {"decision": "APPROVE", "issues": []}

        review = H3WorkflowReviewAdapter(
            report_repository=PostgreSQLReportRepository(self.session_factory),
            report_claim_repository=PostgreSQLReportClaimRepository(self.session_factory),
            review_repository=PostgreSQLReviewRepository(self.session_factory),
            review_provider=ApprovedProvider(),
        ).review_for_context(context)
        return container, project, report, review

    def _assert_h3_finalization_rejected(self, mutate):
        container, project, report, review = self._h3_review_without_finalization()
        mutate(report, review)
        with self.assertRaises(DeliverableFinalizationError):
            container.project_deliverables_service.finalize_approved_review(
                project_id=self.project.id,
                report_id=report.id,
                review_id=review.review_id,
            )
        item = container.project_deliverables_service.source(
            self.project.id, "DESK", report.id,
            owner_id=project.owner_principal_id,
        )
        self.assertIsNone(item.pdf)
        self.assertIsNone(item.pptx)
        if item.presentation_job is not None:
            self.assertNotIn(item.presentation_job.state, {"completed", "finalization_complete"})

        fresh = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        fresh_project = fresh.project_service.get_project(self.project.id)
        fresh_item = fresh.project_deliverables_service.source(
            self.project.id, "DESK", report.id,
            owner_id=fresh_project.owner_principal_id,
        )
        self.assertIsNone(fresh_item.pdf)
        self.assertIsNone(fresh_item.pptx)
        if fresh_item.presentation_job is not None:
            self.assertNotIn(fresh_item.presentation_job.state, {"completed", "finalization_complete"})

    def test_h3_stale_review_report_revision_rejects_delivery(self):
        def mutate(report, review):
            with self.session_factory.session() as session:
                session.execute(
                    update(ReportModel)
                    .where(ReportModel.id == report.id)
                    .values(revision_number=report.revision_number + 1)
                )

        self._assert_h3_finalization_rejected(mutate)

    def test_h3_tampered_claim_set_digest_rejects_delivery(self):
        def mutate(report, review):
            # PostgreSQL immutability is itself an acceptance assertion.
            from sqlalchemy.exc import DBAPIError

            with self.session_factory.session() as session:
                claim = session.query(ReportClaimModel).filter_by(
                    report_id=report.id,
                    report_revision=report.revision_number,
                ).first()
                self.assertIsNotNone(claim)
                claim.authority_digest = "0" * 64
                with self.assertRaisesRegex(DBAPIError, "report_claims are immutable"):
                    session.flush()
                session.rollback()
            # Model tampering through the permitted JSON metadata seam; the
            # delivery authority must reject the digest mismatch.
            with self.session_factory.session() as session:
                persisted = session.get(ReportModel, report.id)
                metadata = dict(persisted.metadata_json or {})
                presentation = dict(metadata.get("h3_presentation") or {})
                presentation["claim_set_digest"] = "0" * 64
                metadata["h3_presentation"] = presentation
                session.execute(
                    update(ReportModel)
                    .where(ReportModel.id == report.id)
                    .values(metadata_json=metadata)
                )

        self._assert_h3_finalization_rejected(mutate)

    def test_h3_mismatched_source_provenance_rejects_delivery(self):
        def mutate(report, review):
            with self.session_factory.session() as session:
                session.execute(
                    update(ReportModel)
                    .where(ReportModel.id == report.id)
                    .values(workflow_run_id="foreign-h3-run")
                )

        container, project, report, review = self._h3_review_without_finalization()
        mutate(report, review)
        with self.assertRaises(DeliverableFinalizationError):
            container.project_deliverables_service.finalize_approved_review(
                project_id=self.project.id,
                report_id=report.id,
                review_id=review.review_id,
            )
        with self.assertRaises(AccessDeniedError):
            container.project_deliverables_service.source(
                self.project.id, "DESK", report.id,
                owner_id=project.owner_principal_id,
            )
        fresh = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        fresh_project = fresh.project_service.get_project(self.project.id)
        with self.assertRaises(AccessDeniedError):
            fresh.project_deliverables_service.source(
                self.project.id, "DESK", report.id,
                owner_id=fresh_project.owner_principal_id,
            )

    def _assert_product_completion_not_ready_after_full_delivery(self, mutate):
        self.test_h3_approved_review_finalizes_and_reloads_pptx()
        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(container.shutdown)
        run = max(
            PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id),
            key=lambda item: item.revision_number,
        ).workflow_run_id
        mutate(run)
        projection = container.research_run_result_query_service.product_completion(
            run, evaluated_at="fixed",
        )
        self.assertNotEqual(projection.status.value, "READY")
        fresh = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        reloaded = fresh.research_run_result_query_service.product_completion(
            run, evaluated_at="fixed",
        )
        self.assertEqual(reloaded.status, projection.status)
        self.assertEqual(reloaded.blocking_codes, projection.blocking_codes)

    def test_valid_h3_delivery_without_terminal_research_is_not_ready(self):
        self.test_h3_approved_review_finalizes_and_reloads_pptx()
        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(container.shutdown)
        run = max(
            PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id),
            key=lambda item: item.revision_number,
        ).workflow_run_id
        projection = container.research_run_result_query_service.product_completion(
            run, evaluated_at="fixed",
        )
        diagnostic_report = max(
            PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id),
            key=lambda item: item.revision_number,
        )
        diagnostic_project = container.project_service.get_project(self.project.id)
        diagnostic_item = container.project_deliverables_service.source(
            self.project.id, "DESK", diagnostic_report.id,
            owner_id=diagnostic_project.owner_principal_id,
        )
        diagnostic_reviews = PostgreSQLReviewRepository(self.session_factory).list_for_project(
            self.project.id, workflow_run_id=run, report_id=diagnostic_report.id,
        )
        self.assertEqual(projection.status.value, "NOT_READY")
        self.assertIn("workflow_not_terminal", projection.blocking_codes)
        self.assertIn("research_outcome_not_completed", projection.blocking_codes)
        fresh = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        reloaded = fresh.research_run_result_query_service.product_completion(
            run, evaluated_at="fixed",
        )
        self.assertEqual(reloaded.status, projection.status)
        self.assertEqual(reloaded.blocking_codes, projection.blocking_codes)
        self.assertIn("workflow_not_terminal", reloaded.blocking_codes)
        self.assertIn("research_outcome_not_completed", reloaded.blocking_codes)

    def test_product_completion_is_not_ready_for_incomplete_persisted_research(self):
        project, template, workflow = self._persisted_planning_context()
        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(container.shutdown)
        projection = container.research_run_result_query_service.product_completion(
            workflow.id, evaluated_at="fixed",
        )
        self.assertNotEqual(projection.status.value, "READY")
        self.assertIn("workflow_not_terminal", projection.blocking_codes)

    def test_product_completion_is_not_ready_when_pdf_is_missing(self):
        # The legitimate missing-delivery state is the persisted approved
        # review before finalization; completed immutable deliverables are not
        # deleted or modified to manufacture the scenario.
        container, project, report, review = self._h3_review_without_finalization()
        projection = container.research_run_result_query_service.product_completion(
            report.workflow_run_id, evaluated_at="fixed",
        )
        self.assertNotEqual(projection.status.value, "READY")
        self.assertIn("pdf_not_terminal", projection.blocking_codes)
        self.assertIn("pptx_not_terminal_success", projection.blocking_codes)
        fresh = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        reloaded = fresh.research_run_result_query_service.product_completion(
            report.workflow_run_id, evaluated_at="fixed",
        )
        self.assertEqual(reloaded.status, projection.status)
        self.assertEqual(reloaded.blocking_codes, projection.blocking_codes)

    def test_product_completion_rejects_stale_h3_authority(self):
        def tamper_digest(run_id):
            report = max(
                PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id),
                key=lambda item: item.revision_number,
            )
            with self.session_factory.session() as session:
                metadata = dict(session.get(ReportModel, report.id).metadata_json or {})
                presentation = dict(metadata.get("h3_presentation") or {})
                presentation["claim_set_digest"] = "0" * 64
                metadata["h3_presentation"] = presentation
                session.execute(
                    update(ReportModel).where(ReportModel.id == report.id)
                    .values(metadata_json=metadata)
                )

        self._assert_product_completion_not_ready_after_full_delivery(tamper_digest)

    def test_product_completion_rejects_nonterminal_pptx_job(self):
        def make_pending(run_id):
            with self.session_factory.session() as session:
                session.query(PresentationJobModel).filter(
                    PresentationJobModel.project_id == self.project.id,
                ).update({"state": "pptx_pending"}, synchronize_session=False)

        self._assert_product_completion_not_ready_after_full_delivery(make_pending)

    def test_product_completion_canonical_workflow_execution_probe(self):
        """Probe the real durable worker path without adding downstream artifacts."""
        self.body = ir3_zip()
        planner_llm = self._canonical_quantitative_planner_llm()

        def h3_candidates(request):
            claims = []
            for candidate in request["candidates"]:
                claim_id = candidate["claim_id"]
                catalog = candidate["authorized_catalog"]
                nodes = [{"node_type": "TEXT", "text": "Validated finding: "}]
                fact_ref = next(iter(catalog["facts"]), None)
                period_ref = next(iter(catalog["periods"]), None)
                if fact_ref is not None:
                    nodes.append({
                        "node_type": "FACT_REF", "owner_claim_ref": claim_id,
                        "authority_ref": fact_ref, "presentation_variant": "value_with_unit",
                    })
                if period_ref is not None:
                    nodes.extend((
                        {"node_type": "TEXT", "text": " in "},
                        {"node_type": "PERIOD_REF", "owner_claim_ref": claim_id,
                         "authority_ref": period_ref, "presentation_variant": "year"},
                    ))
                citation_ref = next(iter(catalog["citations"]), None)
                if citation_ref is not None:
                    nodes.append({
                        "node_type": "CITATION_REF", "owner_claim_ref": claim_id,
                        "authority_ref": citation_ref,
                    })
                claims.append({
                    "claim_id": claim_id, "kind": "observation", "certainty": "direct",
                    "direction": "not_applicable", "nodes": nodes,
                })
            return {"contract_version": H3_REPORT_CONTRACT, "claims": claims}

        class DeterministicH3Engine:
            method_name = "h3-deterministic-worker-probe"

            @staticmethod
            def generate_h3_claim_candidates(request):
                return h3_candidates(request)

            @staticmethod
            def repair_h3_claim_candidates(request):
                return h3_candidates(request)

        class DeterministicH3EditorialProvider:
            @staticmethod
            def compose(request):
                catalog = request["authority_catalog"]
                claim_id = next(iter(catalog["claims"]))
                fact_ref = next(iter(catalog["facts"]), None)
                period_ref = next(iter(catalog["periods"]), None)
                nodes = [{
                    "node_id": "n1", "node_type": "TEXT", "owner_claim_ref": None,
                    "text": "Validated result ", "authority_ref": None,
                    "presentation_variant": None,
                }]
                if fact_ref is not None:
                    nodes.append({
                        "node_id": "n2", "node_type": "FACT_REF",
                        "owner_claim_ref": claim_id, "text": None,
                        "authority_ref": fact_ref, "presentation_variant": "value_with_unit",
                    })
                if period_ref is not None:
                    nodes.extend((
                        {"node_id": "n3", "node_type": "TEXT", "owner_claim_ref": None,
                         "text": " in ", "authority_ref": None, "presentation_variant": None},
                        {"node_id": "n4", "node_type": "PERIOD_REF",
                         "owner_claim_ref": claim_id, "text": None,
                         "authority_ref": period_ref, "presentation_variant": "year"},
                    ))
                return {
                    "contract_version": H3_REPORT_CONTRACT,
                    "typed_document": {
                        "contract_version": H3_REPORT_CONTRACT,
                        "document_id": request["report_id"],
                        "owner_id": request["report_id"], "nodes": nodes,
                    },
                }

        class ApprovedH3ReviewProvider:
            @staticmethod
            def review(request):
                return {"decision": "APPROVE", "issues": []}

        container = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(
                llm_client=planner_llm,
                report_engine=DeterministicH3Engine(),
                h3_editorial_provider=DeterministicH3EditorialProvider(),
                h3_review_provider=ApprovedH3ReviewProvider(),
                search_provider=self._FixtureSearchProvider(self.origin),
                source_retriever=HttpSourceRetriever(
                    xlsx_extraction_revision="xlsx-structured-v2",
                ),
            ),
        )
        self.addCleanup(container.shutdown)
        self.assertIsNotNone(container.durable_workflow_service)
        self.assertIsNotNone(container.worker_execution_service)
        container.agency.initialize()

        project = container.project_service.get_project(self.project.id)
        project.owner_principal_id = "ir6-owner"
        project.selected_methods = ("DESK",)
        container.project_service.save_project(project)
        brief = ResearchBrief(
            title="Resident population",
            business_question="Resident population of Ukraine",
            timeframe="2015–2021",
        )
        planning = container.project_planning_service
        planning.save_brief(project, brief)
        project = container.project_service.get_project(self.project.id)
        planning.generate_design(project)
        project = container.project_service.get_project(self.project.id)
        planning.approve_design(
            project,
            actor_id="ir6-owner",
            expected_design_id=project.current_research_design.id,
        )
        project = container.project_service.get_project(self.project.id)
        template = ResearchDesignWorkflowMapper(
            desk_report_contract_version=H3_REPORT_CONTRACT,
        ).from_research_design(project.current_research_design, project)
        template.id = "ir6-d7-execution-template"
        template.name = "IR-6D7 canonical execution probe"

        run_id = str(uuid4())
        submitted = container.agency.start_research_from_template(
            project, template, run_id=run_id,
        )
        processed = container.worker_execution_service.drain_runnable_runs(
            "ir6-d7-worker",
        )
        persisted = container.workflow_service.get_workflow_run(submitted.workflow_run.id)
        self.assertEqual(persisted.status.value, "paused")
        self.assertFalse(any(task.status.value == "failed" for task in persisted.tasks))
        finalization_task = next(
            task for task in persisted.tasks
            if task.definition_id == "task-finalize-deliverables"
        )
        self.assertEqual(finalization_task.status.value, "paused")
        presentation_processed = container.project_deliverables_service.process_next_presentation(
            "ir6-d7-pptx-worker",
        )
        self.assertTrue(presentation_processed)
        persisted = container.workflow_service.get_workflow_run(submitted.workflow_run.id)
        task_results = container.workflow_service.get_task_results(persisted.id)
        diagnostic_keys = (
            "research_readiness", "research_product_outcome",
            DESK_REPORT_CONTRACT_PIN, "report_generation_diagnostics",
            "review_diagnostics", "desk_deliverable_finalization",
        )
        diagnostic_results = {}
        for key in diagnostic_keys:
            value = task_results.get(key)
            if isinstance(value, dict):
                diagnostic_results[key] = {
                    field: value.get(field)
                    for field in (
                        "status", "outcome", "code", "reason", "failure_code",
                        "failure_category", "phase", "category", "contract_version",
                    )
                    if field in value
                }
            elif value is not None:
                diagnostic_results[key] = value
        execution_port = getattr(container.worker_execution_service, "_execution_port", None)
        lease = (
            execution_port.get_lease(persisted.id)
            if execution_port is not None and hasattr(execution_port, "get_lease")
            else None
        )
        self.assertTrue(processed >= 1)
        self.assertTrue(persisted.is_terminal)
        self.assertFalse(any(task.status.value == "failed" for task in persisted.tasks))
        self.assertEqual(persisted.status.value, "completed")
        finalization_task = next(
            task for task in persisted.tasks
            if task.definition_id == "task-finalize-deliverables"
        )
        self.assertEqual(finalization_task.status.value, "completed")
        self.assertEqual(
            task_results.get(DESK_REPORT_CONTRACT_PIN),
            H3_REPORT_CONTRACT,
        )
        readiness_payload = extract_research_readiness(task_results)
        persisted_outcome = extract_research_product_outcome(task_results)
        self.assertIsInstance(readiness_payload, dict)
        self.assertIsInstance(persisted_outcome, dict)
        self.assertEqual(persisted_outcome.get("outcome"), "COMPLETED")
        result = container.research_run_result_query_service.get_for_run(persisted.id)
        self.assertEqual(result.outcome.value, "COMPLETED")
        reports = PostgreSQLReportRepository(self.session_factory).list_for_project(
            self.project.id, workflow_run_id=persisted.id,
        )
        self.assertTrue(reports)
        latest_report = max(reports, key=lambda item: item.revision_number)
        claims = tuple(
            claim
            for report in reports
            for claim in PostgreSQLReportClaimRepository(self.session_factory).list_for_report(
                report.id, report.revision_number,
            )
        )
        project = container.project_service.get_project(self.project.id)
        catalog_item = container.project_deliverables_service.source(
            self.project.id, "DESK", latest_report.id,
            owner_id=project.owner_principal_id,
        )
        self.assertIsNotNone(catalog_item.pdf)
        self.assertIsNotNone(catalog_item.pptx)
        self.assertIn(
            catalog_item.presentation_job.state,
            {"finalization_complete", "completed"},
        )
        fresh = create_application_container(
            config=postgresql_application_config(
                desk_report_contract_version=H3_REPORT_CONTRACT,
            ),
            overrides=ApplicationOverrides(),
        )
        self.addCleanup(fresh.shutdown)
        fresh_result = fresh.research_run_result_query_service.get_for_run(persisted.id)
        self.assertEqual(fresh_result.outcome.value, "COMPLETED")
        fresh_completion = fresh.research_run_result_query_service.product_completion(
            persisted.id, evaluated_at="fixed",
        )
        self.assertEqual(fresh_completion.status.value, "READY")
        self.assertEqual(fresh_completion.blocking_codes, ())

    def _assert_h3_authority_rejects(self, mutate):
        context, _, accepted_ids, _ = self._canonical_analysis()
        context.write_shared(DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT)
        mutate(context, accepted_ids)
        with self.assertRaises(H3ReportOutcomeError):
            self._h3_negative_report_service().write_for_context(context)
        reports = PostgreSQLReportRepository(self.session_factory)
        self.assertEqual(reports.list_for_project(self.project.id), [])
        with self.session_factory.session() as session:
            self.assertEqual(
                session.query(ReportClaimModel)
                .filter_by(project_id=self.project.id)
                .count(),
                0,
            )
        fresh = DatabaseSessionFactory(self.engine)
        self.assertEqual(PostgreSQLReportRepository(fresh).list_for_project(self.project.id), [])
        with fresh.session() as session:
            self.assertEqual(
                session.query(ReportClaimModel)
                .filter_by(project_id=self.project.id)
                .count(),
                0,
            )

    def test_h3_foreign_workflow_evidence_is_rejected(self):
        def mutate(context, accepted_ids):
            repository = PostgreSQLEvidenceRepository(self.session_factory)
            original = repository.get_by_id(accepted_ids[0])
            foreign = replace(
                original,
                id=str(uuid4()),
                workflow_run_id="foreign-h3-run",
                deduplication_key=f"h3-foreign-{uuid4().hex[:20]}",
            )
            repository.create(foreign)
            finding = PostgreSQLFindingRepository(self.session_factory).list_for_project(
                self.project.id, workflow_run_id=context.workflow_run.id,
            )[0]
            with self.session_factory.session() as session:
                session.execute(
                    update(FindingModel)
                    .where(FindingModel.id == finding.id)
                    .values(evidence_refs=[foreign.id])
                )

        self._assert_h3_authority_rejects(mutate)

    def test_h3_tampered_finding_lineage_is_rejected(self):
        def mutate(context, accepted_ids):
            finding = PostgreSQLFindingRepository(self.session_factory).list_for_project(
                self.project.id, workflow_run_id=context.workflow_run.id,
            )[0]
            with self.session_factory.session() as session:
                session.execute(
                    update(FindingModel)
                    .where(FindingModel.id == finding.id)
                    .values(evidence_refs=["missing-h3-evidence"])
                )

        self._assert_h3_authority_rejects(mutate)

    def test_h3_invalid_citation_provenance_is_rejected(self):
        def mutate(context, accepted_ids):
            evidence = PostgreSQLEvidenceRepository(self.session_factory).get_by_id(accepted_ids[0])
            metadata = dict(evidence.metadata)
            locator = dict(evidence.source_locator)
            structured = dict(locator.get("structured") or {})
            structured["raw_workbook_checksum"] = "0" * 64
            locator["structured"] = structured
            metadata["workbook_provenance"] = structured
            with self.session_factory.session() as session:
                session.execute(
                    update(EvidenceModel)
                    .where(EvidenceModel.id == evidence.id)
                    .values(metadata_json=metadata, source_locator=locator)
                )

        self._assert_h3_authority_rejects(mutate)

    def test_global_pipeline_rejects_unvalidated_finding_before_persistence(self):
        context, _, _, _ = self._canonical_analysis()
        findings = PostgreSQLFindingRepository(self.session_factory)
        existing = findings.list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )[0]
        findings.create(replace(
            existing, id="ir6-unvalidated", deduplication_key="ir6-unvalidated-key",
            metadata={},
        ))
        with self.assertRaises(ReportError):
            self._report_service().write_for_context(context)
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(
                self.project.id,
            ),
            [],
        )

    def test_global_outcome_does_not_promote_partial_or_insufficient_to_completed(self):
        payload = {
            "analysis_eligible_information_need_ids": ["in-1", "in-2"],
            "blocking_information_need_ids": ["in-2"],
        }
        self.assertNotEqual(
            derive_authoritative_outcome(
                required_information_need_ids=("in-1", "in-2"),
                readiness_payload=payload, findings=(), evidence=(),
                project_id=self.project.id, workflow_run_id="missing",
                research_design_id="missing",
            )[0],
            "COMPLETED",
        )

    def test_source_acquisition_failure_leaves_no_analysis_or_report(self):
        project, template, workflow = self._persisted_planning_context()
        self.body = b"not-a-supported-xlsx-or-zip-document"
        failed_source = self.acquire(workflow.id)
        # SourceAcquisitionService persists a typed failed Source and returns
        # it from this bounded group-resolution API; it does not raise here.
        self.assertNotEqual(failed_source.retrieval_status.value, "acquired")
        self.assertTrue(self.repo.list_for_project(project.id))
        self.assertEqual(
            PostgreSQLEvidenceRepository(self.session_factory).list_for_project(
                project.id, workflow_run_id=workflow.id,
            ),
            [],
        )
        self.assertEqual(
            PostgreSQLFindingRepository(self.session_factory).list_for_project(
                project.id, workflow_run_id=workflow.id,
            ),
            [],
        )
        self.assertEqual(
            PostgreSQLInsightRepository(self.session_factory).list_for_project(
                project.id, workflow_run_id=workflow.id,
            ),
            [],
        )
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(project.id),
            [],
        )
        with self.session_factory.session() as session:
            self.assertEqual(
                session.query(ReportClaimModel).filter_by(project_id=project.id).count(),
                0,
            )

    def test_rejected_qualification_keeps_readiness_and_product_insufficient(self):
        project, template, workflow = self._persisted_planning_context()
        context = WorkflowContext(
            project=project, workflow_template=template, workflow_run=workflow,
        )
        readiness = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=self.repo,
        ).assess_and_apply(context)
        self.assertFalse(readiness.ready_for_analysis)
        outcome, _ = derive_authoritative_outcome(
            required_information_need_ids=("in",),
            readiness_payload=context.read_shared("research_readiness"),
            findings=(), evidence=(), project_id=project.id,
            workflow_run_id=workflow.id,
            research_design_id=template.research_design_snapshot.id,
        )
        self.assertNotEqual(outcome, "COMPLETED")
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(project.id),
            [],
        )

    def test_report_persistence_failure_leaves_no_partial_report_or_claims(self):
        context, _, _, _ = self._canonical_analysis()

        class FailingClaims:
            def __init__(self, delegate):
                self.delegate = delegate

            def __getattr__(self, name):
                return getattr(self.delegate, name)

            def create_with_report(self, report, claims):
                raise RuntimeError("forced IR-6 persistence failure")

        service = self._report_service()
        service._report_claim_repository = FailingClaims(
            service._report_claim_repository,
        )
        with self.assertRaises(RuntimeError):
            service.write_for_context(context)
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(
                self.project.id,
            ),
            [],
        )
        with self.session_factory.session() as session:
            self.assertEqual(
                session.query(ReportClaimModel).filter_by(project_id=self.project.id).count(),
                0,
            )

    def test_tampered_derived_lineage_rejects_report_claims_and_report(self):
        context, _, _, _ = self._canonical_analysis()
        findings = PostgreSQLFindingRepository(self.session_factory)
        derived = next(
            item for item in findings.list_for_project(
                self.project.id, workflow_run_id=context.workflow_run.id,
            ) if item.metadata.get("derivation")
        )
        metadata = dict(derived.metadata)
        derivation = dict(metadata["derivation"])
        derivation["input_finding_ids"] = ["foreign-finding-id"]
        derivation["input_evidence_ids"] = ["foreign-evidence-id"]
        metadata["derivation"] = derivation
        with self.session_factory.session() as session:
            session.execute(
                update(FindingModel)
                .where(FindingModel.id == derived.id)
                .values(metadata_json=metadata)
            )

        with self.assertRaises(ReportError):
            self._report_service().write_for_context(context)
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(
                self.project.id,
            ),
            [],
        )
        with self.session_factory.session() as session:
            self.assertEqual(
                session.query(ReportClaimModel).filter_by(project_id=self.project.id).count(),
                0,
            )

    def test_new_source_revision_cannot_replace_pinned_analysis_provenance(self):
        context, source, accepted_ids, _ = self._canonical_analysis()
        original = PostgreSQLSourceRepository(self.session_factory).get_by_id(source.id)
        self.assertIsNotNone(original)
        assert original is not None
        changed_text = (original.content_text or "") + "\nchanged revision"
        changed_raw = changed_text.encode("utf-8")
        replacement = replace(
            original,
            id=str(uuid4()),
            content_text=changed_text,
            content_checksum=sha256(changed_text.encode("utf-8")).hexdigest(),
            raw_content_checksum=sha256(changed_raw).hexdigest(),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            version=0,
        )
        new_revision = self.repo.create_immutable_revision(replacement)
        self.assertNotEqual(new_revision.id, original.id)
        self.assertGreater(new_revision.content_revision, original.content_revision)

        summary = self._report_service().write_for_context(context)
        report = PostgreSQLReportRepository(self.session_factory).get_by_id(summary.report_id)
        claims = PostgreSQLReportClaimRepository(self.session_factory).list_for_report(
            report.id, report.revision_number,
        )
        self.assertTrue(claims)
        self.assertTrue(set(report.evidence_refs) <= set(accepted_ids))
        self.assertTrue(all(source.id in claim.source_ids for claim in claims))
        self.assertTrue(all(new_revision.id not in claim.source_ids for claim in claims))
        evidence = PostgreSQLEvidenceRepository(self.session_factory).list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )
        self.assertTrue(all(item.source_id == original.id for item in evidence if item.id in accepted_ids))
        self.assertTrue(all(item.source_content_checksum == original.content_checksum for item in evidence if item.id in accepted_ids))

    def _assert_foreign_evidence_isolation(self, field):
        context, _, accepted_ids, _ = self._canonical_analysis()
        evidence_repository = PostgreSQLEvidenceRepository(self.session_factory)
        canonical = evidence_repository.get_by_id(accepted_ids[0])
        self.assertIsNotNone(canonical)
        assert canonical is not None
        foreign_id = str(uuid4())
        values = {
            "id": foreign_id,
            "deduplication_key": f"ir6-fe-{field[:3]}-{foreign_id[:16]}",
        }
        if field == "project_id":
            project_repository = PostgreSQLProjectRepository(
                self.session_factory,
            )
            foreign_project = ProjectFactory().create("IR-6 foreign project")
            project_repository.create(foreign_project)
            values["project_id"] = foreign_project.id
        elif field == "workflow_run_id":
            values["workflow_run_id"] = "foreign-run"
        elif field == "research_design_id":
            values["research_design_id"] = "foreign-design"
        else:
            raise AssertionError(field)
        self.assertLessEqual(len(values["id"]), 36)
        self.assertLessEqual(len(values["deduplication_key"]), 64)
        foreign = replace(canonical, **values)
        evidence_repository.create(foreign)
        self.assertIsNotNone(evidence_repository.get_by_id(foreign_id))

        findings = PostgreSQLFindingRepository(self.session_factory)
        existing = findings.list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )[0]
        foreign_finding_id = str(uuid4())
        foreign_finding_key = f"ir6-ff-{field[:3]}-{foreign_id[:16]}"
        self.assertLessEqual(len(foreign_finding_id), 36)
        self.assertLessEqual(len(foreign_finding_key), 64)
        findings.create(replace(
            existing,
            id=foreign_finding_id,
            deduplication_key=foreign_finding_key,
            evidence_refs=(foreign_id,),
        ))

        # Analysis reads only the current project/run/design authority set.
        AnalysisService(
            analysis_engine=CanonicalAnalysisEngine(),
            evidence_repository=evidence_repository,
            finding_repository=findings,
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            max_evidence_per_batch=100,
            max_chars_per_batch=1_000_000,
            source_repository=self.repo,
        ).analyze_for_context(context)
        persisted = findings.list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )
        canonical_findings = [
            item for item in persisted
            if item.id != foreign_finding_id
        ]
        self.assertTrue(canonical_findings)
        self.assertTrue(all(foreign_id not in item.evidence_refs for item in canonical_findings))

        with self.assertRaises(ReportError):
            self._report_service().write_for_context(context)
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(
                self.project.id,
            ),
            [],
        )
        with self.session_factory.session() as session:
            self.assertEqual(
                session.query(ReportClaimModel).filter_by(project_id=self.project.id).count(),
                0,
            )

    def test_foreign_project_evidence_is_rejected_by_analysis_and_claim_authority(self):
        self._assert_foreign_evidence_isolation("project_id")

    def test_foreign_workflow_run_evidence_is_rejected_by_analysis_and_claim_authority(self):
        self._assert_foreign_evidence_isolation("workflow_run_id")

    def test_foreign_design_evidence_is_rejected_by_analysis_and_claim_authority(self):
        self._assert_foreign_evidence_isolation("research_design_id")

    def _readiness_with_source_origins(self, origin_for_source):
        variant_bodies = {
            "1": self._distinct_b2_zip("IR6-B2-source-a"),
            "2": self._distinct_b2_zip("IR6-B2-source-b"),
            "3": self._distinct_b2_zip("IR6-B2-source-a"),
        }
        retriever = HttpSourceRetriever(xlsx_extraction_revision="xlsx-structured-v2")
        owner = self

        class VariantRetriever:
            xlsx_extraction_revision = "xlsx-structured-v2"

            def known_unsupported_url(self, url):
                return retriever.known_unsupported_url(url)

            def retrieve(self, candidate):
                index = candidate.url.rsplit("/", 1)[-1]
                previous = owner.body
                owner.body = variant_bodies.get(index, variant_bodies["1"])
                try:
                    return retriever.retrieve(candidate)
                finally:
                    owner.body = previous

        context, _, _, _ = self._canonical_analysis(
            source_retriever=VariantRetriever(),
        )
        source_repository = PostgreSQLSourceRepository(self.session_factory)
        sources = source_repository.list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )
        self.assertGreaterEqual(len(sources), 2)
        evidence_repository = PostgreSQLEvidenceRepository(self.session_factory)
        provider = Mock()
        provider.generate.side_effect = AssertionError(
            "structured extraction must not call a provider",
        )
        extraction = build_evidence_extraction_service(
            config=postgresql_application_config(evidence_extractor="llm"),
            overrides=ApplicationOverrides(),
            evidence_repository=evidence_repository,
            source_repository=source_repository,
            llm_client=provider,
        )
        extraction_summary = extraction.extract_for_source_ids(
            context,
            tuple(source.id for source in sources),
            allow_empty=True,
        )
        fresh_evidence_repository = PostgreSQLEvidenceRepository(
            DatabaseSessionFactory(self.engine),
        )
        evidence = fresh_evidence_repository.list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )
        relevant = [
            item for item in evidence if "in" in item.information_need_refs
        ]
        source_ids = sorted({item.source_id for item in relevant})
        self.assertGreaterEqual(
            len(source_ids),
            2,
            "production extraction must persist evidence from two source IDs; "
            f"sources={[(source.id, sum(item.source_id == source.id for item in evidence), sum(source.id == item.source_id and 'in' in item.information_need_refs for item in evidence)) for source in sources]}; "
            f"summary={extraction_summary.to_dict() if hasattr(extraction_summary, 'to_dict') else extraction_summary!r}",
        )
        origin_by_source = {
            source_ids[0]: origin_for_source(source_ids[0], 1),
            source_ids[1]: origin_for_source(source_ids[1], 2),
        }
        with self.session_factory.session() as session:
            for item in relevant:
                origin_id = origin_by_source.get(item.source_id)
                if origin_id is None:
                    continue
                metadata = dict(item.metadata)
                metadata["data_lineage"] = {
                    "status": "established",
                    "origin_id": origin_id,
                }
                session.execute(
                    update(EvidenceModel)
                    .where(EvidenceModel.id == item.id)
                    .values(metadata_json=metadata)
                )

        evidence = fresh_evidence_repository.list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )
        relevant = [
            item for item in evidence if "in" in item.information_need_refs
        ]
        self.assertGreaterEqual(
            len({item.source_id for item in relevant}),
            2,
        )

        design = context.workflow_template.research_design_snapshot
        acquired = next(item for item in design.information_needs if item.id == "in")
        coverage = replace(acquired.evidence_coverage, minimum_independent_sources=2)
        adjusted = replace(
            design,
            information_needs=(replace(acquired, evidence_coverage=coverage),
                               *[item for item in design.information_needs if item.id != "in"]),
        )
        context.workflow_template = replace(
            context.workflow_template,
            research_design_snapshot=adjusted,
        )
        readiness = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            evidence_repository=fresh_evidence_repository,
            source_repository=source_repository,
        ).assess_and_apply(context)
        assessment = acquired_assessment(readiness)
        return context, assessment, readiness

    def test_same_data_origin_does_not_satisfy_independent_source_quota(self):
        context, assessment, readiness = self._readiness_with_source_origins(
            lambda source_id, index: "ua-population-dataset",
        )
        self.assertIn("insufficient_source_diversity", assessment.reason)
        outcome, _ = derive_authoritative_outcome(
            required_information_need_ids=("in",),
            readiness_payload=context.read_shared("research_readiness"),
            findings=(), evidence=(), project_id=self.project.id,
            workflow_run_id=context.workflow_run.id,
            research_design_id=context.workflow_template.research_design_snapshot.id,
        )
        self.assertNotEqual(outcome, "COMPLETED")
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(self.project.id),
            [],
        )

    def test_distinct_data_origins_can_satisfy_independent_source_quota(self):
        context, assessment, _ = self._readiness_with_source_origins(
            lambda source_id, index: f"ua-origin-{index}",
        )
        self.assertGreaterEqual(assessment.independent_source_count, 2)
        self.assertNotIn("insufficient_source_diversity", assessment.reason)

    def _assert_rejected_evidence_does_not_reach_report(self, mutation):
        context, _, accepted_ids, _ = self._canonical_analysis()
        evidence_repository = PostgreSQLEvidenceRepository(self.session_factory)
        target_id = accepted_ids[0]
        current = evidence_repository.get_by_id(target_id)
        self.assertIsNotNone(current)
        assert current is not None
        metadata, source_locator = mutation(current)
        with self.session_factory.session() as session:
            session.execute(
                update(EvidenceModel)
                .where(EvidenceModel.id == target_id)
                .values(metadata_json=metadata, source_locator=source_locator)
            )
        target = evidence_repository.get_by_id(target_id)
        self.assertIsNotNone(target)
        assert target is not None
        design = context.workflow_template.research_design_snapshot
        brief = context.workflow_template.research_brief_snapshot
        readiness = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            evidence_repository=evidence_repository,
            source_repository=self.repo,
        ).assess_and_apply(context)
        try:
            analysis = AnalysisService(
                analysis_engine=CanonicalAnalysisEngine(),
                evidence_repository=evidence_repository,
                finding_repository=PostgreSQLFindingRepository(self.session_factory),
                insight_repository=PostgreSQLInsightRepository(self.session_factory),
                max_evidence_per_batch=100,
                max_chars_per_batch=1_000_000,
                source_repository=self.repo,
            ).analyze_for_context(context)
        except AnalysisError:
            analysis = None
        if analysis is not None:
            self.assertFalse(analysis.finding_ids)
            self.assertFalse(analysis.insight_ids)
        temporal = qualify_evidence_with_temporal_decisions(
            design=design,
            evidence=(target,),
            brief=brief,
            source_repository=self.repo,
        )
        numeric = project_numeric_evidence_for_design(
            design=design,
            evidence=temporal.evidence,
            source_repository=self.repo,
            temporal_decisions=temporal.decisions,
            allowed_workflow_run_ids=(context.workflow_run.id,),
        ).qualifications["in"]
        self.assertNotIn(target_id, {item.id for item in numeric.accepted_evidence})
        self.assertFalse(readiness.ready_for_analysis)
        with self.assertRaises(ReportError):
            self._report_service().write_for_context(context)
        self.assertEqual(
            PostgreSQLReportRepository(self.session_factory).list_for_project(
                self.project.id,
            ),
            [],
        )
        with self.session_factory.session() as session:
            self.assertEqual(
                session.query(ReportClaimModel).filter_by(project_id=self.project.id).count(),
                0,
            )

    def test_wrong_numeric_metric_is_rejected_before_report_authority(self):
        def mutate(item):
            metadata = dict(item.metadata)
            metadata["metric"] = "Wrong metric"
            return metadata, dict(item.source_locator)

        self._assert_rejected_evidence_does_not_reach_report(mutate)

    def test_wrong_numeric_unit_is_rejected_before_report_authority(self):
        def mutate(item):
            metadata = dict(item.metadata)
            metadata["unit"] = "percent"
            return metadata, dict(item.source_locator)

        self._assert_rejected_evidence_does_not_reach_report(mutate)

    def test_wrong_numeric_geography_is_rejected_before_report_authority(self):
        def mutate(item):
            metadata = dict(item.metadata)
            metadata["geography"] = "Poland"
            return metadata, dict(item.source_locator)

        self._assert_rejected_evidence_does_not_reach_report(mutate)

    def test_out_of_range_observation_period_is_rejected_before_report_authority(self):
        def mutate(item):
            metadata = dict(item.metadata)
            metadata["observation_period"] = "2022"
            return metadata, dict(item.source_locator)

        self._assert_rejected_evidence_does_not_reach_report(mutate)

    def test_invalid_citation_checksum_and_locator_are_rejected_before_report_authority(self):
        def mutate(item):
            metadata = dict(item.metadata)
            locator = dict(item.source_locator)
            structured = dict(locator.get("structured") or {})
            structured["raw_workbook_checksum"] = "0" * 64
            locator["structured"] = structured
            metadata["workbook_provenance"] = structured
            return metadata, locator

        self._assert_rejected_evidence_does_not_reach_report(mutate)
        self.assertNotEqual(
            derive_authoritative_outcome(
                required_information_need_ids=("in-1",),
                readiness_payload=None, findings=(), evidence=(),
                project_id=self.project.id, workflow_run_id="missing",
                research_design_id="missing",
            )[0],
            "COMPLETED",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()


# The imported IR-5 base supplies fixtures only. Do not let unittest discover
# it a second time from this module alongside the focused IR-6 class.
del _IR5CanonicalReportCompletionPostgreSQLTests
