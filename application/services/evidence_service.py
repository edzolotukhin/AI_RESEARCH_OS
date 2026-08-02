from __future__ import annotations

from application.persistence.exceptions import EntityNotFoundError
from application.ports.evidence_ports import EvidenceRepository
from domain.evidence.evidence import Evidence


class EvidenceService:
    """Application service for durable research evidence access."""

    def __init__(self, *, evidence_repository: EvidenceRepository) -> None:
        self._evidence_repository = evidence_repository

    def get_evidence(self, evidence_id: str) -> Evidence:
        evidence = self._evidence_repository.get_by_id(evidence_id)
        if evidence is None:
            raise EntityNotFoundError(f"Evidence not found: {evidence_id}")
        return evidence

    def list_evidence_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        source_id: str | None = None,
    ) -> list[Evidence]:
        return self._evidence_repository.list_for_project(
            project_id,
            workflow_run_id=workflow_run_id,
            research_question_id=research_question_id,
            information_need_id=information_need_id,
            source_id=source_id,
        )

    def count_for_run(self, project_id: str, workflow_run_id: str) -> int:
        return len(
            self.list_evidence_for_project(
                project_id,
                workflow_run_id=workflow_run_id,
            ),
        )

    def run_has_evidence(self, project_id: str, workflow_run_id: str) -> bool:
        return self.count_for_run(project_id, workflow_run_id) > 0
