from dataclasses import replace
import io
import unittest
from unittest.mock import patch
import httpx
from openpyxl import Workbook
from application.sources.acquisition_capability import decide_acquisition, TABLE_EXTRACTION_CAPABILITY
from application.sources.source_acquisition_service import _failure_category, _safe_attempt_diagnostics
from infrastructure.retrieval.bounded_pdf_text_extractor import PdfTextResult
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.sources.source import Source
from domain.sources.source_candidate import SourceCandidate
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever


def workbook(value=950):
    book = Workbook()
    book.active.append(["Year", "Population"])
    book.active.append([2020, value])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def candidate(**metadata):
    return SourceCandidate("fixture", "https://example.org/landing", "Population", "", "q", 1,
        metadata={"navigation_enabled":"1", "required_resource_kind":"table", **metadata})


class CapabilityNavigationTests(unittest.TestCase):
    def retrieve(self, handler, **metadata):
        with patch("infrastructure.retrieval.network_safety._default_resolve_host_addresses", return_value=["93.184.216.34"]):
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                return HttpSourceRetriever(http_client=client).retrieve(candidate(**metadata))

    def test_irrelevant_html_does_not_hide_extensionless_xlsx(self):
        def handler(request):
            path = request.url.path
            if path == "/landing":
                return httpx.Response(200,text='<a href="/aaa-resource">resource data</a><a href="/resource">resource data</a>',headers={"content-type":"text/html"})
            if path == "/aaa-resource":
                return httpx.Response(200,text="Descriptive prose",headers={"content-type":"text/html"})
            if path == "/resource":
                return httpx.Response(200,text='<p>XLSX</p><a href="/download/123">Download</a>',headers={"content-type":"text/html"})
            return httpx.Response(200,content=workbook(),headers={"content-type":"application/octet-stream"})
        source = self.retrieve(handler)
        self.assertTrue(source.metadata["structured_rows"])
        self.assertEqual(source.url,"https://example.org/download/123")
        self.assertEqual(source.metadata["navigation_chain"],["https://example.org/landing","https://example.org/resource","https://example.org/download/123"])
        self.assertEqual(source.metadata["navigation_diagnostics"]["requests"],4)
        self.assertTrue(any(e.get("decision")=="rejected" for e in source.metadata["navigation_diagnostics"]["events"]))

    def test_redirects_share_request_budget(self):
        calls=[]
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302,headers={"location":"/next"+str(len(calls))})
        source=self.retrieve(handler,navigation_max_requests="2")
        self.assertEqual(len(calls),2)
        self.assertEqual(source.metadata["navigation_diagnostics"]["stop_reason"],"request_budget_exhausted")

    def test_aggregate_byte_limit(self):
        source=self.retrieve(lambda r:httpx.Response(200,content=b"x"*100,headers={"content-type":"text/html"}),navigation_max_bytes="50")
        self.assertEqual(source.retrieval_status.value,"failed")
        self.assertEqual(source.metadata["navigation_diagnostics"]["stop_reason"],"byte_budget_exhausted")
        self.assertEqual(source.metadata["failure_category"],"content_too_large")

    def test_child_redirect_loop_continues_to_next_xlsx(self):
        calls=[]
        def handler(request):
            calls.append(request.url.path)
            if request.url.path == "/landing":
                return httpx.Response(200,text='<a href="/a-loop">Download table</a><a href="/b-data.xlsx">Download table</a>',headers={"content-type":"text/html"})
            if request.url.path == "/a-loop":
                return httpx.Response(302,headers={"location":"/landing"})
            if request.url.path == "/b-data.xlsx":
                return httpx.Response(200,content=workbook(),headers={"content-type":"application/octet-stream"})
            self.fail("unexpected request")
        source=self.retrieve(handler)
        self.assertEqual(source.retrieval_status.value,"acquired")
        self.assertEqual(source.url,"https://example.org/b-data.xlsx")
        self.assertEqual(calls,["/landing","/a-loop","/b-data.xlsx"])
        self.assertTrue(source.metadata["structured_rows"])
        events=source.metadata["navigation_diagnostics"]["events"]
        self.assertTrue(any(event.get("reason")=="url_already_visited" for event in events))

    def test_root_redirect_loop_is_failed_without_repeat_request(self):
        calls=[]
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(302,headers={"location":"/landing"})
        source=self.retrieve(handler)
        self.assertEqual(calls,["/landing"])
        self.assertEqual(source.retrieval_status.value,"failed")
        self.assertEqual(source.metadata["failure_category"],"other_retrieval_error")
        self.assertEqual(source.metadata["retrieval_diagnostic"]["failure_category"],"other_retrieval_error")
        self.assertEqual(source.metadata["retrieval_diagnostic"]["limit_code"],"url_already_visited")
        self.assertEqual(source.metadata["navigation_diagnostics"]["requests"],1)

    def test_table_html_without_structured_rows_remains_failed_with_category(self):
        source=self.retrieve(lambda r:httpx.Response(200,text='<table><tr><td>2020</td><td>950</td></tr></table>',headers={"content-type":"text/html"}))
        self.assertEqual(source.retrieval_status.value,"failed")
        self.assertEqual(source.metadata["reason"],"required_terminal_not_found")
        self.assertEqual(source.metadata["retrieval_diagnostic"]["terminal_reason"], "required_terminal_not_found")
        self.assertEqual(source.metadata["failure_category"],"other_retrieval_error")
        self.assertEqual(source.metadata["retrieval_diagnostic"]["failure_category"],"other_retrieval_error")
        design=ResearchDesign(id="diagnostic-design",research_questions=(ResearchQuestion("rq","Population"),),
            information_needs=(InformationNeed("need","rq","Population"),))
        category=_failure_category(source)
        records,truncated=_safe_attempt_diagnostics([{"action":"fetch_failed","information_need_id":"need",
            "retrieval_diagnostic":source.metadata["retrieval_diagnostic"]}],design)
        self.assertEqual(category,"other_retrieval_error")
        self.assertEqual(records[0]["failure_category"],category)
        self.assertEqual(records[0]["terminal_reason"], "required_terminal_not_found")
        self.assertFalse(truncated)

    def test_pdf_failure_safe_projection_omits_source_and_payload(self):
        with patch("infrastructure.retrieval.http_source_retriever.extract_pdf_text",
                   return_value=PdfTextResult(error_code="pdf_encrypted")):
            source=self.retrieve(lambda r:httpx.Response(200,content=b"%PDF-1.4",headers={"content-type":"application/pdf"}),required_resource_kind="text")
        design=ResearchDesign(id="diagnostic-design",research_questions=(ResearchQuestion("rq","Population"),),
            information_needs=(InformationNeed("need","rq","Population"),))
        records,truncated=_safe_attempt_diagnostics([{
            "action":"fetch_failed","information_need_id":"need",
            "canonical_url":"https://private.example/secret.pdf","source_id":"source-secret",
            "provider_payload":"credential-secret","reason":source.metadata["reason"],
            "retrieval_diagnostic":source.metadata["retrieval_diagnostic"],
        }],design)
        self.assertEqual(source.metadata["failure_category"],"unsupported_content_type")
        self.assertEqual(records[0]["failure_category"],_failure_category(source))
        self.assertFalse(truncated)
        for secret in ("private.example","source-secret","credential-secret","pdf_encrypted"):
            self.assertNotIn(secret,str(records))

    def test_request_limit_remains_failed(self):
        source=self.retrieve(lambda r:httpx.Response(302,headers={"location":"/next"+str(r.url.path)}),navigation_max_requests="1")
        self.assertEqual(source.retrieval_status.value,"failed")
        self.assertEqual(source.metadata["failure_category"],"content_too_large")
        self.assertEqual(source.metadata["retrieval_diagnostic"]["limit_code"],"request_budget_exhausted")

    def test_html_challenge_category_agrees_with_diagnostic(self):
        source=self.retrieve(lambda r:httpx.Response(200,text="Just a moment. Verify you are human",headers={"content-type":"text/html"}),required_resource_kind="text")
        self.assertEqual(source.retrieval_status.value,"failed")
        self.assertEqual(source.metadata["reason"],"html_challenge")
        self.assertEqual(source.metadata["retrieval_diagnostic"]["terminal_reason"], "html_challenge")
        self.assertEqual(source.metadata["failure_category"],"other_retrieval_error")
        self.assertEqual(source.metadata["retrieval_diagnostic"]["failure_category"],"other_retrieval_error")

    def test_loop_and_link_limit(self):
        source=self.retrieve(lambda r:httpx.Response(200,text='<a href="/landing">data loop</a><a href="/resource">resource</a>',headers={"content-type":"text/html"}),navigation_total_links="2")
        diag=source.metadata["navigation_diagnostics"]
        self.assertLessEqual(diag["considered_links"],2)
        self.assertLessEqual(diag["requests"],2)

    def test_unsafe_redirect_is_not_requested(self):
        calls=[]
        def handler(r):
            calls.append(str(r.url))
            return httpx.Response(302,headers={"location":"http://127.0.0.1/private"})
        source=self.retrieve(handler)
        self.assertEqual(len(calls),1)
        self.assertEqual(source.metadata["failure_category"],"unsafe_address")

    def test_text_html_remains_terminal(self):
        source=self.retrieve(lambda r:httpx.Response(200,text="Ordinary research content",headers={"content-type":"text/html"}),required_resource_kind="text")
        self.assertEqual(source.retrieval_status.value,"acquired")

    def test_redirect_chain_is_persistable_provenance(self):
        def handler(request):
            if request.url.path=="/landing":
                return httpx.Response(302,headers={"location":"/download"})
            return httpx.Response(200,content=workbook(),headers={"content-type":"application/octet-stream"})
        source=self.retrieve(handler)
        self.assertEqual(source.metadata["navigation_chain"],["https://example.org/landing","https://example.org/download"])
        self.assertEqual(source.metadata["navigation_diagnostics"]["requests"],2)

    def test_text_challenge_is_rejected(self):
        source=self.retrieve(lambda r:httpx.Response(200,text="Just a moment. Verify you are human",headers={"content-type":"text/html"}),required_resource_kind="text")
        self.assertEqual(source.retrieval_status.value,"failed")

    def test_compressed_html_is_not_decoded_twice(self):
        import gzip
        body=b"<p>Ordinary research content</p>"
        source=self.retrieve(lambda r:httpx.Response(200,content=gzip.compress(body),headers={"content-type":"text/html","content-encoding":"gzip"}),required_resource_kind="text")
        self.assertEqual(source.retrieval_status.value,"acquired")
        self.assertIn("Ordinary research content",source.content_text)
        self.assertEqual(source.metadata["navigation_diagnostics"]["received_bytes"],len(body))

    def test_unsupported_format_is_controlled(self):
        source=self.retrieve(lambda r:httpx.Response(200,content=b"%PDF",headers={"content-type":"application/pdf"}))
        self.assertEqual(source.retrieval_status.value,"failed")
        self.assertEqual(source.metadata["reason"],"pdf_mime_mismatch")

    def test_depth_limit(self):
        source=self.retrieve(lambda r:httpx.Response(200,text='<a href="/resource/next">resource</a>',headers={"content-type":"text/html"}),navigation_max_depth="0")
        self.assertEqual(source.metadata["navigation_diagnostics"]["requests"],1)
        self.assertEqual(source.metadata["navigation_diagnostics"]["stop_reason"],"depth_limit")

    def test_capability_decisions(self):
        source=Source("s","p","https://example.org/a","https://example.org/a","A","2026-01-01T00:00:00Z",content_text="text")
        self.assertEqual(decide_acquisition(source,structured=True).action,"REFETCH")
        source.metadata["structured_rows"]=[{}]
        self.assertEqual(decide_acquisition(source,structured=True).action,"REEXTRACT")
        source.extraction_revision=TABLE_EXTRACTION_CAPABILITY
        source.raw_checksum_kind="sha256-bytes"
        self.assertEqual(decide_acquisition(source,structured=True).action,"REUSE")
        self.assertEqual(decide_acquisition(source,structured=True,research_design_id="new").action,"REVALIDATE")
