"""Content alias audit and one extraction survive isolated PostgreSQL storage."""
import unittest
from dataclasses import replace
from uuid import uuid4

from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.sources.content_identity import acquired_content_identity
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from infrastructure.evidence.deterministic_evidence_extractor import DeterministicEvidenceExtractor
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from runtime.workflow_context import WorkflowContext
from tests.application.evidence.test_prf08p_content_identity import source
from tests.application.evidence.test_evidence_extraction_service import _design, _template
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL required")
class ContentIdentityPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_aliases_keep_urls_and_single_grounded_evidence(self):
        project = ProjectFactory().create("PRF-08P synthetic")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        sources = PostgreSQLSourceRepository(self.session_factory)
        evidence = PostgreSQLEvidenceRepository(self.session_factory)
        ids = [str(uuid4()), str(uuid4())]
        for sid in ids:
            sources.create(replace(source(sid), project_id=project.id))
        template = _template(_design())
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
        run.id = "run-1"
        context = WorkflowContext(project=project, workflow_template=template, workflow_run=run)
        context.current_task = run.tasks[0]
        result = EvidenceExtractionService(evidence_extractor=DeterministicEvidenceExtractor(),
            source_repository=sources, evidence_repository=evidence).extract_for_context(context)
        self.assertEqual(result.evidence_extracted, 1)
        saved = evidence.list_for_project(project.id, workflow_run_id="run-1")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].metadata["acquired_content_identity"], acquired_content_identity(source()))
        self.assertEqual({x["source_id"] for x in saved[0].metadata["content_aliases"]}, set(ids))
        persisted = sources.list_for_project(project.id, workflow_run_id="run-1")
        self.assertEqual(len({s.url for s in persisted}), 2)
        self.assertEqual(len({acquired_content_identity(s) for s in persisted}), 1)
