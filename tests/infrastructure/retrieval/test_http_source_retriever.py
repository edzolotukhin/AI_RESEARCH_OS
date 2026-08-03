from __future__ import annotations

import hashlib
import unittest
from unittest.mock import Mock, patch

from domain.sources.source_candidate import SourceCandidate

from domain.sources.retrieval_status import RetrievalStatus
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever


class HttpSourceRetrieverTests(unittest.TestCase):
    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses")
    def test_extracts_html_text(self, resolve_addresses) -> None:
        resolve_addresses.return_value = ["93.184.216.34"]
        client = Mock()
        response = Mock()
        response.url = "https://example.com/report"
        response.status_code = 200
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
        self.assertTrue(source.content_checksum)
        self.assertEqual(
            source.content_checksum,
            hashlib.sha256(source.content_text.encode("utf-8")).hexdigest(),
        )

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses")
    def test_public_https_url_passes_validation_and_acquires_content(
        self,
        resolve_addresses,
    ) -> None:
        resolve_addresses.return_value = ["93.184.216.34"]
        client = Mock()
        response = Mock()
        response.url = "https://wise.com/ru/cost-of-living/serbia"
        response.status_code = 200
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.content = b"<html><body><p>Serbia market overview</p></body></html>"
        client.get.return_value = response

        source = HttpSourceRetriever(http_client=client).retrieve(
            SourceCandidate(
                provider="tavily",
                url="https://wise.com/ru/cost-of-living/serbia",
                title="Wise report",
                snippet="",
                query_id="sq-1",
                rank=1,
            ),
        )

        self.assertEqual(source.retrieval_status, RetrievalStatus.ACQUIRED)
        self.assertIn("Serbia market overview", source.content_text)
        self.assertTrue(source.content_checksum)
        client.get.assert_called_once()

    @patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url")
    def test_marks_unsupported_pdf(self, _validate) -> None:
        client = Mock()
        response = Mock()
        response.url = "https://example.com/report.pdf"
        response.status_code = 200
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
        self.assertEqual(
            source.metadata.get("failure_category"),
            "unsupported_content_type",
        )

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses")
    def test_dns_failure_records_category(self, resolve_addresses) -> None:
        resolve_addresses.return_value = []
        retriever = HttpSourceRetriever(http_client=Mock())
        source = retriever.retrieve(
            SourceCandidate(
                provider="test",
                url="https://missing.example/report",
                title="Missing",
                snippet="",
                query_id="sq-1",
                rank=1,
            ),
        )
        self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(source.metadata.get("failure_category"), "dns_resolution_failed")
        self.assertIn("Unable to resolve host", source.metadata.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
