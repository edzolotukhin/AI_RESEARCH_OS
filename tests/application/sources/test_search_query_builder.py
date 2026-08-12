from __future__ import annotations

import unittest

from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion

from application.sources.search_query_builder import SearchQueryBuilder


class SearchQueryBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = SearchQueryBuilder()
        self.design = ResearchDesign(
            id="design-1",
            research_questions=(
                ResearchQuestion(
                    id="rq-1",
                    question="What is brand awareness?",
                    objective_refs=("Evaluate brand awareness.",),
                ),
            ),
            information_needs=(
                InformationNeed(
                    id="in-1",
                    research_question_id="rq-1",
                    description="Published brand tracking statistics",
                    preferred_source_types=("official statistics",),
                    timeframe="2024-2026",
                    geography="Germany",
                ),
            ),
            language="en",
        )

    def test_builds_traceable_query(self) -> None:
        queries = self.builder.build_queries(self.design)
        self.assertEqual(len(queries), 1)
        query = queries[0]
        self.assertEqual(query.id, "sq-in-1")
        self.assertEqual(query.research_question_id, "rq-1")
        self.assertEqual(query.information_need_id, "in-1")
        self.assertIn("brand awareness", query.query_text)
        self.assertIn("brand tracking", query.query_text)
        self.assertIn("Germany", query.query_text)
        self.assertIn("2024-2026", query.query_text)
        self.assertEqual(query.preferred_source_types, ("official statistics",))
        self.assertEqual(query.language, "en")
        self.assertNotIn("tavily", query.to_dict())

    def test_rejects_empty_query_text(self) -> None:
        design = ResearchDesign(
            id="design-2",
            research_questions=(
                ResearchQuestion(id="rq-1", question="   ", objective_refs=()),
            ),
            information_needs=(
                InformationNeed(
                    id="in-empty",
                    research_question_id="rq-1",
                    description="   ",
                ),
            ),
        )
        with self.assertRaises(ValueError):
            self.builder.build_queries(design)


if __name__ == "__main__":
    unittest.main()
