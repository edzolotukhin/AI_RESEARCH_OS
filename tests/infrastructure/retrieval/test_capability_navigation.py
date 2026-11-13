from dataclasses import replace
import io
import unittest
from unittest.mock import patch
import httpx
from openpyxl import Workbook
from application.sources.acquisition_capability import decide_acquisition, TABLE_EXTRACTION_CAPABILITY
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
        self.assertEqual(source.retrieval_status.value,"unsupported")

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
