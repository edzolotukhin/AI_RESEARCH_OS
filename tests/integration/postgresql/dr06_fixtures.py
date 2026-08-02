"""Shared DR-06 PostgreSQL integration fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template_builder import WorkflowTemplateBuilder

from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
    PostgreSQLEvidenceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
    PostgreSQLFindingRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
    PostgreSQLInsightRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
    PostgreSQLSourceRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from runtime.workflow_context import WorkflowContext

from tests.fixtures.research_brief import sample_research_brief


def seed_report_prerequisites(
    session_factory: DatabaseSessionFactory,
    *,
    project_name: str = "DR-06 Fixture Project",
    run_id: str | None = None,
    project: Project | None = None,
) -> tuple[Project, WorkflowContext, str, str, str, str]:
    """Persist run-scoped analysis inputs required by ReportService."""
    if project is None:
        project = ProjectFactory().create(project_name)
        PostgreSQLProjectRepository(session_factory).create(project)

    brief = sample_research_brief()
    design = ResearchDesign(
        id="design-dr06",
        research_questions=(
            ResearchQuestion(
                id="rq-a",
                question="What is the market position?",
                objective_refs=("obj-1",),
                priority=1,
                rationale="Primary question",
            ),
        ),
        information_needs=(
            InformationNeed(
                id="in-a",
                research_question_id="rq-a",
                description="Market share data",
            ),
        ),
        source_strategy=("web",),
        analysis_plan=("compare",),
        deliverable_plan=("summary",),
        assumptions=(),
        limitations=("Sample limitations",),
        language="en",
    )
    template = (
        WorkflowTemplateBuilder(id="template-dr06", name="DR-06 Template")
        .add_task(
            id="task-write-report",
            name="Write Report",
            executor_id="report",
            executor_type=ExecutorType.AGENT,
        )
        .build()
    )
    template.research_brief_snapshot = brief
    template.research_design_snapshot = design

    run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template=template,
        run_id=run_id,
    )
    run.project_id = project.id
    context = WorkflowContext(
        project=project,
        workflow_run=run,
        workflow_template=template,
        current_task=run.tasks[0],
    )

    now = datetime.now(timezone.utc).isoformat()
    source_id = str(uuid4())
    evidence_id = str(uuid4())
    finding_id = str(uuid4())
    insight_id = str(uuid4())
    source_url = f"https://example.com/market-report/{run.id}"

    source_repo = PostgreSQLSourceRepository(session_factory)
    evidence_repo = PostgreSQLEvidenceRepository(session_factory)
    finding_repo = PostgreSQLFindingRepository(session_factory)
    insight_repo = PostgreSQLInsightRepository(session_factory)

    source_repo.create(
        Source(
            id=source_id,
            project_id=project.id,
            url=source_url,
            canonical_url=source_url,
            title="Market Report",
            retrieved_at=now,
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="Market share increased in 2026.",
            content_checksum="checksum-source",
            query_refs=("sq-in-a",),
            research_question_refs=("rq-a",),
            information_need_refs=("in-a",),
            workflow_run_refs=(run.id,),
            research_design_refs=(design.id,),
        ),
    )
    evidence_repo.create(
        Evidence(
            id=evidence_id,
            project_id=project.id,
            source_id=source_id,
            source_content_checksum="checksum-source",
            workflow_run_id=run.id,
            research_design_id=design.id,
            statement="Market share increased in 2026.",
            source_excerpt="Market share increased in 2026.",
            created_at=now,
            research_question_refs=("rq-a",),
            information_need_refs=("in-a",),
            evidence_type=EvidenceType.DIRECT_EXCERPT,
            deduplication_key=f"dedup-{evidence_id}",
        ),
    )
    finding_repo.create(
        Finding(
            id=finding_id,
            project_id=project.id,
            workflow_run_id=run.id,
            research_design_id=design.id,
            statement="Brand awareness is strong.",
            rationale="Supported by market data",
            evidence_refs=(evidence_id,),
            finding_type=FindingType.SYNTHESIS,
            analysis_method="deterministic",
            research_question_refs=("rq-a",),
            deduplication_key=f"dedup-{finding_id}",
            created_at=now,
        ),
    )
    insight_repo.create(
        Insight(
            id=insight_id,
            project_id=project.id,
            workflow_run_id=run.id,
            research_design_id=design.id,
            statement="Position is defensible.",
            implication="Maintain current strategy",
            finding_refs=(finding_id,),
            research_question_refs=("rq-a",),
            deduplication_key=f"dedup-{insight_id}",
            created_at=now,
        ),
    )

    return project, context, source_id, evidence_id, finding_id, insight_id


def build_report_service(session_factory: DatabaseSessionFactory):
    from application.report.report_service import ReportService
    from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
        PostgreSQLArtifactRepository,
    )
    from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import (
        PostgreSQLReportRepository,
    )
    from infrastructure.report.deterministic_report_engine import DeterministicReportEngine

    return ReportService(
        report_engine=DeterministicReportEngine(),
        finding_repository=PostgreSQLFindingRepository(session_factory),
        insight_repository=PostgreSQLInsightRepository(session_factory),
        evidence_repository=PostgreSQLEvidenceRepository(session_factory),
        source_repository=PostgreSQLSourceRepository(session_factory),
        report_repository=PostgreSQLReportRepository(session_factory),
        artifact_repository=PostgreSQLArtifactRepository(session_factory),
        max_findings_per_batch=10,
        max_chars_per_batch=12000,
    )
