from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.analysis_ports import FindingRepository, InsightRepository
from domain.findings.finding import Finding
from domain.findings.insight import Insight


class FindingService:
    """Application service for durable research finding access."""

    def __init__(self, *, finding_repository: FindingRepository) -> None:
        self._finding_repository = finding_repository

    def get_finding(self, finding_id: str) -> Finding:
        finding = self._finding_repository.get_by_id(finding_id)
        if finding is None:
            raise EntityNotFoundError(f"Finding not found: {finding_id}")
        return finding

    def list_findings_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[Finding]:
        return self._finding_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
            research_question_id=research_question_id,
            information_need_id=information_need_id,
            evidence_id=evidence_id,
        )

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return len(
            self.list_findings_for_project(
                project_id,
                workflow_run_id=workflow_run_id,
            ),
        )

    def run_has_findings(self, project_id: str, workflow_run_id: str) -> bool:
        return self.count_for_run(project_id, workflow_run_id) > 0


class InsightService:
    """Application service for durable research insight access."""

    def __init__(self, *, insight_repository: InsightRepository) -> None:
        self._insight_repository = insight_repository

    def get_insight(self, insight_id: str) -> Insight:
        insight = self._insight_repository.get_by_id(insight_id)
        if insight is None:
            raise EntityNotFoundError(f"Insight not found: {insight_id}")
        return insight

    def list_insights_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[Insight]:
        return self._insight_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
            research_question_id=research_question_id,
            finding_id=finding_id,
        )

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return len(
            self.list_insights_for_project(
                project_id,
                workflow_run_id=workflow_run_id,
            ),
        )

    def run_has_insights(self, project_id: str, workflow_run_id: str) -> bool:
        return self.count_for_run(project_id, workflow_run_id) > 0
