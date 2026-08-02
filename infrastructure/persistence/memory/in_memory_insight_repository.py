from __future__ import annotations

import threading

from application.analysis.exceptions import DuplicateInsightError
from application.ports.analysis_ports import InsightRepository
from domain.findings.insight import Insight


class InMemoryInsightRepository(InsightRepository):
    def __init__(self) -> None:
        self._insights: dict[str, Insight] = {}
        self._lock = threading.RLock()

    def create(self, insight: Insight) -> int:
        with self._lock:
            existing = self.get_by_deduplication_key(
                insight.workflow_run_id,
                insight.deduplication_key,
            )
            if existing is not None:
                raise DuplicateInsightError(
                    f"Insight already exists for run/key: "
                    f"{insight.workflow_run_id}/{insight.deduplication_key}",
                )
            self._insights[insight.id] = insight
            insight.version = 1
            return 1

    def get_by_id(self, insight_id: str) -> Insight | None:
        with self._lock:
            return self._insights.get(insight_id)

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Insight | None:
        with self._lock:
            for insight in self._insights.values():
                if (
                    insight.workflow_run_id == workflow_run_id
                    and insight.deduplication_key == deduplication_key
                ):
                    return insight
            return None

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[Insight]:
        with self._lock:
            items = [
                insight
                for insight in self._insights.values()
                if insight.project_id == project_id
            ]
        if workflow_run_id is not None:
            items = [
                insight for insight in items if insight.workflow_run_id == workflow_run_id
            ]
        if research_question_id is not None:
            items = [
                insight
                for insight in items
                if research_question_id in insight.research_question_refs
            ]
        if finding_id is not None:
            items = [
                insight for insight in items if finding_id in insight.finding_refs
            ]
        return sorted(items, key=lambda item: item.id)
