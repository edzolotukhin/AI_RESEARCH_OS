"""Real loopback HTTP + PostgreSQL, with only network-origin guard fixture-scoped."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread, Barrier
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from application.evidence.citation_integrity import citation_is_valid
from application.evidence.grounding import verify_grounding
from application.sources.source_acquisition_service import SourceAcquisitionService, _PendingCandidate
from domain.evidence.evidence import Evidence
from domain.factories.project_factory import ProjectFactory
from domain.sources.source import Source
from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever
from infrastructure.retrieval.network_safety import UnsafeUrlError
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase
from tests.infrastructure.retrieval.test_capability_navigation import workbook


class CapabilityAcquisitionTests(PostgreSQLIntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.project=ProjectFactory().create("Synthetic acquisition")
        PostgreSQLProjectRepository(self.session_factory).create(self.project)
        self.repo=PostgreSQLSourceRepository(self.session_factory)
        self.body=workbook()
        self.hits=[]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                owner.hits.append(inner.path)
                if inner.path.startswith("/download"):
                    body=owner.body
                    mime="application/octet-stream"
                else:
                    body=b'<p>XLSX</p><a href="/download/123">Download</a>'
                    mime="text/html"
                inner.send_response(200)
                inner.send_header("Content-Type",mime)
                inner.send_header("Content-Length",str(len(body)))
                inner.end_headers()
                inner.wfile.write(body)
            def log_message(self,*args):
                pass
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.origin="http://127.0.0.1:"+str(self.server.server_port)
        self.thread=Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        def guard(url,**kwargs):
            parsed=urlsplit(url)
            if parsed.hostname!="127.0.0.1" or parsed.port!=self.server.server_port:
                raise UnsafeUrlError("Fixture origin only")
        self.guard=patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url",side_effect=guard)
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def run_id(self):
        run=str(uuid4())
        with self.session_factory.session() as session:
            session.add(WorkflowRunModel(id=run,project_id=self.project.id,workflow_template_id="fixture",status="completed",dependency_graph={},task_results={},version=0))
        return run

    def acquire(self,run,landing="/landing",**metadata):
        repo=PostgreSQLSourceRepository(DatabaseSessionFactory(self.engine))
        revision=metadata.pop("requested_extraction_revision","xlsx-structured-v2")
        service=SourceAcquisitionService(search_provider=None,source_retriever=HttpSourceRetriever(xlsx_extraction_revision=revision),source_repository=repo)
        query=SearchQuery("q","rq","in","Population 2020")
        candidate=SourceCandidate("fixture",self.origin+landing,"Population","","q",1,metadata={"required_resource_kind":"table",**metadata})
        return service._resolve_source_for_group(project_id=self.project.id,workflow_run_id=run,research_design_id="design",items=[_PendingCandidate(candidate,query,candidate.url)])[0]

    def test_legacy_upgrade_reuse_reextract_changed_bytes_and_citation(self):
        run=self.run_id()
        old=Source(str(uuid4()),self.project.id,self.origin+"/landing",self.origin+"/landing","Legacy",datetime.now(timezone.utc).isoformat(),content_text="legacy",content_checksum=sha256(b"legacy").hexdigest())
        self.repo.create(old)
        from domain.planning.research_design import ResearchDesign, ResearchQuestion, InformationNeed, EvidenceCoverageContract
        design=ResearchDesign("design",(ResearchQuestion("rq","Population"),),
            (InformationNeed("in","rq","Population",evidence_coverage=EvidenceCoverageContract(required_metric="population",required_periods=("2020",))),))
        selection=SourceAcquisitionService(search_provider=None,source_retriever=HttpSourceRetriever(),source_repository=self.repo)
        query=SearchQuery("q","rq","in","Population 2020")
        item=_PendingCandidate(SourceCandidate("fixture",old.url,"Population","Population 2020","q",1),query,old.url)
        groups,_,_,exhausted=selection._select_groups({old.url:[item]},design=design,project_id=self.project.id,exhausted_pairs=frozenset({(old.url,"in")}))
        self.assertEqual(len(groups),1)
        self.assertEqual(exhausted,0)
        self.assertEqual(groups[0].items[0].candidate.metadata["required_resource_kind"],"table")
        before=self.repo.get_by_id(old.id).to_dict()
        evidence=Evidence(str(uuid4()),self.project.id,old.id,old.content_checksum,run,"design","legacy","legacy",datetime.now(timezone.utc).isoformat(),source_locator=verify_grounding(source_text="legacy",excerpt="legacy").to_dict(),deduplication_key="legacy")
        PostgreSQLEvidenceRepository(self.session_factory).create(evidence)
        acquired=self.acquire(run)
        self.assertTrue(acquired.metadata["structured_rows"])
        self.assertEqual(acquired.raw_checksum_kind,"sha256-bytes")
        self.assertEqual(self.repo.list_acquisition_paths(self.project.id,run)[0].diagnostics["capability_decision"],"REFETCH")
        count=len(self.hits)
        reused=self.acquire(self.run_id())
        self.assertEqual(reused.id,acquired.id)
        self.assertEqual(len(self.hits),count)
        extracted=self.acquire(self.run_id(),requested_extraction_revision="xlsx-structured-v3")
        self.assertNotEqual(extracted.id,acquired.id)
        self.assertEqual(extracted.content_revision,acquired.content_revision)
        self.body=workbook(900)
        changed=self.acquire(self.run_id(),acquisition_refresh="1")
        self.assertEqual(changed.content_revision,acquired.content_revision+1)
        fresh=DatabaseSessionFactory(self.engine)
        self.assertEqual(PostgreSQLSourceRepository(fresh).get_by_id(old.id).to_dict(),before)
        self.assertTrue(citation_is_valid(PostgreSQLEvidenceRepository(fresh).get_by_id(evidence.id),self.repo.get_by_id(old.id)))

    def test_two_landings_and_concurrent_refetch_share_revision(self):
        barrier=Barrier(2)
        runs=[self.run_id(),self.run_id()]
        def work(index):
            barrier.wait(timeout=10)
            return self.acquire(runs[index],landing="/landing"+str(index))
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows=list(pool.map(work,range(2)))
        self.assertEqual(rows[0].id,rows[1].id)
        self.assertEqual(len(self.repo.list_for_project(self.project.id)),1)
        for index,run in enumerate(runs):
            paths=self.repo.list_acquisition_paths(self.project.id,run)
            self.assertEqual(len(paths),1)
            self.assertEqual(paths[0].source_id,rows[0].id)
            self.assertEqual(paths[0].navigation_chain[0],self.origin+"/landing"+str(index))
        hits=len(self.hits)
        self.assertEqual(self.acquire(self.run_id(),landing="/landing1").id,rows[0].id)
        self.assertEqual(len(self.hits),hits)

    def test_failed_navigation_only_one_attempt_per_run(self):
        self.body=b"invalid workbook"
        run=self.run_id()
        failed=self.acquire(run)
        count=len(self.hits)
        again=self.acquire(run)
        self.assertEqual(again.id,failed.id)
        self.assertEqual(len(self.hits),count)
        self.assertNotEqual(failed.retrieval_status.value,"acquired")
