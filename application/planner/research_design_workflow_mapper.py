from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from domain.planning.research_design import ResearchDesign
from domain.project import Project
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate
from domain.workflow_template_builder import WorkflowTemplateBuilder

from .exceptions import PlannerMappingError


class ResearchDesignWorkflowMapper:
    """
    Deterministically maps ResearchDesign to WorkflowTemplate.

    Semantic planning (LLM) is separated from runtime task topology (code).
    """

    _TASK_COLLECT = "task-collect-evidence"
    _TASK_ANALYZE = "task-analyze"
    _TASK_REPORT = "task-write-report"

    def from_research_design(
        self,
        design: ResearchDesign,
        project: Project,
    ) -> WorkflowTemplate:
        brief = project.research_brief
        template_name = brief.title if brief is not None else "Desk Research Workflow"

        builder = WorkflowTemplateBuilder(
            id=str(uuid4()),
            name=template_name,
        )

        builder.add_task(
            id=self._TASK_COLLECT,
            name="Collect evidence",
            executor_id="search",
            executor_type=ExecutorType.AGENT,
            depends_on=[],
            metadata={
                "stage_id": "stage-desk-research",
                "stage_name": "Desk Research",
                "project_id": project.id,
                "research_design_id": design.id,
                "purpose": "collect_sources",
                "implementation_status": "planned",
            },
        )
        builder.add_task(
            id=self._TASK_ANALYZE,
            name="Analyze findings",
            executor_id="analysis",
            executor_type=ExecutorType.AGENT,
            depends_on=[self._TASK_COLLECT],
            metadata={
                "stage_id": "stage-desk-research",
                "stage_name": "Desk Research",
                "project_id": project.id,
                "research_design_id": design.id,
                "purpose": "analyze",
                "implementation_status": "planned",
            },
        )
        builder.add_task(
            id=self._TASK_REPORT,
            name="Write research report",
            executor_id="report",
            executor_type=ExecutorType.AGENT,
            depends_on=[self._TASK_ANALYZE],
            metadata={
                "stage_id": "stage-desk-research",
                "stage_name": "Desk Research",
                "project_id": project.id,
                "research_design_id": design.id,
                "purpose": "write_report",
                "implementation_status": "planned",
            },
        )

        template = builder.build()
        return replace(
            template,
            research_brief_snapshot=brief,
            research_design_snapshot=design,
        )
