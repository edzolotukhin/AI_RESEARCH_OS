"""The positive integration fixture must satisfy dated-brief source preconditions."""

import unittest

from domain.sources.source_candidate import SourceCandidate
from tests.helpers.dated_desk_integration_fixture import (
    DatedDeskSourceRetriever,
)


class DatedDeskIntegrationFixtureTests(unittest.TestCase):
    def test_sources_are_distinct_and_ground_the_observation_date(self) -> None:
        retriever = DatedDeskSourceRetriever()
        urls = (
            "https://example.com/market-report?utm_source=test",
            "https://research.example.org/brand-health",
            "https://research.example.org/industry-trends",
        )
        contents = []
        for index, url in enumerate(urls):
            source = retriever.retrieve(SourceCandidate(
                provider="deterministic",
                provider_result_id=str(index),
                url=url,
                title="Synthetic brand awareness source",
                snippet="Synthetic observation",
                source_type="web",
                rank=index + 1,
                query_id="synthetic-query",
            ))
            self.assertIn("As of 2026-06-30, measured", source.content_text)
            self.assertIn("Purina brand awareness", source.content_text)
            contents.append(source.content_text)
        self.assertEqual(len(set(contents)), len(urls))


if __name__ == "__main__":
    unittest.main()
