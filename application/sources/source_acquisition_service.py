from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.planning.research_design import ResearchDesign
from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.search_query import SearchQuery
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate

from application.persistence.exceptions import ConcurrentModificationError
from application.ports.source_ports import (
    SearchProvider,
    SourceRepository,
    SourceRetriever,
)
from application.sources.exceptions import DuplicateSourceError, SourceAcquisitionError
from application.sources.provenance_merge import (
    ProvenanceDelta,
    apply_first_acquisition,
    apply_provenance_delta,
    build_discovery_record,
    has_immutable_acquired_content,
    is_successful_acquisition,
    merge_refs,
    missing_discovery_records,
)
from application.sources.search_query_builder import SearchQueryBuilder
from application.sources.url_canonicalizer import canonicalize_url

from runtime.workflow_context import WorkflowContext

_MAX_PROVENANCE_RETRIES = 5


@dataclass(frozen=True)
class SourceAcquisitionSummary:
    source_ids: tuple[str, ...]
    queries_executed: int
    candidates_found: int
    sources_acquired: int
    retrieval_failures: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ids": list(self.source_ids),
            "queries_executed": self.queries_executed,
            "candidates_found": self.candidates_found,
            "sources_acquired": self.sources_acquired,
            "retrieval_failures": self.retrieval_failures,
        }


@dataclass
class _PendingCandidate:
    candidate: SourceCandidate
    query: SearchQuery
    canonical_url: str


class SourceAcquisitionService:
    """Orchestrates search, deduplication, retrieval, and source persistence."""

    def __init__(
        self,
        *,
        search_provider: SearchProvider,
        source_retriever: SourceRetriever,
        source_repository: SourceRepository,
        query_builder: SearchQueryBuilder | None = None,
    ) -> None:
        self._search_provider = search_provider
        self._source_retriever = source_retriever
        self._source_repository = source_repository
        self._query_builder = query_builder or SearchQueryBuilder()

    def acquire_for_context(self, context: WorkflowContext) -> SourceAcquisitionSummary:
        design = self._resolve_design(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        queries = self._query_builder.build_queries(design)

        pending = self._collect_candidates(queries)
        source_ids, acquired, failures = self._acquire_candidates(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
            grouped=pending,
        )

        if acquired == 0:
            raise SourceAcquisitionError(
                "No sources were successfully acquired for project "
                f"{project_id}",
            )

        return SourceAcquisitionSummary(
            source_ids=tuple(source_ids),
            queries_executed=len(queries),
            candidates_found=sum(len(items) for items in pending.values()),
            sources_acquired=acquired,
            retrieval_failures=failures,
        )

    def _resolve_design(self, context: WorkflowContext) -> ResearchDesign:
        template = context.workflow_template
        if template is None or template.research_design_snapshot is None:
            raise SourceAcquisitionError(
                "Workflow template is missing research_design_snapshot",
            )
        return template.research_design_snapshot

    def _collect_candidates(
        self,
        queries: list[SearchQuery],
    ) -> dict[str, list[_PendingCandidate]]:
        grouped: dict[str, list[_PendingCandidate]] = {}

        for query in queries:
            candidates = self._search_provider.search(query)
            for candidate in candidates:
                try:
                    canonical = canonicalize_url(candidate.url)
                except ValueError:
                    continue
                grouped.setdefault(canonical, []).append(
                    _PendingCandidate(
                        candidate=candidate,
                        query=query,
                        canonical_url=canonical,
                    ),
                )
        return grouped

    def _acquire_candidates(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        grouped: dict[str, list[_PendingCandidate]],
    ) -> tuple[list[str], int, int]:
        source_ids: list[str] = []
        acquired = 0
        failures = 0

        for items in grouped.values():
            resolved = self._resolve_source_for_group(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
                items=items,
            )
            source_ids.append(resolved.id)
            if is_successful_acquisition(resolved.retrieval_status):
                acquired += 1
            elif resolved.retrieval_status in {
                RetrievalStatus.FAILED,
                RetrievalStatus.UNSUPPORTED,
            }:
                failures += 1

        return source_ids, acquired, failures

    def _resolve_source_for_group(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        items: list[_PendingCandidate],
    ) -> Source:
        primary = items[0]
        delta = self._build_delta(
            items=items,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
        )

        existing = self._source_repository.get_by_canonical_url_for_project(
            project_id,
            primary.canonical_url,
        )
        if existing is not None:
            return self._merge_existing_source(existing, delta, incoming=None)

        retrieved = self._source_retriever.retrieve(primary.candidate)
        incoming = self._finalize_source(
            retrieved=retrieved,
            project_id=project_id,
            item=primary,
            items=items,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
        )

        for attempt in range(_MAX_PROVENANCE_RETRIES):
            try:
                self._source_repository.create(incoming)
                return incoming
            except DuplicateSourceError:
                existing = self._source_repository.get_by_canonical_url_for_project(
                    project_id,
                    primary.canonical_url,
                )
                if existing is None:
                    continue
                return self._merge_existing_source(existing, delta, incoming=incoming)

        raise SourceAcquisitionError(
            f"Failed to resolve concurrent source acquisition for "
            f"{primary.canonical_url}",
        )

    def _merge_existing_source(
        self,
        existing: Source,
        delta: ProvenanceDelta,
        *,
        incoming: Source | None,
    ) -> Source:
        for attempt in range(_MAX_PROVENANCE_RETRIES):
            pending_records = missing_discovery_records(
                existing,
                delta.discovery_records,
            )
            before_run_refs = existing.workflow_run_refs
            before_design_refs = existing.research_design_refs
            before_query_refs = existing.query_refs
            before_question_refs = existing.research_question_refs
            before_need_refs = existing.information_need_refs
            before_metadata = dict(existing.metadata or {})
            before_content = existing.content_text

            merged = apply_provenance_delta(existing, delta)
            if incoming is not None and not has_immutable_acquired_content(merged):
                merged = apply_first_acquisition(merged, incoming)

            if (
                pending_records
                or merged.workflow_run_refs != before_run_refs
                or merged.research_design_refs != before_design_refs
                or merged.query_refs != before_query_refs
                or merged.research_question_refs != before_question_refs
                or merged.information_need_refs != before_need_refs
                or merged.metadata != before_metadata
                or merged.content_text != before_content
            ):
                try:
                    self._source_repository.save(merged, expected_version=merged.version)
                    return merged
                except ConcurrentModificationError:
                    reloaded = self._source_repository.get_by_id(existing.id)
                    if reloaded is None:
                        break
                    existing = reloaded
                    continue
            return merged
        raise SourceAcquisitionError(
            f"Failed to merge provenance for source {existing.id}",
        )

    def _build_delta(
        self,
        *,
        items: list[_PendingCandidate],
        workflow_run_id: str,
        research_design_id: str,
    ) -> ProvenanceDelta:
        query_refs: tuple[str, ...] = ()
        question_refs: tuple[str, ...] = ()
        need_refs: tuple[str, ...] = ()
        discovery_records: list[dict[str, Any]] = []
        for item in items:
            query_refs = merge_refs(query_refs, (item.query.id,))
            question_refs = merge_refs(
                question_refs,
                (item.query.research_question_id,),
            )
            need_refs = merge_refs(need_refs, (item.query.information_need_id,))
            discovery_records.append(
                build_discovery_record(
                    provider=item.candidate.provider,
                    query_id=item.query.id,
                    rank=item.candidate.rank,
                    workflow_run_id=workflow_run_id,
                    research_design_id=research_design_id,
                    research_question_id=item.query.research_question_id,
                    information_need_id=item.query.information_need_id,
                ),
            )
        return ProvenanceDelta(
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
            query_refs=query_refs,
            research_question_refs=question_refs,
            information_need_refs=need_refs,
            discovery_records=tuple(discovery_records),
        )

    def _finalize_source(
        self,
        *,
        retrieved: Source,
        project_id: str,
        item: _PendingCandidate,
        items: list[_PendingCandidate],
        workflow_run_id: str,
        research_design_id: str,
    ) -> Source:
        now = datetime.now(timezone.utc).isoformat()
        content_text = retrieved.content_text
        checksum = self._checksum(content_text) if content_text else ""
        delta = self._build_delta(
            items=items,
            workflow_run_id=workflow_run_id,
            research_design_id=research_design_id,
        )
        metadata = dict(retrieved.metadata)
        metadata["discovery_records"] = list(delta.discovery_records)
        if retrieved.retrieval_status == RetrievalStatus.TRUNCATED:
            metadata["truncated"] = True

        return Source(
            id=str(uuid4()),
            project_id=project_id,
            url=item.candidate.url,
            canonical_url=item.canonical_url,
            title=retrieved.title or item.candidate.title,
            publisher=retrieved.publisher,
            author=retrieved.author,
            published_at=retrieved.published_at or item.candidate.published_at,
            retrieved_at=retrieved.retrieved_at or now,
            source_type=retrieved.source_type or item.candidate.source_type or "web",
            language=retrieved.language or item.query.language,
            content_type=retrieved.content_type,
            query_refs=delta.query_refs,
            research_question_refs=delta.research_question_refs,
            information_need_refs=delta.information_need_refs,
            workflow_run_refs=(workflow_run_id,),
            research_design_refs=(research_design_id,),
            retrieval_status=retrieved.retrieval_status,
            content_text=content_text,
            content_checksum=checksum,
            metadata=metadata,
        )

    @staticmethod
    def _checksum(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
