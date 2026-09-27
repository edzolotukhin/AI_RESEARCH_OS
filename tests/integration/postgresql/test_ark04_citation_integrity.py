"""Citation qualification reads persisted spans without repairing stored Evidence."""
import unittest
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

from application.evidence.grounding import verify_grounding
from application.evidence.temporal_scope import qualifying_evidence
from domain.evidence.evidence import Evidence
from domain.factories.project_factory import ProjectFactory
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL integration disabled")
class CitationIntegrityPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_invalid_persisted_span_is_nonqualifying_and_unchanged(self):
        project = ProjectFactory().create("ARK-04 synthetic citations")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        sources = PostgreSQLSourceRepository(self.session_factory)
        evidence = PostgreSQLEvidenceRepository(self.session_factory)
        text = "Prefix. Українська цитата. End."
        excerpt = "Українська цитата."
        checksum = sha256(text.encode()).hexdigest()
        source = Source(str(uuid4()), project.id, "https://example.test/citation",
                        "https://example.test/citation", "Synthetic", "2026-01-01",
                        content_text=text, content_checksum=checksum)
        sources.create(source)
        ids = []
        for valid in (True, False):
            locator = verify_grounding(source_text=text, excerpt=excerpt).to_dict()
            if not valid:
                locator["normalized_start"] = 0
            item = Evidence(id=str(uuid4()), project_id=project.id,
                source_id=source.id, source_content_checksum=checksum,
                workflow_run_id="offline-ark04", research_design_id="offline-ark04",
                statement=excerpt, source_excerpt=excerpt, source_locator=locator,
                created_at="2026-01-01T00:00:00+00:00", deduplication_key=str(valid),
                information_need_refs=("IN1",), research_question_refs=("RQ1",))
            evidence.create(item)
            ids.append(item.id)
        loaded = evidence.list_for_project(project.id)
        before = {item.id: asdict(item) for item in loaded}
        qualified = qualifying_evidence(design=ResearchDesign("offline-ark04", research_questions=()),
            evidence=loaded, brief=None, source_repository=sources)
        self.assertEqual([item.id for item in qualified], ids[:1])
        self.assertEqual({item.id: asdict(item) for item in evidence.list_for_project(project.id)}, before)
