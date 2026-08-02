from __future__ import annotations

import threading

from application.evidence.exceptions import DuplicateEvidenceError
from application.ports.evidence_ports import EvidenceRepository
from domain.evidence.evidence import Evidence


class InMemoryEvidenceRepository(EvidenceRepository):
    def __init__(self) -> None:
        self._evidence: dict[str, Evidence] = {}
        self._lock = threading.RLock()

    def create(self, evidence: Evidence) -> int:
        with self._lock:
            existing = self.get_by_deduplication_key(
                evidence.workflow_run_id,
                evidence.deduplication_key,
            )
            if existing is not None:
                raise DuplicateEvidenceError(
                    f"Evidence already exists for run/key: "
                    f"{evidence.workflow_run_id}/{evidence.deduplication_key}",
                )
            self._evidence[evidence.id] = evidence
            evidence.version = 1
            return 1

    def get_by_id(self, evidence_id: str) -> Evidence | None:
        with self._lock:
            return self._evidence.get(evidence_id)

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Evidence | None:
        with self._lock:
            for evidence in self._evidence.values():
                if (
                    evidence.workflow_run_id == workflow_run_id
                    and evidence.deduplication_key == deduplication_key
                ):
                    return evidence
            return None

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        information_need_id: str | None = None,
        source_id: str | None = None,
    ) -> list[Evidence]:
        with self._lock:
            items = [
                evidence
                for evidence in self._evidence.values()
                if evidence.project_id == project_id
            ]
        if workflow_run_id is not None:
            items = [
                evidence
                for evidence in items
                if evidence.workflow_run_id == workflow_run_id
            ]
        if research_question_id is not None:
            items = [
                evidence
                for evidence in items
                if research_question_id in evidence.research_question_refs
            ]
        if information_need_id is not None:
            items = [
                evidence
                for evidence in items
                if information_need_id in evidence.information_need_refs
            ]
        if source_id is not None:
            items = [evidence for evidence in items if evidence.source_id == source_id]
        return sorted(items, key=lambda item: item.id)
