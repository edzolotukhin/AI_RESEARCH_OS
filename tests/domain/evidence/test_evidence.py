from __future__ import annotations

import unittest

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType


class EvidenceDomainTests(unittest.TestCase):
    def test_round_trip_preserves_provenance_and_checksum(self) -> None:
        evidence = Evidence(
            id="ev-1",
            project_id="project-1",
            source_id="source-1",
            source_content_checksum="checksum-a",
            workflow_run_id="run-1",
            research_design_id="design-1",
            research_question_refs=("rq-1",),
            information_need_refs=("in-1",),
            evidence_type=EvidenceType.DIRECT_EXCERPT,
            statement="Market report content is documented.",
            source_excerpt="Acquired market report body text.",
            source_locator={
                "normalized_start": 0,
                "normalized_end": 33,
                "excerpt_hash": "abc",
            },
            extraction_method="deterministic",
            confidence=0.9,
            quality_signals={"direct": True},
            deduplication_key="dedup-key",
            created_at="2026-01-01T00:00:00+00:00",
            metadata={"provider": "deterministic"},
            version=1,
        )
        restored = Evidence.from_dict(evidence.to_dict())
        self.assertEqual(restored.source_content_checksum, "checksum-a")
        self.assertEqual(restored.workflow_run_id, "run-1")
        self.assertEqual(restored.research_design_id, "design-1")
        self.assertEqual(restored.information_need_refs, ("in-1",))


if __name__ == "__main__":
    unittest.main()
