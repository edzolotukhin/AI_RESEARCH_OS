from __future__ import annotations

import unittest

from domain.sources.retrieval_status import RetrievalStatus
from domain.sources.source import Source

from application.sources.provenance_merge import (
    ProvenanceDelta,
    apply_first_acquisition,
    apply_provenance_delta,
    has_immutable_acquired_content,
    is_successful_acquisition,
    merge_refs,
)


class ProvenanceMergeTests(unittest.TestCase):
    def test_merge_refs_preserves_first_seen_order(self) -> None:
        merged = merge_refs(("b", "a"), ("a", "c"))
        self.assertEqual(merged, ("b", "a", "c"))

    def test_acquired_content_is_immutable_on_provenance_merge(self) -> None:
        existing = Source(
            id="s1",
            project_id="p1",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Title A",
            retrieved_at="2026-01-01T00:00:00+00:00",
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="version A",
            content_checksum="checksum-a",
            workflow_run_refs=("run-a",),
            research_design_refs=("design-a",),
        )
        incoming = Source(
            id="s2",
            project_id="p1",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Title B",
            retrieved_at="2026-02-01T00:00:00+00:00",
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="version B",
            content_checksum="checksum-b",
        )
        self.assertTrue(has_immutable_acquired_content(existing))
        merged = apply_provenance_delta(
            existing,
            ProvenanceDelta(
                workflow_run_id="run-b",
                research_design_id="design-b",
                query_refs=("sq-2",),
                research_question_refs=("rq-2",),
                information_need_refs=("in-2",),
                discovery_records=(),
            ),
        )
        apply_first_acquisition(merged, incoming)
        self.assertEqual(merged.content_text, "version A")
        self.assertEqual(merged.content_checksum, "checksum-a")
        self.assertIn("run-b", merged.workflow_run_refs)

    def test_truncated_counts_as_successful_acquisition(self) -> None:
        self.assertTrue(is_successful_acquisition(RetrievalStatus.TRUNCATED))
        self.assertFalse(is_successful_acquisition(RetrievalStatus.FAILED))

    def test_merge_discovery_records_scopes_by_research_design(self) -> None:
        from application.sources.provenance_merge import merge_discovery_records

        existing = [
            {
                "provider": "deterministic",
                "query_id": "sq-in-1",
                "rank": 1,
                "workflow_run_id": "run-1",
                "research_design_id": "design-1",
            },
        ]
        merged = merge_discovery_records(
            existing,
            (
                {
                    "provider": "deterministic",
                    "query_id": "sq-in-1",
                    "rank": 1,
                    "workflow_run_id": "run-2",
                    "research_design_id": "design-2",
                },
            ),
        )
        self.assertEqual(len(merged), 2)

    def test_missing_discovery_records_detects_run_two_provenance(self) -> None:
        from application.sources.provenance_merge import (
            build_discovery_record,
            missing_discovery_records,
        )

        existing = Source(
            id="s1",
            project_id="p1",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Title",
            retrieved_at="2026-01-01T00:00:00+00:00",
            retrieval_status=RetrievalStatus.ACQUIRED,
            content_text="body",
            metadata={
                "discovery_records": [
                    build_discovery_record(
                        provider="deterministic",
                        query_id="sq-in-1",
                        rank=1,
                        workflow_run_id="run-1",
                        research_design_id="design-1",
                        research_question_id="rq-1",
                        information_need_id="in-1",
                    ),
                ],
            },
        )
        pending = missing_discovery_records(
            existing,
            (
                build_discovery_record(
                    provider="deterministic",
                    query_id="sq-in-1",
                    rank=1,
                    workflow_run_id="run-2",
                    research_design_id="design-2",
                    research_question_id="rq-1",
                    information_need_id="in-1",
                ),
            ),
        )
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
