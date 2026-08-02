from __future__ import annotations

import httpx
from sqlalchemy.exc import IntegrityError

from application.persistence.exceptions import ConcurrentModificationError
from application.ports.source_ports import SourceRepository
from application.sources.exceptions import DuplicateSourceError
from domain.sources.source import Source
from infrastructure.persistence.postgresql.concurrency import atomic_update_version
from infrastructure.persistence.postgresql.mappers.source_mapper import (
    source_from_model,
    source_to_model,
    source_to_update_values,
)
from infrastructure.persistence.postgresql.models.source_model import SourceModel
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory


class PostgreSQLSourceRepository(SourceRepository):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, source: Source) -> int:
        with self._session_factory.session() as session:
            try:
                session.add(source_to_model(source, version=1))
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateSourceError(
                    f"Source already exists for {source.project_id} / "
                    f"{source.canonical_url}",
                ) from exc
            source.version = 1
            return 1

    def save(
        self,
        source: Source,
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._session_factory.session() as session:
            try:
                new_version = atomic_update_version(
                    session,
                    SourceModel,
                    source.id,
                    expected_version=expected_version,
                    values=source_to_update_values(source),
                )
            except ConcurrentModificationError:
                raise
            source.version = new_version
            return new_version

    def get_by_id(self, source_id: str) -> Source | None:
        with self._session_factory.session() as session:
            model = session.get(SourceModel, source_id)
            if model is None:
                return None
            return source_from_model(model)

    def get_by_canonical_url_for_project(
        self,
        project_id: str,
        canonical_url: str,
    ) -> Source | None:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = select(SourceModel).where(
                SourceModel.project_id == project_id,
                SourceModel.canonical_url == canonical_url,
            )
            model = session.scalars(statement).first()
            if model is None:
                return None
            return source_from_model(model)

    def list_for_project(
        self,
        project_id: str,
        *,
        research_question_id: str | None = None,
        retrieval_status: str | None = None,
        workflow_run_id: str | None = None,
    ) -> list[Source]:
        from sqlalchemy import select

        with self._session_factory.session() as session:
            statement = (
                select(SourceModel)
                .where(SourceModel.project_id == project_id)
                .order_by(SourceModel.id)
            )
            models = session.scalars(statement).all()
        sources = [source_from_model(model) for model in models]
        if workflow_run_id is not None:
            sources = [
                source
                for source in sources
                if workflow_run_id in source.workflow_run_refs
            ]
        if research_question_id is not None:
            sources = [
                source
                for source in sources
                if research_question_id in source.research_question_refs
            ]
        if retrieval_status is not None:
            sources = [
                source
                for source in sources
                if source.retrieval_status.value == retrieval_status
            ]
        return sources
