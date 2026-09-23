from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from application.query.desk_workbench_query_service import COLLECTION_LIMIT, DeskWorkbenchQueryService
from application.query.research_status import ResearchExecutionStatus, ResearchPhase, ResearchStatusProjection
from domain.research_brief import ResearchBrief
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate


class DeskWorkbenchQueryTests(TestCase):
    def setUp(self):
        self.container=MagicMock(); self.project=SimpleNamespace(id="project-a",name="Проєкт А")
        self.run=SimpleNamespace(id="run-a",project_id="project-a",workflow_template_id="template-a",status=WorkflowStatus.RUNNING)
        self.container.workflow_service.get_workflow_run.return_value=self.run
        self.container.workflow_service.get_template.return_value=WorkflowTemplate(
            id="template-a",name="Історичний план",
            research_brief_snapshot=ResearchBrief("Назва","Питання"),
        )
        self.container.research_status_query_service.get_status.return_value=ResearchStatusProjection(
            "run-a","project-a",ResearchExecutionStatus.RUNNING,ResearchPhase.RESEARCHING,None,False,"running")
        self.container.evidence_service.list_evidence_for_project.return_value=[]
        self.container.finding_service.list_findings_for_project.return_value=[]
        self.container.insight_service.list_insights_for_project.return_value=[]
        self.container.report_query_service.list_reports_for_project.return_value=[]
        self.container.review_query_service.list_reviews_for_project.return_value=[]

    def test_every_collection_query_is_explicitly_run_scoped(self):
        self.container.source_service.list_sources_for_run.return_value=[]
        view=DeskWorkbenchQueryService(container=self.container).get("run-a",project=self.project)
        self.assertEqual(view.header.project_name,"Проєкт А")
        self.container.source_service.list_sources_for_run.assert_called_once_with("run-a",project_id="project-a")
        self.container.evidence_service.list_evidence_for_project.assert_called_once_with("project-a",workflow_run_id="run-a")
        self.container.finding_service.list_findings_for_project.assert_called_once_with("project-a",workflow_run_id="run-a")
        self.container.insight_service.list_insights_for_project.assert_called_once_with("project-a",workflow_run_id="run-a")
        self.container.report_query_service.list_reports_for_project.assert_called_once_with("project-a",workflow_run_id="run-a")
        self.container.review_query_service.list_reviews_for_project.assert_called_once_with("project-a",workflow_run_id="run-a")

    def test_collection_is_bounded_and_total_remains_honest(self):
        self.container.source_service.list_sources_for_run.return_value=[
            Source(str(i),"project-a",f"https://example.com/{i}",f"https://example.com/{i}",f"Source {i}","2026-01-01",workflow_run_refs=("run-a",),retrieval_status=RetrievalStatus.ACQUIRED)
            for i in range(COLLECTION_LIMIT+7)
        ]
        view=DeskWorkbenchQueryService(container=self.container).get("run-a",project=self.project)
        self.assertEqual(len(view.sources),COLLECTION_LIMIT); self.assertEqual(view.sources_total,COLLECTION_LIMIT+7)

    def test_project_run_mismatch_fails_closed_before_collection_queries(self):
        with self.assertRaisesRegex(ValueError,"scope"):
            DeskWorkbenchQueryService(container=self.container).get("run-a",project=SimpleNamespace(id="project-b",name="B"))
        self.container.source_service.list_sources_for_run.assert_not_called()

    def test_historical_missing_design_is_explicit(self):
        self.container.source_service.list_sources_for_run.return_value=[]
        view=DeskWorkbenchQueryService(container=self.container).get("run-a",project=self.project)
        self.assertTrue(view.design.historical_fallback); self.assertEqual(view.design.research_questions,())
