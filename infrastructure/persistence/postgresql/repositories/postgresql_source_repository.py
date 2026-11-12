from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime, timezone
from uuid import uuid4
import json
from application.sources.source_identity import prepare_snapshot, assert_snapshot_unchanged, terminal_resource_key, acquisition_path_digest
from infrastructure.persistence.postgresql.models.source_model import SourceAcquisitionPathModel
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
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
        prepare_snapshot(source)
        with self._session_factory.session() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(source.terminal_resource_key[:15], 16)})
            if session.scalars(select(SourceModel).where(SourceModel.project_id == source.project_id, SourceModel.canonical_url == source.canonical_url)).first():
                raise DuplicateSourceError("Source already exists; use create_immutable_revision")
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
            current = session.get(SourceModel, source.id)
            if current is None:
                raise ValueError("Source not found")
            assert_snapshot_unchanged(source_from_model(current), source)
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
            model = session.scalars(statement.order_by(SourceModel.content_revision.desc(), SourceModel.retrieved_at.desc(), SourceModel.id)).first()
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

    def resolve_terminal_identity(self, project_id, terminal_url):
        return terminal_resource_key(project_id, terminal_url)

    def find_latest_content_revision(self, project_id, resource_key):
        with self._session_factory.session() as session:
            row = session.scalars(select(SourceModel).where(SourceModel.project_id == project_id, SourceModel.terminal_resource_key == resource_key).order_by(SourceModel.content_revision.desc(), SourceModel.retrieved_at.desc(), SourceModel.id)).first()
            return source_from_model(row) if row else None

    def find_matching_revision(self, project_id, resource_key, raw_checksum, extraction_revision, *, raw_checksum_kind="sha256-bytes"):
        with self._session_factory.session() as session:
            row = session.scalars(select(SourceModel).where(SourceModel.project_id == project_id, SourceModel.terminal_resource_key == resource_key, SourceModel.raw_content_checksum == raw_checksum, SourceModel.raw_checksum_kind == raw_checksum_kind, SourceModel.extraction_revision == extraction_revision)).first()
            return source_from_model(row) if row else None

    def create_immutable_revision(self, source):
        prepare_snapshot(source)
        with self._session_factory.session() as session:
            # Transaction-scoped resource lock also serializes the first insert.
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(source.terminal_resource_key[:15], 16)})
            rows = list(session.scalars(select(SourceModel).where(SourceModel.project_id == source.project_id, SourceModel.terminal_resource_key == source.terminal_resource_key)))
            matching = next((r for r in rows if r.raw_content_checksum == source.raw_content_checksum and r.raw_checksum_kind == source.raw_checksum_kind and r.extraction_revision == source.extraction_revision), None)
            if matching:
                if (matching.content_text or "", matching.content_checksum or "", matching.retrieval_status) != (source.content_text, source.content_checksum, source.retrieval_status.value):
                    raise ValueError("Content/extraction identity conflicts with persisted snapshot")
                return source_from_model(matching)
            same_bytes = [r for r in rows if source.raw_checksum_kind == "sha256-bytes" and r.raw_checksum_kind == "sha256-bytes" and r.raw_content_checksum == source.raw_content_checksum]
            source.content_revision = same_bytes[0].content_revision if same_bytes else max((r.content_revision for r in rows), default=0) + 1
            source.id = str(uuid4()) if any(r.id == source.id for r in rows) or not source.id else source.id
            source.version = 1
            session.add(source_to_model(source, version=1))
            session.flush()
            return source

    def persist_acquisition_path(self, path):
        if len(path.navigation_chain) > 32 or len(json.dumps(path.diagnostics)) > 8192:
            raise ValueError("Acquisition diagnostics exceed bounds")
        digest = acquisition_path_digest(project_id=path.project_id, landing_url=path.landing_url, terminal_url=path.terminal_url, navigation_chain=path.navigation_chain)
        with self._session_factory.session() as session:
            source = session.get(SourceModel, path.source_id)
            run = session.get(WorkflowRunModel, path.workflow_run_id)
            if source is None or run is None or source.project_id != path.project_id or run.project_id != path.project_id:
                raise ValueError("Foreign source/workflow acquisition path")
            if source.terminal_resource_key != terminal_resource_key(path.project_id, path.terminal_url):
                raise ValueError("Terminal resource mismatch")
            statement = insert(SourceAcquisitionPathModel).values(id=str(uuid4()), project_id=path.project_id, workflow_run_id=path.workflow_run_id, source_id=path.source_id, path_digest=digest, landing_url=path.landing_url, terminal_url=path.terminal_url, navigation_chain=list(path.navigation_chain), diagnostics=dict(path.diagnostics), created_at=datetime.now(timezone.utc)).on_conflict_do_nothing(constraint="uq_source_path_observation")
            session.execute(statement)
            return digest

    def list_acquisition_paths(self, project_id, workflow_run_id):
        with self._session_factory.session() as session:
            return list(session.scalars(select(SourceAcquisitionPathModel).where(SourceAcquisitionPathModel.project_id == project_id, SourceAcquisitionPathModel.workflow_run_id == workflow_run_id)))
