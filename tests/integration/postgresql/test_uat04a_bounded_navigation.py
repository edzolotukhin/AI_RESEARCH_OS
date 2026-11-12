from __future__ import annotations

import io
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import httpx
from openpyxl import Workbook

from application.composition_root import create_application_container
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.source_acquisition_service import SourceAcquisitionService
from application.sources.source_budget import SourceAcquisitionBudget
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.sources.search_query import SearchQuery
from domain.sources.source_candidate import SourceCandidate
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from infrastructure.evidence.deterministic_evidence_extractor import DeterministicEvidenceExtractor
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.config import ApplicationOverrides
from tests.application.evidence.test_structured_production import design as structured_design
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever
from runtime.workflow_context import WorkflowContext
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, postgresql_application_config


class _FixtureSearchProvider:
    def search(self, query: SearchQuery) -> list[SourceCandidate]:
        return [SourceCandidate("fixture", "https://example.org/landing", "Population Ukraine 2019–2021", "Annual population statistics", query.id, 1)]


def _workbook() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Population"
    sheet.append(["Year", "Population", "Unit", "Geography"])
    for year, value in ((2019, 1000), (2020, 950), (2021, 900)):
        sheet.append([year, value, "persons", "Ukraine"])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


class Uat04aBoundedNavigationPostgreSQLTests(PostgreSQLIntegrationTestCase):
    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses",return_value=["93.184.216.34"])
    def test_landing_resource_xlsx_structured_evidence_persists_and_is_idempotent(self, _dns) -> None:
        workbook = _workbook()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/landing":
                return httpx.Response(200, text='<a href="/resource">resource</a>', headers={"content-type": "text/html"})
            if request.url.path == "/resource":
                return httpx.Response(200, text='<h1>Population.xlsx</h1><p>Format: XLSX</p><a href="/download/123">Завантажити</a>', headers={"content-type": "text/html"})
            if request.url.path == "/download/123":
                return httpx.Response(200, content=workbook, headers={"content-type": "application/octet-stream"})
            return httpx.Response(200, content=workbook, headers={"content-type": "application/octet-stream"})

        project = Project(
            id="uat04a-project", name="UAT-04A",
            research_brief=ResearchBrief(title="Population", business_question="Population", timeframe="2019-2021"),
        )
        design = ResearchDesign(
            id="uat04a-design",
            research_questions=(ResearchQuestion(id="rq-pop", question="Population", objective_refs=()),),
            information_needs=(InformationNeed(id="in-pop", research_question_id="rq-pop", description="Annual population"),),
        )
        design = replace(structured_design(), id="uat04a-design")
        template = WorkflowTemplate(
            id="uat04a-template",
            name="Desk",
            task_definitions=(TaskDefinition(id="task-collect-evidence", name="Collect", executor_id="search", executor_type=ExecutorType.AGENT),),
            research_design_snapshot=design,
        )
        run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template, run_id="uat04a-run", project_id=project.id)
        context = WorkflowContext(project=project, workflow_template=template, workflow_run=run)
        context.current_task = run.tasks[0]

        container = create_application_container(config=postgresql_application_config())
        self.addCleanup(container.shutdown)
        container.project_service.create_project(project.name, project_id=project.id)
        container.project_service.save_project(project)
        with self.session_factory.session() as session:
            session.add(WorkflowRunModel(id=run.id,project_id=project.id,workflow_template_id=template.id,status="completed",dependency_graph={},task_results={},version=0))
        source_repository = container.source_service._source_repository
        evidence_repository = container.evidence_service._evidence_repository
        retriever = HttpSourceRetriever(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        acquisition = SourceAcquisitionService(
            search_provider=_FixtureSearchProvider(), source_retriever=retriever,
            source_repository=source_repository, query_builder=SearchQueryBuilder(),
            budget=SourceAcquisitionBudget(min_successful_sources=1),
        )
        query = SearchQuery("uat04a-query", "rq-pop", "in-pop", "population 2019 2021")
        acquired = acquisition.acquire_targeted_queries(context, [query], max_sources=1)
        self.assertEqual(acquired.sources_acquired, 1, acquired.to_dict())
        source = source_repository.get_by_id(acquired.source_ids[0])
        assert source is not None
        self.assertEqual(source.metadata["navigation_chain"], [
            "https://example.org/landing", "https://example.org/resource", "https://example.org/download/123",
        ])
        assert source.metadata["navigation_diagnostics"]["selected_link"] == "https://example.org/download/123"
        self.assertEqual(len(source.metadata.get("structured_rows", [])), 4, source.metadata)
        self.assertIn('Sheet="Population"', source.content_text)
        self.assertIn('Year=2019', source.content_text)
        self.assertIn('Population=1000', source.content_text)

        provider=Mock()
        provider.generate.side_effect=AssertionError("Structured rows require no LLM")
        extraction = build_evidence_extraction_service(config=postgresql_application_config(evidence_extractor="llm"),overrides=ApplicationOverrides(),llm_client=provider,evidence_repository=evidence_repository,source_repository=source_repository)
        first = extraction.extract_for_source_ids(context, acquired.source_ids, target_information_need_id="in-pop")
        self.assertEqual(first.evidence_extracted, 3)
        evidence = evidence_repository.list_for_project(project.id, workflow_run_id=run.id)
        self.assertEqual(sorted(int(item.metadata["observation_period"]) for item in evidence), [2019, 2020, 2021])
        self.assertEqual(sorted(item.metadata["numeric_value"] for item in evidence), [900, 950, 1000])
        self.assertEqual(sorted(item.source_locator["structured"]["row"] for item in evidence), [2, 3, 4])
        self.assertTrue(all(item.source_locator["structured"]["sheet"] == "Population" for item in evidence))
        self.assertTrue(all("in-pop" in item.information_need_refs for item in evidence))
        self.assertEqual(len(evidence_repository.list_for_project(project.id, workflow_run_id=run.id)), 3)
        provider.generate.assert_not_called()

        second = extraction.extract_for_source_ids(context, acquired.source_ids, target_information_need_id="in-pop")
        self.assertEqual(second.evidence_extracted, 3)
        self.assertEqual(len(evidence_repository.list_for_project(project.id, workflow_run_id=run.id)), 3)


if __name__ == "__main__":
    unittest.main()
