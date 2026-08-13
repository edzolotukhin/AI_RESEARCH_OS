from __future__ import annotations

from domain.planning.research_design import ResearchDesign
from domain.research_brief import ResearchBrief
from domain.research_quality.targeted_research_request import TargetedResearchRequest
from domain.sources.search_query import SearchQuery

from application.sources.expectation_aware_query_intent import (
    build_expectation_aware_query_text,
)
from application.sources.category_subject import resolve_category_subject
from application.sources.url_canonicalizer import normalize_query_text

SEMANTIC_TARGET_MISSING_ASPECTS = "missing_aspects"
SEMANTIC_TARGET_EE_FALLBACK = "EE_fallback"
SEMANTIC_TARGET_LEGACY_DIRECTIVES = "legacy_directives"


class TargetedSearchQueryBuilder:
    """Build bounded search queries for one targeted InformationNeed gap."""

    def build_queries(
        self,
        *,
        design: ResearchDesign,
        request: TargetedResearchRequest,
        max_queries: int,
        max_results: int,
        brief: ResearchBrief | None = None,
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

        question = next(
            (
                item
                for item in design.research_questions
                if item.id == need.research_question_id
            ),
            None,
        )
        subject_context = question.question if question is not None else ""
        category = resolve_category_subject(brief=brief, design=design)
        semantic_targets, target_source = self._resolve_semantic_targets(
            need=need,
            request=request,
        )
        base_text = build_expectation_aware_query_text(
            subject_context=subject_context,
            category_context=category.text if category is not None else "",
            description=need.description,
            geography=need.geography,
            timeframe=need.timeframe,
            semantic_targets=semantic_targets,
        )

        queries: list[SearchQuery] = [
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
                    f"(attempt {request.attempt}); "
                    f"semantic_target_source={target_source}"
                ),
            ),
        ]

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
                    query_text=build_expectation_aware_query_text(
                        subject_context=subject_context,
                        category_context=category.text if category is not None else "",
                        description=directive_text,
                        geography=need.geography,
                        timeframe=need.timeframe,
                    ),
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

    @staticmethod
    def _resolve_semantic_targets(
        *,
        need,
        request: TargetedResearchRequest,
    ) -> tuple[tuple[str, ...], str]:
        """Resolve targeted semantic targets without inventing EE aspects."""
        if need.evidence_expectation is not None:
            if request.missing_aspects:
                return tuple(request.missing_aspects), SEMANTIC_TARGET_MISSING_ASPECTS
            return (
                tuple(need.evidence_expectation.required_aspects),
                SEMANTIC_TARGET_EE_FALLBACK,
            )
        if request.missing_aspects:
            return tuple(request.missing_aspects), SEMANTIC_TARGET_LEGACY_DIRECTIVES
        return tuple(request.search_directives), SEMANTIC_TARGET_LEGACY_DIRECTIVES
