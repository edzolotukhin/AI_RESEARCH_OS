"""Canonical lineage read-time semantics survive disposable JSONB persistence."""
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from application.research_quality.deterministic_sufficiency_evaluator import _independent_lineages
from domain.evidence.evidence import Evidence
from domain.factories.project_factory import ProjectFactory
from domain.sources.source import Source
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL integration disabled")
class LineageIdentityPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_aliases_normalize_without_rewriting_persisted_origin(self):
        project = ProjectFactory().create("PRF-08K synthetic lineage")
        PostgreSQLProjectRepository(self.session_factory).create(project)
        sources = PostgreSQLSourceRepository(self.session_factory)
        evidence = PostgreSQLEvidenceRepository(self.session_factory)
        origins = ("Statistics Office, sourced from Example Registry", "Example Registry", "Other Registry")
        now = datetime.now(timezone.utc).isoformat()
        for i, origin in enumerate(origins):
            source_id = str(uuid4())
            sources.create(Source(id=source_id, project_id=project.id,
                url=f"https://example.test/{i}", canonical_url=f"https://example.test/{i}",
                title="Synthetic", retrieved_at=now, content_text=f"Source: {origin}", content_checksum=str(i)))
            evidence.create(Evidence(id=str(uuid4()), project_id=project.id,
                source_id=source_id, source_content_checksum=str(i), workflow_run_id="offline-k",
                research_design_id="offline-k-design", statement=f"Synthetic {i}",
                source_excerpt=f"Source: {origin}", created_at=now,
                information_need_refs=("IN1",), research_question_refs=("RQ1",),
                deduplication_key=f"k-{i}", metadata={"data_lineage":{
                    "status":"established", "origin_id":origin, "basis_excerpt":f"Source: {origin}"}}))
        loaded = evidence.list_for_project(project.id, workflow_run_id="offline-k")
        self.assertEqual(len(loaded), 3)
        self.assertEqual(len(_independent_lineages(loaded)[0]), 2)
        self.assertEqual({e.metadata["data_lineage"]["origin_id"] for e in loaded}, set(origins))
