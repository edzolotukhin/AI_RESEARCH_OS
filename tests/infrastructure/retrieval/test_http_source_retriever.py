from __future__ import annotations

import hashlib
import sys
import unittest
from unittest.mock import Mock, patch
import httpx
from reportlab.pdfgen import canvas
from io import BytesIO

from domain.sources.source_candidate import SourceCandidate

from domain.sources.retrieval_status import RetrievalStatus
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever
from infrastructure.retrieval.bounded_pdf_text_extractor import PdfTextResult, PDF_EXTRACTION_REVISION


def _pdf_bytes() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    document.drawString(40, 760, "Population 2020: 100 persons")
    document.showPage()
    document.save()
    return output.getvalue()


class HttpSourceRetrieverTests(unittest.TestCase):
    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    def test_safe_http_status_classes_and_success(self, _resolve) -> None:
        candidate = SourceCandidate("test", "https://example.com/report", "Report", "", "sq-1", 1)
        for status, expected in ((403, "4xx"), (503, "5xx"), (200, "none")):
            with self.subTest(status=status):
                client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
                    status, text="safe body", headers={"content-type": "text/plain"},
                )))
                with client:
                    source = HttpSourceRetriever(http_client=client).retrieve(candidate)
                diagnostic = source.metadata["retrieval_diagnostic"]
                self.assertEqual(diagnostic["http_status_class"], expected)
                self.assertEqual(diagnostic["stage"], "fetch" if status >= 400 else "success")
                self.assertEqual(diagnostic["failure_category"], "http_error" if status >= 400 else "none")

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    def test_safe_size_and_exception_diagnostics(self, _resolve) -> None:
        candidate = SourceCandidate("test", "https://example.com/report", "Report", "", "sq-1", 1,
                                    metadata={"navigation_max_bytes": "4"})
        client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="oversized")))
        with client:
            source = HttpSourceRetriever(http_client=client).retrieve(candidate)
        self.assertEqual(source.metadata["retrieval_diagnostic"]["limit_code"], "byte_budget_exhausted")
        client = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("SECRET https://private.example"))))
        with client:
            source = HttpSourceRetriever(http_client=client).retrieve(candidate)
        self.assertEqual(source.metadata["retrieval_diagnostic"]["exception_class"], "ConnectError")
        self.assertNotIn("SECRET", str(source.metadata["retrieval_diagnostic"]))

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
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_malformed_pdf_fails_without_parser_exception(self, parse_pdf, _validate) -> None:
        parse_pdf.return_value = PdfTextResult(error_code="pdf_malformed")
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
        self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(source.metadata.get("failure_category"), "other_retrieval_error")
        self.assertEqual(source.metadata["reason"], "pdf_malformed")

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_direct_pdf_checksum_revision_and_capability(self, parse_pdf, _resolve) -> None:
        parse_pdf.return_value = PdfTextResult("Population 2020: 100 persons", 1)
        body = _pdf_bytes()
        candidate = SourceCandidate("test", "https://example.com/report.pdf", "Report", "", "sq-1", 1)
        with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, content=body, headers={"content-type": "application/pdf"},
        ))) as client:
            retriever = HttpSourceRetriever(http_client=client)
            self.assertFalse(retriever.known_unsupported_url(candidate.url))
            source = retriever.retrieve(candidate)
        parse_pdf.assert_called_once_with(body)
        self.assertEqual(source.retrieval_status, RetrievalStatus.ACQUIRED)
        self.assertEqual(source.raw_content_checksum, hashlib.sha256(body).hexdigest())
        self.assertEqual(source.raw_checksum_kind, "sha256-bytes")
        self.assertEqual(source.content_checksum, hashlib.sha256(source.content_text.encode()).hexdigest())
        self.assertEqual(source.extraction_revision, PDF_EXTRACTION_REVISION)
        self.assertEqual(source.metadata["navigation_chain"], [candidate.url])
        self.assertEqual(source.metadata["retrieval_diagnostic"]["failure_category"], "none")

    @unittest.skipUnless(sys.platform == "linux" and sys.version_info[:2] == (3, 11),
                         "requires the production Linux Python 3.11 runtime")
    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    def test_actual_linux_pdf_retrieval_uses_bounded_child(self, _resolve) -> None:
        body = _pdf_bytes()
        with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, content=body, headers={"content-type": "application/pdf"},
        ))) as client:
            source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                "test", "https://example.com/report.pdf", "Report", "", "sq-1", 1,
                metadata={"required_resource_kind": "text"},
            ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.ACQUIRED)
        self.assertIn("Population 2020: 100 persons", source.content_text)
        self.assertEqual(source.raw_content_checksum, hashlib.sha256(body).hexdigest())

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_validated_redirect_to_extensionless_pdf(self, parse_pdf, _resolve) -> None:
        body = _pdf_bytes()
        parse_pdf.return_value = PdfTextResult("Population 2020: 100 persons", 1)
        def respond(request):
            if request.url.path == "/landing":
                return httpx.Response(302, headers={"location": "/file"})
            return httpx.Response(200, content=body, headers={"content-type": "application/pdf"})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                "test", "https://example.com/landing", "Report", "", "sq-1", 1,
            ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.ACQUIRED)
        self.assertEqual(source.metadata["navigation_chain"], ["https://example.com/landing", "https://example.com/file"])
        self.assertEqual(source.metadata["navigation_diagnostics"]["requests"], 2)

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_octet_stream_pdf_signature_is_accepted(self, parse_pdf, _resolve) -> None:
        parse_pdf.return_value = PdfTextResult("Population 2020: 100 persons", 1)
        with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, content=_pdf_bytes(), headers={"content-type": "application/octet-stream"},
        ))) as client:
            source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                "test", "https://example.com/download", "Report", "", "sq-1", 1,
            ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.ACQUIRED)
        self.assertEqual(source.content_type, "application/pdf")

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_pdf_redirect_to_private_address_never_reaches_parser(self, parse_pdf, _resolve) -> None:
        requested = []
        def respond(request):
            requested.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://127.0.0.1/report.pdf"})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                "test", "https://example.com/report.pdf", "Report", "", "sq-1", 1,
            ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(len(requested), 1)
        parse_pdf.assert_not_called()

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_pdf_navigation_byte_budget_remains_fail_closed(self, parse_pdf, _resolve) -> None:
        with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, content=_pdf_bytes(), headers={"content-type": "application/pdf"},
        ))) as client:
            source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                "test", "https://example.com/report.pdf", "Report", "", "sq-1", 1,
                metadata={"navigation_max_bytes": "100"},
            ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(source.metadata["retrieval_diagnostic"]["limit_code"], "byte_budget_exhausted")
        parse_pdf.assert_not_called()

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_pdf_mime_signature_and_size_fail_closed(self, parse_pdf, _resolve) -> None:
        candidate = SourceCandidate("test", "https://example.com/file", "Report", "", "sq-1", 1)
        cases = (
            (b"not a PDF", "application/pdf", "pdf_mime_mismatch"),
            (b"%PDF-1.4", "text/plain", "pdf_mime_mismatch"),
            (b"%PDF-1.4" + b"x" * 512_000, "application/pdf", "pdf_body_limit"),
        )
        for body, mime, expected in cases:
            with self.subTest(expected=expected, mime=mime):
                with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
                    200, content=body, headers={"content-type": mime},
                ))) as client:
                    source = HttpSourceRetriever(http_client=client).retrieve(candidate)
                self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
                self.assertEqual(source.metadata["reason"], expected)
                self.assertEqual(source.metadata["failure_category"], source.metadata["retrieval_diagnostic"]["failure_category"])
        parse_pdf.assert_not_called()

    @patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url")
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_pdf_declared_content_length_above_cap_fails_for_nonstreaming_client(self, parse_pdf, _validate) -> None:
        client = Mock()
        response = Mock()
        response.url = "https://example.com/report.pdf"
        response.status_code = 200
        response.headers = {"content-type": "application/pdf", "content-length": "9" * 5000}
        response.content = _pdf_bytes()
        client.get.return_value = response
        source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
            "test", "https://example.com/report.pdf", "Report", "", "sq-1", 1,
        ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(source.metadata["reason"], "pdf_body_limit")
        parse_pdf.assert_not_called()

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_streaming_pdf_uses_received_bytes_even_with_small_content_length(self, parse_pdf, _resolve) -> None:
        # The redirect fetcher removes transfer Content-Length after decoding.
        # The received byte count remains authoritative for the parser boundary.
        oversized = b"%PDF-" + b"x" * 512_000
        with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, content=oversized, headers={"content-type": "application/pdf", "content-length": "5"},
        ))) as client:
            source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                "test", "https://example.com/report.pdf", "Report", "", "sq-1", 1,
            ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(source.metadata["reason"], "pdf_body_limit")
        parse_pdf.assert_not_called()

    @patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"])
    @patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text")
    def test_pdf_table_need_without_structured_rows_fails(self, parse_pdf, _resolve) -> None:
        parse_pdf.return_value = PdfTextResult("2020 100 persons", 1)
        with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, content=_pdf_bytes(), headers={"content-type": "application/pdf"},
        ))) as client:
            source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                "test", "https://example.com/file.pdf", "Report", "", "sq-1", 1,
                metadata={"required_resource_kind": "table"},
            ))
        self.assertEqual(source.retrieval_status, RetrievalStatus.FAILED)
        self.assertEqual(source.metadata["reason"], "required_terminal_not_found")
        self.assertNotIn("structured_rows", source.metadata)

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
