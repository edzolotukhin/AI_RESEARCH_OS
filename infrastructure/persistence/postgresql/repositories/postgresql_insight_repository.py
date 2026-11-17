from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from application.analysis.exceptions import DuplicateInsightError
from application.ports.analysis_ports import InsightRepository
from domain.findings.insight import Insight

from infrastructure.persistence.postgresql.mappers.finding_mapper import (
    insight_from_model,
    insight_to_model,
)
from infrastructure.persistence.postgresql.models.finding_model import InsightModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLInsightRepository(InsightRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, insight: Insight) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(insight_to_model(insight, version=1))
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateInsightError(
                    f"Insight already exists for run/key: "
                    f"{insight.workflow_run_id}/{insight.deduplication_key}",
                ) from exc
            insight.version = 1
            return 1

    def get_by_id(self, insight_id: str) -> Insight | None:
        with self._session_factory.session() as session:
            model = session.get(InsightModel, insight_id)
            if model is None:
                return None
            return insight_from_model(model)

    def lock_selected_for_authority(self, ids: tuple[str, ...]) -> tuple[Insight, ...]:
        """Lock exactly the selected Insight rows for an owned authority read."""
        from sqlalchemy import select

        session = self._session_factory.require_write_transaction()
        locked: list[Insight] = []
        for insight_id in sorted(ids):
            model = session.execute(
                select(InsightModel)
                .where(InsightModel.id == insight_id)
                .with_for_update(read=True)
            ).scalar_one_or_none()
            if model is None:
                raise ValueError("Selected Insight is missing")
            locked.append(insight_from_model(model))
        return tuple(locked)

    def get_by_deduplication_key(
        self,
        workflow_run_id: str,
        deduplication_key: str,
    ) -> Insight | None:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = select(InsightModel).where(
                InsightModel.workflow_run_id == workflow_run_id,
                InsightModel.deduplication_key == deduplication_key,
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return insight_from_model(model)

    def list_for_project(
        self,
        project_id: str,
        *,
        workflow_run_id: str | None = None,
        research_question_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[Insight]:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = (
                select(InsightModel)
                .where(InsightModel.project_id == project_id)
                .order_by(InsightModel.id)
            )
            if workflow_run_id is not None:
                statement = statement.where(
                    InsightModel.workflow_run_id == workflow_run_id,
                )
            models = session.scalars(statement).all()

        insights = [insight_from_model(model) for model in models]
        if research_question_id is not None:
            insights = [
                item
                for item in insights
                if research_question_id in item.research_question_refs
            ]
        if finding_id is not None:
            insights = [
                item for item in insights if finding_id in item.finding_refs
            ]
        return insights
