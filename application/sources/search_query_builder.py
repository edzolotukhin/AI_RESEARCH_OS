from __future__ import annotations

from domain.planning.research_design import InformationNeed, ResearchDesign
from domain.sources.search_query import SearchQuery

from application.sources.expectation_aware_query_intent import (
    build_expectation_aware_query_text,
)


class SearchQueryBuilder:
    """Deterministically derive SearchQuery records from a ResearchDesign."""

    def __init__(self, *, max_results: int = 5) -> None:
        self._max_results = max_results

    def build_queries(self, design: ResearchDesign) -> list[SearchQuery]:
        if not design.information_needs:
            raise ValueError(
                "ResearchDesign must contain at least one information need "
                "to generate search queries",
            )

        question_ids = {question.id for question in design.research_questions}
        queries: list[SearchQuery] = []

        for need in design.information_needs:
            self._validate_need(need, question_ids)
            queries.append(self._build_query(design, need))

        return queries

    def _validate_need(
        self,
        need: InformationNeed,
        question_ids: set[str],
    ) -> None:
        if need.research_question_id not in question_ids:
            raise ValueError(
                f"InformationNeed {need.id!r} references unknown research question "
                f"{need.research_question_id!r}",
            )

    def _build_query(
        self,
        design: ResearchDesign,
        need: InformationNeed,
    ) -> SearchQuery:
        # Parity with TargetedSearchQueryBuilder: parent RQ text anchors the
        # category/subject so a generic InformationNeed cannot drop Brief topic.
        question = next(
            (
                item
                for item in design.research_questions
                if item.id == need.research_question_id
            ),
            None,
        )
        subject_context = question.question if question is not None else ""
        semantic_targets: tuple[str, ...] = ()
        if need.evidence_expectation is not None:
            semantic_targets = need.evidence_expectation.required_aspects
        query_text = build_expectation_aware_query_text(
            subject_context=subject_context,
            description=need.description,
            geography=need.geography,
            timeframe=need.timeframe,
            semantic_targets=semantic_targets,
        )

        rationale_parts = [f"Derived from information need {need.id}"]
        if subject_context:
            rationale_parts.append("subject_context=parent_research_question")
        if need.geography:
            rationale_parts.append(f"geography={need.geography}")
        if need.timeframe:
            rationale_parts.append(f"timeframe={need.timeframe}")

        return SearchQuery(
            id=f"sq-{need.id}",
            research_question_id=need.research_question_id,
            information_need_id=need.id,
            query_text=query_text,
            language=design.language,
            geography=need.geography,
            timeframe=need.timeframe,
            preferred_source_types=need.preferred_source_types,
            max_results=self._max_results,
            rationale="; ".join(rationale_parts),
        )
