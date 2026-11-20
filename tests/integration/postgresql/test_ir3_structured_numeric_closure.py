from __future__ import annotations

from unittest.mock import Mock

from application.analysis.numeric_integrity import project_numeric_evidence_for_design
from application.config import ApplicationOverrides
from application.evidence.citation_integrity import citation_is_valid
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.evidence.temporal_scope import qualify_evidence_with_temporal_decisions
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.research_brief import ResearchBrief
from domain.workflow_template import WorkflowTemplate
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
    PostgreSQLEvidenceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
    PostgreSQLSourceRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from runtime.workflow_context import WorkflowContext
from tests.application.evidence.test_ir3_structured_numeric_closure import (
    YEARS,
    ir3_design,
    ir3_zip,
)
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.integration.postgresql import test_capability_acquisition as capability_fixture


class IR3StructuredNumericClosurePostgreSQLTests(capability_fixture.CapabilityAcquisitionTests):
    def test_http_zip_xlsx_persists_reloads_and_qualifies_seven_year_series(self):
        self.body = ir3_zip()
        run_id = self.run_id()
        design = ir3_design()
        brief = ResearchBrief(
            title="Resident population",
            business_question="Resident population",
            timeframe="2015–2021",
        )
        template = WorkflowTemplate(
            id="fixture",
            name="IR-3 structured numeric closure",
            task_definitions=(),
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
        provider = Mock()
        provider.generate.side_effect = AssertionError("structured extraction must not call a provider")
        service = build_evidence_extraction_service(
            config=postgresql_application_config(evidence_extractor="llm"),
            overrides=ApplicationOverrides(),
            evidence_repository=evidence_repository,
            source_repository=self.repo,
            llm_client=provider,
        )

        summary = service.extract_for_source_ids(context, (source.id,), allow_empty=True)
        rows = tuple(sorted(
            evidence_repository.list_for_project(self.project.id, workflow_run_id=run_id),
            key=lambda item: item.metadata["observation_period"],
        ))
        temporal = qualify_evidence_with_temporal_decisions(
            design=design, evidence=rows, brief=brief, source_repository=self.repo,
        )
        projection = project_numeric_evidence_for_design(
            design=design,
            evidence=temporal.evidence,
            source_repository=self.repo,
            temporal_decisions=temporal.decisions,
            allowed_workflow_run_ids=(run_id,),
        )
        qualification = projection.qualifications["in"]

        self.assertEqual(summary.evidence_extracted, 7)
        self.assertEqual(tuple(item.metadata["observation_period"] for item in rows), YEARS)
        self.assertEqual(qualification.qualified_periods, YEARS)
        self.assertEqual(qualification.missing_periods, ())
        self.assertEqual(
            {item.id for item in qualification.accepted_evidence}, {item.id for item in rows},
        )
        self.assertIn("/landing", self.hits)
        self.assertIn("/download/123", self.hits)
        provider.generate.assert_not_called()

        fresh = DatabaseSessionFactory(self.engine)
        fresh_sources = PostgreSQLSourceRepository(fresh)
        fresh_evidence = PostgreSQLEvidenceRepository(fresh)
        loaded_source = fresh_sources.get_by_id(source.id)
        loaded_rows = tuple(fresh_evidence.get_by_id(item.id) for item in rows)
        self.assertTrue(all(item is not None for item in loaded_rows))
        self.assertTrue(all(citation_is_valid(item, loaded_source) for item in loaded_rows))
        for expected_row, item in enumerate(loaded_rows, start=2):
            structured = item.source_locator["structured"]
            self.assertEqual(structured["sheet"], "Resident population")
            self.assertEqual(structured["cell"], f"B{expected_row}")
            self.assertEqual(structured["period_cell"], f"A{expected_row}")
            self.assertEqual(structured["raw_workbook_checksum"], loaded_source.raw_content_checksum)
            self.assertEqual(structured["extraction_revision"], loaded_source.extraction_revision)
            self.assertEqual(structured["content_revision"], loaded_source.content_revision)

        reloaded_temporal = qualify_evidence_with_temporal_decisions(
            design=design,
            evidence=loaded_rows,
            brief=brief,
            source_repository=fresh_sources,
        )
        reloaded = project_numeric_evidence_for_design(
            design=design,
            evidence=reloaded_temporal.evidence,
            source_repository=fresh_sources,
            temporal_decisions=reloaded_temporal.decisions,
            allowed_workflow_run_ids=(run_id,),
        ).qualifications["in"]
        self.assertEqual(reloaded.qualified_periods, YEARS)
        self.assertEqual(reloaded.missing_periods, ())


if __name__ == "__main__":
    import unittest
    unittest.main()
