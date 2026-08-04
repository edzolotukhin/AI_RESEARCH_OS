from __future__ import annotations

from domain.planning.research_design import InformationNeed, ResearchDesign
from domain.sources.search_query import SearchQuery

from application.sources.url_canonicalizer import normalize_query_text


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
        query_text = normalize_query_text(need.description)
        if need.geography:
            query_text = normalize_query_text(
                f"{query_text} {need.geography}",
            )
        if need.timeframe:
            query_text = normalize_query_text(
                f"{query_text} {need.timeframe}",
            )

        rationale_parts = [f"Derived from information need {need.id}"]
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
