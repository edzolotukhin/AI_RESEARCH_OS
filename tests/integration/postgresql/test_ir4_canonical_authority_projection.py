from __future__ import annotations

from unittest.mock import Mock

from application.analysis.analysis_service import AnalysisService
from application.config import ApplicationOverrides
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.research_quality.deterministic_research_sufficiency_evaluator import (
    DeterministicResearchSufficiencyEvaluator,
)
from application.research_quality.research_readiness_service import ResearchReadinessService
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.research_brief import ResearchBrief
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
    PostgreSQLEvidenceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
    PostgreSQLFindingRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
    PostgreSQLInsightRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
    PostgreSQLSourceRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from runtime.workflow_context import WorkflowContext
from tests.application.analysis.test_ir4_canonical_authority_projection import (
    CanonicalAnalysisEngine,
    acquired_assessment,
    ir4_design,
)
from tests.application.evidence.test_ir3_structured_numeric_closure import YEARS, ir3_zip
from tests.integration.postgresql import test_capability_acquisition as capability_fixture
from tests.integration.postgresql.helpers import postgresql_application_config


class IR4CanonicalAuthorityProjectionPostgreSQLTests(
    capability_fixture.CapabilityAcquisitionTests,
):
    def test_fresh_session_preserves_canonical_evidence_finding_and_insight_lineage(self):
        self.body = ir3_zip()
        run_id = self.run_id()
        design = ir4_design()
        brief = ResearchBrief(
            title="Resident population",
            business_question="Resident population of Ukraine",
            timeframe="2015–2021",
        )
        template = WorkflowTemplate(
            "fixture",
            "IR-4 PostgreSQL authority projection",
            (),
            research_design_snapshot=design,
            research_brief_snapshot=brief,
        )
        workflow = WorkflowRunFactory(task_factory=TaskFactory()).create(
            template=template, run_id=run_id, project_id=self.project.id,
        )
        context = WorkflowContext(
            project=self.project,
            workflow_template=template,
            workflow_run=workflow,
        )
        source = self.acquire(run_id)
        evidence_repository = PostgreSQLEvidenceRepository(self.session_factory)
        finding_repository = PostgreSQLFindingRepository(self.session_factory)
        insight_repository = PostgreSQLInsightRepository(self.session_factory)
        provider = Mock()
        provider.generate.side_effect = AssertionError("structured extraction must not call a provider")
        extraction = build_evidence_extraction_service(
            config=postgresql_application_config(evidence_extractor="llm"),
            overrides=ApplicationOverrides(),
            evidence_repository=evidence_repository,
            source_repository=self.repo,
            llm_client=provider,
        )
        extraction.extract_for_source_ids(context, (source.id,), allow_empty=True)
        provider.generate.assert_not_called()
        readiness_service = ResearchReadinessService(
            evaluator=DeterministicResearchSufficiencyEvaluator(),
            evidence_repository=evidence_repository,
            source_repository=self.repo,
        )
        readiness = readiness_service.assess_and_apply(context)
        engine = CanonicalAnalysisEngine()
        analysis = AnalysisService(
            analysis_engine=engine,
            evidence_repository=evidence_repository,
            finding_repository=finding_repository,
            insight_repository=insight_repository,
            max_evidence_per_batch=100,
            max_chars_per_batch=1_000_000,
            source_repository=self.repo,
        )
        summary = analysis.analyze_for_context(context)

        accepted_ids = tuple(
            acquired_assessment(readiness).prerequisite_diagnostics["qualifying_evidence_ids"]
        )
        self.assertTrue(readiness.ready_for_analysis)
        self.assertEqual(len(accepted_ids), 7)
        self.assertTrue(summary.finding_ids)
        self.assertTrue(summary.insight_ids)

        fresh = DatabaseSessionFactory(self.engine)
        fresh_sources = PostgreSQLSourceRepository(fresh)
        fresh_evidence = PostgreSQLEvidenceRepository(fresh)
        fresh_findings = PostgreSQLFindingRepository(fresh)
        fresh_insights = PostgreSQLInsightRepository(fresh)
        loaded_evidence = tuple(fresh_evidence.get_by_id(item_id) for item_id in accepted_ids)
        loaded_findings = tuple(fresh_findings.get_by_id(item_id) for item_id in summary.finding_ids)
        loaded_insights = tuple(fresh_insights.get_by_id(item_id) for item_id in summary.insight_ids)
        self.assertTrue(all(item is not None for item in loaded_evidence))
        self.assertTrue(all(item is not None for item in loaded_findings))
        self.assertTrue(all(item is not None for item in loaded_insights))
        self.assertEqual(
            {ref for item in loaded_findings for ref in item.evidence_refs},
            set(accepted_ids),
        )
        self.assertEqual(
            {ref for item in loaded_insights for ref in item.finding_refs},
            {item.id for item in loaded_findings},
        )
        derived = next(item for item in loaded_findings if item.information_need_refs == ("change",))
        self.assertEqual(
            tuple(derived.metadata["derivation"]["input_evidence_ids"]),
            accepted_ids,
        )
        self.assertEqual(
            tuple(sorted(item.metadata["observation_period"] for item in loaded_evidence)),
            YEARS,
        )
        loaded_source = fresh_sources.get_by_id(source.id)
        self.assertTrue(all(
            item.source_content_checksum == loaded_source.content_checksum
            for item in loaded_evidence
        ))


if __name__ == "__main__":
    import unittest
    unittest.main()
