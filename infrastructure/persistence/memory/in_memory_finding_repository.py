from __future__ import annotations

import threading

from application.analysis.exceptions import DuplicateFindingError
from application.ports.analysis_ports import FindingRepository
from domain.findings.finding import Finding


class InMemoryFindingRepository(FindingRepository):
    def __init__(self) -> None:
        self._findings: dict[str, Finding] = {}
        self._lock = threading.RLock()

    def create(self, finding: Finding) -> int:
        with self._lock:
            existing = self.get_by_deduplication_key(
                finding.workflow_run_id,
                finding.deduplication_key,
            )
            if existing is not None:
                raise DuplicateFindingError(
                    f"Finding already exists for run/key: "
                    f"{finding.workflow_run_id}/{finding.deduplication_key}",
                )
            self._findings[finding.id] = finding
            finding.version = 1
            return 1

    def get_by_id(self, finding_id: str) -> Finding | None:
        with self._lock:
            return self._findings.get(finding_id)

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Finding | None:
        with self._lock:
            for finding in self._findings.values():
                if (
                    finding.workflow_run_id == workflow_run_id
                    and finding.deduplication_key == deduplication_key
                ):
                    return finding
            return None

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[Finding]:
        with self._lock:
            items = [
                finding
                for finding in self._findings.values()
                if finding.project_id == project_id
            ]
        if workflow_run_id is not None:
            items = [
                finding for finding in items if finding.workflow_run_id == workflow_run_id
            ]
        if research_question_id is not None:
            items = [
                finding
                for finding in items
                if research_question_id in finding.research_question_refs
            ]
        if information_need_id is not None:
            items = [
                finding
                for finding in items
                if information_need_id in finding.information_need_refs
            ]
        if evidence_id is not None:
            items = [
                finding for finding in items if evidence_id in finding.evidence_refs
            ]
        return sorted(items, key=lambda item: item.id)
