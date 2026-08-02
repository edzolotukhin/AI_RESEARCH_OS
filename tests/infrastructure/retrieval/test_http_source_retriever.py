from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from domain.sources.source_candidate import SourceCandidate

from domain.sources.retrieval_status import RetrievalStatus
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever


class HttpSourceRetrieverTests(unittest.TestCase):
    @patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url")
    def test_extracts_html_text(self, _validate) -> None:
        client = Mock()
        response = Mock()
        response.url = "https://example.com/report"
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.content = (
            b"<html><body><script>x</script><p>Hello world</p></body></html>"
        )
        client.get.return_value = response
        retriever = HttpSourceRetriever(http_client=client)
        source = retriever.retrieve(
            SourceCandidate(
                provider="test",
                url="https://example.com/report",
                title="Report",
                snippet="",
                query_id="sq-1",
                rank=1,
            ),
        )
        self.assertEqual(source.retrieval_status, RetrievalStatus.ACQUIRED)
        self.assertIn("Hello world", source.content_text)

    @patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url")
    def test_marks_unsupported_pdf(self, _validate) -> None:
        client = Mock()
        response = Mock()
        response.url = "https://example.com/report.pdf"
        response.headers = {"content-type": "application/pdf"}
        response.content = b"%PDF-1.4"
        client.get.return_value = response
        retriever = HttpSourceRetriever(http_client=client)
        source = retriever.retrieve(
            SourceCandidate(
                provider="test",
                url="https://example.com/report.pdf",
                title="PDF",
                snippet="",
                query_id="sq-1",
                rank=1,
            ),
        )
        self.assertEqual(source.retrieval_status, RetrievalStatus.UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
