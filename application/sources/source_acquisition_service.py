from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
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
from application.sources.source_budget import SourceAcquisitionBudget
from application.sources.url_canonicalizer import canonicalize_url

from runtime.workflow_context import WorkflowContext

logger = logging.getLogger("ai_research_os.sources")

_MAX_PROVENANCE_RETRIES = 5


@dataclass(frozen=True)
class SourceAcquisitionSummary:
    source_ids: tuple[str, ...]
    queries_executed: int
    candidates_found: int
    sources_acquired: int
    retrieval_failures: int
    tavily_query_count: int = 0
    candidate_count_raw: int = 0
    candidate_count_unique: int = 0
    candidates_attempted: int = 0
    acquired_count: int = 0
    truncated_count: int = 0
    failed_count: int = 0
    skipped_duplicate_count: int = 0
    skipped_budget_count: int = 0
    elapsed_seconds: float = 0.0
    budget_exhausted: bool = False
    coverage_target_satisfied: bool = False
    coverage_complete_early_stop: bool = False
    information_needs_covered_count: int = 0
    information_needs_total: int = 0
    failure_category_counts: dict[str, int] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tavily_query_count == 0 and self.queries_executed:
            object.__setattr__(self, "tavily_query_count", self.queries_executed)
        if self.candidate_count_raw == 0 and self.candidates_found:
            object.__setattr__(self, "candidate_count_raw", self.candidates_found)
        if self.acquired_count == 0 and self.sources_acquired:
            object.__setattr__(self, "acquired_count", self.sources_acquired)
        if self.failed_count == 0 and self.retrieval_failures:
            object.__setattr__(self, "failed_count", self.retrieval_failures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ids": list(self.source_ids),
            "queries_executed": self.queries_executed,
            "candidates_found": self.candidates_found,
            "sources_acquired": self.sources_acquired,
            "retrieval_failures": self.retrieval_failures,
            "tavily_query_count": self.tavily_query_count,
            "candidate_count_raw": self.candidate_count_raw,
            "candidate_count_unique": self.candidate_count_unique,
            "candidates_attempted": self.candidates_attempted,
            "acquired_count": self.acquired_count,
            "truncated_count": self.truncated_count,
            "failed_count": self.failed_count,
            "skipped_duplicate_count": self.skipped_duplicate_count,
            "skipped_budget_count": self.skipped_budget_count,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "budget_exhausted": self.budget_exhausted,
            "coverage_target_satisfied": self.coverage_target_satisfied,
            "coverage_complete_early_stop": self.coverage_complete_early_stop,
            "information_needs_covered_count": self.information_needs_covered_count,
            "information_needs_total": self.information_needs_total,
            "failure_category_counts": dict(self.failure_category_counts),
            "limitations": list(self.limitations),
        }


@dataclass
class _PendingCandidate:
    candidate: SourceCandidate
    query: SearchQuery
    canonical_url: str


@dataclass
class _CandidateGroup:
    canonical_url: str
    items: list[_PendingCandidate]

    @property
    def best_rank(self) -> int:
        return min(item.candidate.rank for item in self.items)

    @property
    def need_coverage(self) -> int:
        return len({item.query.information_need_id for item in self.items})


class SourceAcquisitionService:
    """Orchestrates search, deduplication, retrieval, and source persistence."""

    def __init__(
        self,
        *,
        search_provider: SearchProvider,
        source_retriever: SourceRetriever,
        source_repository: SourceRepository,
        query_builder: SearchQueryBuilder | None = None,
        budget: SourceAcquisitionBudget | None = None,
    ) -> None:
        self._search_provider = search_provider
        self._source_retriever = source_retriever
        self._source_repository = source_repository
        self._budget = budget or SourceAcquisitionBudget()
        self._query_builder = query_builder or SearchQueryBuilder(
            max_results=self._budget.max_candidates_per_query,
        )

    def acquire_for_context(self, context: WorkflowContext) -> SourceAcquisitionSummary:
        started = time.monotonic()
        design = self._resolve_design(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id
        queries = self._query_builder.build_queries(design)

        raw_count, grouped = self._collect_candidates(queries)
        prioritized = self._prioritize_groups(grouped)
        unique_count = len(prioritized)

        (
            source_ids,
            acquired,
            failures,
            truncated,
            attempted,
            skipped_duplicate,
            skipped_budget,
            failure_categories,
            budget_exhausted,
            coverage_target_satisfied,
            coverage_complete_early_stop,
            covered_needs,
        ) = self._acquire_candidates(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
            design=design,
            groups=prioritized,
            started_at=started,
        )

        elapsed = time.monotonic() - started
        limitations = self._build_limitations(
            design=design,
            covered_needs=covered_needs,
            budget_exhausted=budget_exhausted,
            skipped_budget=skipped_budget,
            unique_count=unique_count,
            acquired=acquired,
            coverage_target_satisfied=coverage_target_satisfied,
            coverage_complete_early_stop=coverage_complete_early_stop,
        )

        summary = SourceAcquisitionSummary(
            source_ids=tuple(source_ids),
            queries_executed=len(queries),
            candidates_found=raw_count,
            sources_acquired=acquired,
            retrieval_failures=failures,
            tavily_query_count=len(queries),
            candidate_count_raw=raw_count,
            candidate_count_unique=unique_count,
            candidates_attempted=attempted,
            acquired_count=acquired,
            truncated_count=truncated,
            failed_count=failures,
            skipped_duplicate_count=skipped_duplicate,
            skipped_budget_count=skipped_budget,
            elapsed_seconds=elapsed,
            budget_exhausted=budget_exhausted,
            coverage_target_satisfied=coverage_target_satisfied,
            coverage_complete_early_stop=coverage_complete_early_stop,
            information_needs_covered_count=len(covered_needs),
            information_needs_total=len(design.information_needs),
            failure_category_counts=dict(failure_categories),
            limitations=tuple(limitations),
        )

        logger.info(
            "source_acquisition_summary",
            extra={
                "event": "source_acquisition_summary",
                **summary.to_dict(),
            },
        )

        if acquired == 0:
            raise SourceAcquisitionError(
                "No sources were successfully acquired for project "
                f"{project_id}",
            )
        if acquired < self._budget.min_successful_sources:
            raise SourceAcquisitionError(
                "Source acquisition acquired "
                f"{acquired} source(s), below minimum "
                f"{self._budget.min_successful_sources} for project {project_id}",
            )

        return summary

    def acquire_targeted_queries(
        self,
        context: WorkflowContext,
        queries: list[SearchQuery],
        *,
        max_sources: int,
    ) -> SourceAcquisitionSummary:
        """Bounded targeted acquisition for one gap; zero sources is not a failure."""
        if not queries:
            return SourceAcquisitionSummary(
                source_ids=(),
                queries_executed=0,
                candidates_found=0,
                sources_acquired=0,
                retrieval_failures=0,
            )
        if max_sources < 1:
            raise ValueError("max_sources must be at least 1.")

        started = time.monotonic()
        design = self._resolve_design(context)
        project_id = context.project.id
        workflow_run_id = context.workflow_run.id

        raw_count, grouped = self._collect_candidates(queries)
        prioritized = self._prioritize_groups(grouped)[:max_sources]
        unique_count = len(prioritized)

        (
            source_ids,
            acquired,
            failures,
            truncated,
            attempted,
            skipped_duplicate,
            skipped_budget,
            failure_categories,
            budget_exhausted,
            coverage_target_satisfied,
            coverage_complete_early_stop,
            covered_needs,
        ) = self._acquire_candidates(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            research_design_id=design.id,
            design=design,
            groups=prioritized,
            started_at=started,
            max_source_groups=max_sources,
        )

        elapsed = time.monotonic() - started
        return SourceAcquisitionSummary(
            source_ids=tuple(source_ids),
            queries_executed=len(queries),
            candidates_found=raw_count,
            sources_acquired=acquired,
            retrieval_failures=failures,
            tavily_query_count=len(queries),
            candidate_count_raw=raw_count,
            candidate_count_unique=unique_count,
            candidates_attempted=attempted,
            acquired_count=acquired,
            truncated_count=truncated,
            failed_count=failures,
            skipped_duplicate_count=skipped_duplicate,
            skipped_budget_count=skipped_budget,
            elapsed_seconds=elapsed,
            budget_exhausted=budget_exhausted,
            coverage_target_satisfied=coverage_target_satisfied,
            coverage_complete_early_stop=coverage_complete_early_stop,
            information_needs_covered_count=len(covered_needs),
            information_needs_total=len(design.information_needs),
            failure_category_counts=dict(failure_categories),
            limitations=(),
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
    ) -> tuple[int, dict[str, list[_PendingCandidate]]]:
        grouped: dict[str, list[_PendingCandidate]] = {}
        raw_count = 0

        for query in queries:
            candidates = self._search_provider.search(query)
            raw_count += len(candidates)
            for candidate in candidates[: self._budget.max_candidates_per_information_need]:
                if not _is_supported_scheme(candidate.url):
                    continue
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
        return raw_count, grouped

    @staticmethod
    def _prioritize_groups(
        grouped: dict[str, list[_PendingCandidate]],
    ) -> list[_CandidateGroup]:
        groups = [
            _CandidateGroup(canonical_url=canonical, items=items)
            for canonical, items in grouped.items()
        ]
        groups.sort(
            key=lambda group: (
                -group.need_coverage,
                group.best_rank,
                group.canonical_url,
            ),
        )
        return groups

    def _acquire_candidates(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        design: ResearchDesign,
        groups: list[_CandidateGroup],
        started_at: float,
        max_source_groups: int | None = None,
    ) -> tuple[
        list[str],
        int,
        int,
        int,
        int,
        int,
        int,
        Counter[str],
        bool,
        bool,
        bool,
        set[str],
    ]:
        source_ids: list[str] = []
        acquired = 0
        failures = 0
        truncated = 0
        attempted = 0
        skipped_duplicate = 0
        skipped_budget = 0
        failure_categories: Counter[str] = Counter()
        budget_exhausted = False
        coverage_complete_early_stop = False
        covered_needs: set[str] = set()
        covered_questions: set[str] = set()
        source_group_limit = max_source_groups or self._budget.max_sources_per_run

        for index, group in enumerate(groups):
            if index >= source_group_limit:
                skipped_budget += 1
                continue

            if self._budget_remaining(started_at) <= 0:
                budget_exhausted = True
                skipped_budget += len(groups) - index
                break

            resolved, was_project_duplicate, did_fetch = self._resolve_source_for_group(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                research_design_id=research_design_id,
                items=group.items,
            )
            if was_project_duplicate:
                skipped_duplicate += 1
            if did_fetch:
                attempted += 1

            source_ids.append(resolved.id)
            if is_successful_acquisition(resolved.retrieval_status):
                acquired += 1
                if resolved.retrieval_status == RetrievalStatus.TRUNCATED:
                    truncated += 1
            elif resolved.retrieval_status in {
                RetrievalStatus.FAILED,
                RetrievalStatus.UNSUPPORTED,
            }:
                failures += 1
                category = _failure_category(resolved)
                if category:
                    failure_categories[category] += 1

            _update_coverage_from_source(
                resolved,
                covered_needs,
                covered_questions,
            )
            if (
                self._coverage_target_satisfied(
                    design,
                    covered_needs,
                    covered_questions,
                )
                and acquired >= self._budget.min_successful_sources
            ):
                coverage_complete_early_stop = True
                skipped_budget += len(groups) - index - 1
                break

        if not budget_exhausted and self._budget_remaining(started_at) <= 0:
            budget_exhausted = True

        coverage_target_satisfied = self._coverage_target_satisfied(
            design,
            covered_needs,
            covered_questions,
        )

        return (
            source_ids,
            acquired,
            failures,
            truncated,
            attempted,
            skipped_duplicate,
            skipped_budget,
            failure_categories,
            budget_exhausted,
            coverage_target_satisfied,
            coverage_complete_early_stop,
            covered_needs,
        )

    def _budget_remaining(self, started_at: float) -> float:
        elapsed = time.monotonic() - started_at
        return self._budget.acquisition_max_seconds - elapsed

    def _resolve_source_for_group(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        research_design_id: str,
        items: list[_PendingCandidate],
    ) -> tuple[Source, bool, bool]:
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
            merged = self._merge_existing_source(existing, delta, incoming=None)
            return merged, True, False

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
                return incoming, False, True
            except DuplicateSourceError:
                existing = self._source_repository.get_by_canonical_url_for_project(
                    project_id,
                    primary.canonical_url,
                )
                if existing is None:
                    continue
                merged = self._merge_existing_source(existing, delta, incoming=incoming)
                return merged, True, True

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

    def _coverage_target_satisfied(
        self,
        design: ResearchDesign,
        covered_needs: set[str],
        covered_questions: set[str],
    ) -> bool:
        all_needs = {need.id for need in design.information_needs}
        if not all_needs:
            return True

        covered = covered_needs & all_needs
        ratio = len(covered) / len(all_needs)
        target_ratio = self._budget.min_information_need_coverage_ratio

        if target_ratio >= 1.0:
            return covered >= all_needs

        all_questions = {question.id for question in design.research_questions}
        return ratio >= target_ratio and covered_questions >= all_questions

    def _build_limitations(
        self,
        *,
        design: ResearchDesign,
        covered_needs: set[str],
        budget_exhausted: bool,
        skipped_budget: int,
        unique_count: int,
        acquired: int,
        coverage_target_satisfied: bool,
        coverage_complete_early_stop: bool,
    ) -> list[str]:
        limitations: list[str] = []
        if coverage_complete_early_stop:
            limitations.append(
                "Source acquisition stopped early because the coverage target was satisfied",
            )
        if budget_exhausted:
            limitations.append(
                "Source acquisition stopped because the wall-clock budget was exhausted",
            )
        if skipped_budget > 0 and not coverage_complete_early_stop:
            limitations.append(
                f"{skipped_budget} candidate URL(s) were not attempted due to "
                "run-level source budget limits",
            )
        elif skipped_budget > 0 and coverage_complete_early_stop:
            limitations.append(
                f"{skipped_budget} candidate URL(s) were not attempted after "
                "coverage target satisfaction",
            )
        if unique_count > self._budget.max_sources_per_run:
            limitations.append(
                f"Unique candidate URLs ({unique_count}) exceeded the per-run cap "
                f"({self._budget.max_sources_per_run})",
            )

        all_needs = {need.id for need in design.information_needs}
        missing_needs = sorted(all_needs - covered_needs)
        if missing_needs and acquired >= self._budget.min_successful_sources:
            if budget_exhausted or skipped_budget > 0:
                limitations.append(
                    "Information need coverage incomplete after budget exhaustion: "
                    + ", ".join(missing_needs),
                )
            elif not coverage_target_satisfied:
                limitations.append(
                    "No successfully acquired source covers information need(s): "
                    + ", ".join(missing_needs),
                )
        return limitations

    @staticmethod
    def _checksum(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _update_coverage_from_source(
    source: Source,
    covered_needs: set[str],
    covered_questions: set[str],
) -> None:
    if not is_successful_acquisition(source.retrieval_status):
        return
    covered_needs.update(source.information_need_refs)
    covered_questions.update(source.research_question_refs)


def _is_supported_scheme(url: str) -> bool:
    scheme = (urlparse(url.strip()).scheme or "").lower()
    return scheme in {"http", "https"}


def _failure_category(source: Source) -> str | None:
    metadata = source.metadata or {}
    category = metadata.get("failure_category")
    if isinstance(category, str) and category:
        return category
    return "other_retrieval_error"
