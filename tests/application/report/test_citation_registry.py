from __future__ import annotations

import unittest

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.report.citation_registry import CitationRegistry
from domain.evidence.evidence import Evidence


class CitationRegistryTests(unittest.TestCase):
    def test_application_assigns_stable_citation_ids(self) -> None:
        registry = CitationRegistry()
        source = Source(
            id="source-1",
            project_id="p1",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Report A",
            retrieved_at="2026-01-01T00:00:00+00:00",
            source_type="web",
        )
        first = registry.register_source(source)
        second = registry.register_source(source)
        self.assertEqual(first, "S1")
        self.assertEqual(second, "S1")
        self.assertEqual(list(registry.to_dict()), ["S1"])

    def test_same_source_reused_across_sections_keeps_stable_citation(self) -> None:
        registry = CitationRegistry()
        source = Source(
            id="source-1",
            project_id="p1",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Report A",
            retrieved_at="2026-01-01T00:00:00+00:00",
        )
        evidence = Evidence(
            id="evidence-1",
            project_id="p1",
            source_id="source-1",
            source_content_checksum="abc",
            workflow_run_id="run-1",
            research_design_id="design-1",
            statement="fact",
            source_excerpt="fact",
            created_at="2026-01-01T00:00:00+00:00",
        )
        sources_by_id = {"source-1": source}
        evidence_by_id = {"evidence-1": evidence}
        first = registry.citation_ids_for_evidence_refs(
            ("evidence-1",),
            evidence_by_id=evidence_by_id,
            sources_by_id=sources_by_id,
        )
        second = registry.citation_ids_for_evidence_refs(
            ("evidence-1",),
            evidence_by_id=evidence_by_id,
            sources_by_id=sources_by_id,
        )
        self.assertEqual(first, ("S1",))
        self.assertEqual(second, ("S1",))

    def test_citation_resolves_through_evidence_to_source(self) -> None:
        registry = CitationRegistry()
        source = Source(
            id="source-1",
            project_id="p1",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Report A",
            retrieved_at="2026-01-01T00:00:00+00:00",
        )
        evidence = Evidence(
            id="evidence-1",
            project_id="p1",
            source_id="source-1",
            source_content_checksum="abc",
            workflow_run_id="run-1",
            research_design_id="design-1",
            statement="fact",
            source_excerpt="fact",
            created_at="2026-01-01T00:00:00+00:00",
        )
        citation_id = registry.register_evidence(
            evidence,
            sources_by_id={"source-1": source},
        )
        assert citation_id is not None
        entries = registry.to_dict()
        self.assertEqual(entries[citation_id]["source_id"], "source-1")


if __name__ == "__main__":
    unittest.main()
