from __future__ import annotations

import io

import httpx
from openpyxl import Workbook

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source_candidate import SourceCandidate
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever
from infrastructure.retrieval.link_discovery import discover_links


def _xlsx_bytes() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Population"
    sheet.append(["Year", "Population", "Unit"])
    sheet.append([2015, 42000000, "persons"])
    sheet.append([2016, 41900000, "persons"])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def _candidate(url: str) -> SourceCandidate:
    return SourceCandidate("fixture", url, "fixture", "", "q1", 1)


def test_landing_resource_xlsx_navigation_preserves_provenance():
    workbook = _xlsx_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/landing":
            return httpx.Response(200, text='<a href="/resource">Dataset resource</a>', headers={"content-type": "text/html"})
        if request.url.path == "/resource":
            return httpx.Response(200, text='<a href="/population.xlsx">Download table</a>', headers={"content-type": "text/html"})
        return httpx.Response(200, content=workbook, headers={"content-type": "application/octet-stream"})

    retriever = HttpSourceRetriever(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    source = retriever.retrieve(SourceCandidate(
        "fixture", "https://example.org/landing", "fixture", "", "q1", 1,
        metadata={"navigation_enabled": "1", "navigation_terms": "population|2015|official"},
    ))

    assert source.retrieval_status is RetrievalStatus.ACQUIRED
    assert source.content_type == "application/octet-stream"
    assert "2015" in source.content_text
    assert source.metadata["navigation_chain"] == [
        "https://example.org/landing",
        "https://example.org/resource",
        "https://example.org/population.xlsx",
    ]
    assert source.metadata["parser"] == "xlsx"
    assert source.metadata["sheet_count"] == 1


def test_navigation_deduplicates_cycle_and_stops_at_depth():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='<a href="/same">same</a>', headers={"content-type": "text/html"})

    retriever = HttpSourceRetriever(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    source = retriever.retrieve(SourceCandidate(
        "fixture", "https://example.org/same", "fixture", "", "q1", 1,
        metadata={"navigation_enabled": "1", "navigation_max_depth": "2"},
    ))
    assert source.retrieval_status is RetrievalStatus.ACQUIRED
    assert source.metadata.get("navigation_chain") is None


def test_resource_page_download_without_file_extension_is_selected_as_table():
    links = discover_links(
        '<h1>Population.xlsx</h1><p>Format: XLSX</p>'
        '<a href="/download/123">Завантажити</a>',
        base_url="https://example.org/resource/123",
    )
    assert links[0].url == "https://example.org/download/123"
    assert links[0].resource_hint == "table"


def test_navigation_records_controlled_diagnostics_when_no_link_is_selected():
    retriever = HttpSourceRetriever(http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="<p>complete text</p>", headers={"content-type": "text/html"}),
    )))
    source = retriever.retrieve(SourceCandidate(
        "fixture", "https://example.org/page", "fixture", "", "q1", 1,
        metadata={"navigation_enabled": "1"},
    ))
    assert source.metadata["navigation_diagnostics"] == {
        "considered": True,
        "activated": True,
        "candidate_links": 0,
        "stop_reason": "no_terminal_resource",
        "rejection_reason": "candidates_not_acquired_or_visited",
    }
