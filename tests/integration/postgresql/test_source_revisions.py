from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import os
from threading import Barrier
from uuid import uuid4
import unittest

from sqlalchemy import text
from alembic import command
from alembic.config import Config
from application.evidence.citation_integrity import citation_is_valid
from application.evidence.grounding import verify_grounding
from application.sources.provenance_merge import apply_first_acquisition
from domain.evidence.evidence import Evidence
from domain.factories.project_factory import ProjectFactory
from domain.sources.acquisition_path import SourceAcquisitionPath
from domain.sources.source import Source
from domain.sources.retrieval_status import RetrievalStatus
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL required")
class SourceRevisionTests(PostgreSQLIntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.project = ProjectFactory().create("Synthetic revisions")
        PostgreSQLProjectRepository(self.session_factory).create(self.project)
        self.repo = PostgreSQLSourceRepository(self.session_factory)
        self.run = str(uuid4())
        with self.session_factory.session() as session:
            session.add(WorkflowRunModel(id=self.run, project_id=self.project.id, workflow_template_id="fixture", status="completed", dependency_graph={}, task_results={}, version=0))

    def source(self, body="Population 2020 = 950", url="https://example.org/data.xlsx", extraction="xlsx-v1", failed=False):
        return Source(id=str(uuid4()), project_id=self.project.id, url=url, canonical_url=url, title="Fixture", retrieved_at=datetime.now(timezone.utc).isoformat(), content_text=body, content_checksum=sha256(body.encode()).hexdigest(), raw_content_checksum=sha256(body.encode()).hexdigest(), raw_checksum_kind="sha256-bytes", extraction_revision=extraction, retrieval_status=RetrievalStatus.FAILED if failed else RetrievalStatus.ACQUIRED, workflow_run_refs=(self.run,))

    def path(self, source, landing):
        return SourceAcquisitionPath(self.project.id, self.run, source.id, landing, source.url, (landing, source.url))

    def test_paths_and_idempotency(self):
        a = self.repo.create_immutable_revision(self.source())
        b = self.repo.create_immutable_revision(self.source(url="https://example.org/b.xlsx"))
        for source, landing in ((a,"https://example.org/landing"), (b,"https://example.org/landing"), (a,"https://example.org/other")):
            self.repo.persist_acquisition_path(self.path(source, landing))
            self.repo.persist_acquisition_path(self.path(source, landing))
        self.assertEqual(len(self.repo.list_acquisition_paths(self.project.id, self.run)), 3)
        self.assertEqual(self.repo.create_immutable_revision(self.source()).id, a.id)
        self.assertNotEqual(a.terminal_resource_key, b.terminal_resource_key)

    def test_application_first_success_and_reuse_paths(self):
        from application.sources.source_acquisition_service import SourceAcquisitionService, _PendingCandidate
        from domain.sources.search_query import SearchQuery
        from domain.sources.source_candidate import SourceCandidate
        from infrastructure.search.deterministic_search_adapter import DeterministicSearchProvider
        failed = self.repo.create_immutable_revision(self.source(body="",failed=True))
        before = self.repo.get_by_id(failed.id).to_dict()
        response = self.source()
        class Retriever:
            calls = 0
            def retrieve(inner, candidate):
                inner.calls += 1
                return deepcopy(response)
        retriever = Retriever()
        service = SourceAcquisitionService(search_provider=DeterministicSearchProvider(),source_retriever=retriever,source_repository=self.repo)
        query = SearchQuery("q","rq","in","Population")
        item = _PendingCandidate(SourceCandidate("fixture",response.url,"Population","","q",1),query,response.url)
        arguments = dict(project_id=self.project.id,workflow_run_id=self.run,research_design_id="design",items=[item])
        recovered, _, _ = service._resolve_source_for_group(**arguments)
        reused, _, _ = service._resolve_source_for_group(**arguments)
        self.assertEqual(recovered.id,reused.id)
        self.assertNotEqual(recovered.id,failed.id)
        self.assertEqual(retriever.calls,1)
        self.assertEqual(self.repo.get_by_id(failed.id).to_dict(),before)
        paths = self.repo.list_acquisition_paths(self.project.id,self.run)
        self.assertEqual(len(paths),1)
        self.assertEqual(paths[0].source_id,recovered.id)

    def test_content_and_extraction_revisions(self):
        a = self.repo.create_immutable_revision(self.source())
        b = self.repo.create_immutable_revision(self.source(body="Population 2020 = 960"))
        c = self.repo.create_immutable_revision(self.source(extraction="xlsx-v2"))
        self.assertEqual((a.content_revision,b.content_revision,c.content_revision), (1,2,1))
        self.assertEqual(a.terminal_resource_key,b.terminal_resource_key)
        with self.assertRaises(ValueError):
            a.content_text = "changed"
            self.repo.save(a, expected_version=a.version)

    def test_concurrent_recovery(self):
        failed = self.repo.create_immutable_revision(self.source(body="", failed=True))
        barrier = Barrier(2)
        def recover(_):
            repo = PostgreSQLSourceRepository(DatabaseSessionFactory(self.engine))
            candidate = apply_first_acquisition(deepcopy(failed), self.source())
            barrier.wait(timeout=10)
            return repo.create_immutable_revision(candidate).id
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(recover, range(2)))
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(self.repo.get_by_id(failed.id).retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(len(self.repo.list_for_project(self.project.id)),2)

    def test_failed_retry_and_optimistic_lock(self):
        a = self.repo.create_immutable_revision(self.source(body="",failed=True))
        self.assertEqual(self.repo.create_immutable_revision(self.source(body="",failed=True)).id,a.id)
        stale = deepcopy(a)
        a.query_refs = ("query",)
        self.repo.save(a,expected_version=1)
        from application.persistence.exceptions import ConcurrentModificationError
        with self.assertRaises(ConcurrentModificationError):
            self.repo.save(stale,expected_version=1)

    def test_foreign_path_and_immutable_metadata_rejected(self):
        source = self.repo.create_immutable_revision(self.source())
        with self.assertRaises(ValueError):
            self.repo.persist_acquisition_path(SourceAcquisitionPath(str(uuid4()),self.run,source.id,source.url,source.url,(source.url,)))
        self.assertEqual(self.repo.list_acquisition_paths(self.project.id,self.run),[])
        source.metadata["structured_rows"] = [{"invented":True}]
        with self.assertRaises(ValueError):
            self.repo.save(source)

    def test_concurrent_changed_content_and_extraction(self):
        first = self.repo.create_immutable_revision(self.source())
        barrier = Barrier(2)
        def create(index):
            repo = PostgreSQLSourceRepository(DatabaseSessionFactory(self.engine))
            candidate = self.source(body="changed",extraction="v"+str(index))
            barrier.wait(timeout=10)
            return repo.create_immutable_revision(candidate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(create,range(2)))
        self.assertEqual({r.content_revision for r in rows},{2})
        self.assertEqual(len({r.id for r in rows}),2)
        self.assertEqual(self.repo.get_by_id(first.id).content_text,first.content_text)

    def test_historical_citation_and_fresh_reload(self):
        source = self.repo.create_immutable_revision(self.source())
        evidence = Evidence(id=str(uuid4()), project_id=self.project.id, source_id=source.id, source_content_checksum=source.content_checksum, workflow_run_id=self.run, research_design_id=str(uuid4()), statement=source.content_text, source_excerpt=source.content_text, source_locator=verify_grounding(source_text=source.content_text,excerpt=source.content_text).to_dict(), deduplication_key="fixture", created_at=datetime.now(timezone.utc).isoformat())
        erepo = PostgreSQLEvidenceRepository(self.session_factory)
        erepo.create(evidence)
        self.repo.create_immutable_revision(self.source(body="Population 2020 = 960"))
        fresh = DatabaseSessionFactory(self.engine)
        loaded = PostgreSQLEvidenceRepository(fresh).get_by_id(evidence.id)
        self.assertTrue(citation_is_valid(loaded,PostgreSQLSourceRepository(fresh).get_by_id(source.id)))
        self.assertEqual(loaded.source_id, source.id)

    def test_legacy_backfill(self):
        # Empty disposable schema permits a reversible test migration to 029.
        os.environ["DATABASE_URL"] = os.environ["DATABASE_URL_TEST"]
        command.downgrade(Config("alembic.ini"), "029_presentation_draft_lifecycle")
        sid = str(uuid4())
        checksum = sha256(b"legacy").hexdigest()
        with self.engine.begin() as connection:
            connection.execute(text("""INSERT INTO sources (id,project_id,url,canonical_url,title,retrieved_at,source_type,retrieval_status,content_text,content_checksum) VALUES (:id,:p,'https://example.org/legacy','https://example.org/legacy','Legacy',now(),'web','acquired','legacy',:checksum)"""), {"id":sid,"p":self.project.id,"checksum":checksum})
        evidence = Evidence(id=str(uuid4()), project_id=self.project.id, source_id=sid, source_content_checksum=checksum, workflow_run_id=self.run, research_design_id=str(uuid4()), statement="legacy", source_excerpt="legacy", source_locator=verify_grounding(source_text="legacy", excerpt="legacy").to_dict(), deduplication_key="legacy", created_at=datetime.now(timezone.utc).isoformat())
        PostgreSQLEvidenceRepository(self.session_factory).create(evidence)
        command.upgrade(Config("alembic.ini"), "head")
        row = self.repo.get_by_id(sid)
        self.assertEqual((row.id,row.content_revision,row.extraction_revision,row.raw_checksum_kind,row.content_checksum), (sid,1,"legacy-v1","legacy-surrogate",checksum))
        self.assertNotEqual(row.raw_content_checksum,checksum)
        loaded = PostgreSQLEvidenceRepository(DatabaseSessionFactory(self.engine)).get_by_id(evidence.id)
        self.assertEqual(loaded.to_dict(), evidence.to_dict())
        self.assertTrue(citation_is_valid(loaded,row))
