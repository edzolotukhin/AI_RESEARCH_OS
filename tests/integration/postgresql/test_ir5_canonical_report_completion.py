"""IR-5 PostgreSQL acceptance for canonical analysis-to-report authority."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

from application.analysis.analysis_service import AnalysisService
from application.config import ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.report.claim_first_report_service import ClaimFirstReportService
from application.report.exceptions import ReportError
from application.research_quality.deterministic_research_sufficiency_evaluator import (
    DeterministicResearchSufficiencyEvaluator,
)
from application.research_quality.research_readiness_service import ResearchReadinessService
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.research_brief import ResearchBrief
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
    PostgreSQLArtifactRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
    PostgreSQLEvidenceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
    PostgreSQLFindingRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
    PostgreSQLInsightRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_report_claim_repository import (
    PostgreSQLReportClaimRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import (
    PostgreSQLReportRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
    PostgreSQLSourceRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from runtime.workflow_context import WorkflowContext
from tests.application.analysis.test_ir4_canonical_authority_projection import (
    CanonicalAnalysisEngine,
    acquired_assessment,
    ir4_design,
)
from tests.application.evidence.test_ir3_structured_numeric_closure import YEARS, ir3_zip
from tests.integration.postgresql import test_capability_acquisition as capability_fixture
from tests.integration.postgresql.helpers import postgresql_application_config


class IR5CanonicalReportCompletionPostgreSQLTests(
    capability_fixture.CapabilityAcquisitionTests,
):
    def _canonical_analysis(self):
        self.body = ir3_zip()
        run_id = self.run_id()
        design = ir4_design()
        brief = ResearchBrief(
            title="Resident population",
            business_question="Resident population of Ukraine",
            timeframe="2015–2021",
        )
        template = WorkflowTemplate(
            "ir5-template", "IR-5 canonical report", (),
            research_design_snapshot=design,
            research_brief_snapshot=brief,
        )
        workflow = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template, run_id=run_id, project_id=self.project.id,
        )
        context = WorkflowContext(
            project=self.project, workflow_template=template, workflow_run=workflow,
        )
        source = self.acquire(run_id)
        evidence_repository = PostgreSQLEvidenceRepository(self.session_factory)
        finding_repository = PostgreSQLFindingRepository(self.session_factory)
        insight_repository = PostgreSQLInsightRepository(self.session_factory)
        provider = Mock()
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
        self.assertTrue(analysis.finding_ids and analysis.insight_ids)
        return context, source, accepted_ids, analysis

    def test_canonical_analysis_persists_report_claims_and_reload_traceability(self):
        context, source, accepted_ids, analysis = self._canonical_analysis()
        reports = PostgreSQLReportRepository(self.session_factory)
        claims = PostgreSQLReportClaimRepository(self.session_factory)
        service = ClaimFirstReportService(
            report_claim_repository=claims,
            report_engine=DeterministicReportEngine(),
            finding_repository=PostgreSQLFindingRepository(self.session_factory),
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=self.repo,
            report_repository=reports,
            artifact_repository=PostgreSQLArtifactRepository(self.session_factory),
            max_findings_per_batch=10,
            max_chars_per_batch=10_000,
        )
        summary = service.write_for_context(context)
        report = reports.get_by_id(summary.report_id)
        persisted_claims = claims.list_for_report(report.id, report.revision_number)
        self.assertTrue(persisted_claims)
        self.assertEqual(
            set(report.evidence_refs),
            {ref for claim in persisted_claims for ref in claim.evidence_ids},
        )
        self.assertTrue(set(report.finding_refs) <= set(analysis.finding_ids))
        self.assertTrue(set(report.insight_refs) <= set(analysis.insight_ids))

        fresh = DatabaseSessionFactory(self.engine)
        fresh_report = PostgreSQLReportRepository(fresh).get_by_id(report.id)
        fresh_claims = PostgreSQLReportClaimRepository(fresh).list_for_report(
            report.id, report.revision_number,
        )
        fresh_source = PostgreSQLSourceRepository(fresh).get_by_id(source.id)
        self.assertEqual(fresh_report.evidence_refs, report.evidence_refs)
        self.assertEqual(
            {ref for claim in fresh_claims for ref in claim.evidence_ids},
            set(accepted_ids),
        )
        self.assertTrue(all(
            claim.evidence_content_digests and claim.source_ids
            for claim in fresh_claims
        ))
        self.assertEqual(
            {item.source_content_checksum for item in
             PostgreSQLEvidenceRepository(fresh).list_for_project(
                 self.project.id, workflow_run_id=context.workflow_run.id,
             ) if item.id in accepted_ids},
            {fresh_source.content_checksum},
        )

    def test_unvalidated_finding_is_rejected_before_report_persistence(self):
        context, _, _, _ = self._canonical_analysis()
        findings = PostgreSQLFindingRepository(self.session_factory)
        existing = findings.list_for_project(
            self.project.id, workflow_run_id=context.workflow_run.id,
        )[0]
        findings.create(
            replace(
                existing,
                id="unvalidated-ir5",
                deduplication_key="unvalidated-ir5-dedup",
                metadata={},
            )
        )
        reports = PostgreSQLReportRepository(self.session_factory)
        claims = PostgreSQLReportClaimRepository(self.session_factory)
        service = ClaimFirstReportService(
            report_claim_repository=claims,
            report_engine=DeterministicReportEngine(),
            finding_repository=findings,
            insight_repository=PostgreSQLInsightRepository(self.session_factory),
            evidence_repository=PostgreSQLEvidenceRepository(self.session_factory),
            source_repository=self.repo,
            report_repository=reports,
            artifact_repository=PostgreSQLArtifactRepository(self.session_factory),
            max_findings_per_batch=10,
            max_chars_per_batch=10_000,
        )
        with self.assertRaises(ReportError):
            service.write_for_context(context)
        self.assertEqual(reports.list_for_project(self.project.id), [])
        self.assertEqual(claims.list_for_report("missing", 1), [])


if __name__ == "__main__":
    import unittest

    unittest.main()
