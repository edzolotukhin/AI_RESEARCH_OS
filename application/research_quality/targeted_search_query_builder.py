from __future__ import annotations

from domain.planning.research_design import ResearchDesign
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.search_query import SearchQuery

from application.sources.expectation_aware_query_intent import (
    build_expectation_aware_query_text,
)
from application.sources.url_canonicalizer import normalize_query_text


class TargetedSearchQueryBuilder:
    """Build bounded search queries for one targeted InformationNeed gap."""

    def build_queries(
        self,
        *,
        design: ResearchDesign,
        request: TargetedResearchRequest,
        max_queries: int,
        max_results: int,
    ) -> list[SearchQuery]:
        if max_queries < 1:
            raise ValueError("max_queries must be at least 1.")

        need = next(
            (item for item in design.information_needs if item.id == request.information_need_id),
            None,
        )
        if need is None:
            raise ValueError(
                f"InformationNeed {request.information_need_id!r} not found in design",
            )
        if need.research_question_id != request.research_question_id:
            raise ValueError(
                "InformationNeed does not belong to the specified ResearchQuestion",
            )

        queries: list[SearchQuery] = []
        semantic_targets = request.missing_aspects or request.search_directives
        base_text = build_expectation_aware_query_text(
            description=need.description,
            geography=need.geography,
            timeframe=need.timeframe,
            semantic_targets=semantic_targets,
        )

        queries.append(
            SearchQuery(
                id=f"sq-target-{need.id}-a{request.attempt}-0",
                research_question_id=need.research_question_id,
                information_need_id=need.id,
                query_text=base_text,
                language=design.language,
                geography=need.geography,
                timeframe=need.timeframe,
                preferred_source_types=need.preferred_source_types,
                max_results=max_results,
                rationale=(
                    f"Targeted base query for information need {need.id} "
                    f"(attempt {request.attempt})"
                ),
            ),
        )

        for index, directive in enumerate(request.search_directives, start=1):
            if len(queries) >= max_queries:
                break
            directive_text = normalize_query_text(directive)
            if not directive_text:
                continue
            queries.append(
                SearchQuery(
                    id=f"sq-target-{need.id}-a{request.attempt}-{index}",
                    research_question_id=need.research_question_id,
                    information_need_id=need.id,
                    query_text=directive_text,
                    language=design.language,
                    geography=need.geography,
                    timeframe=need.timeframe,
                    preferred_source_types=need.preferred_source_types,
                    max_results=max_results,
                    rationale=(
                        f"Targeted directive query for information need {need.id} "
                        f"(attempt {request.attempt})"
                    ),
                ),
            )

        return queries[:max_queries]
