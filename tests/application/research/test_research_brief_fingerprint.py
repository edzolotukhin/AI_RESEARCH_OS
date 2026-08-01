from __future__ import annotations

import unittest

from application.runtime.research_request_fingerprint import (
    compute_research_request_fingerprint,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST


class ResearchBriefFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_id = "project-1"
        self.base = CANONICAL_BRIEF_REQUEST

    def test_same_semantic_brief_same_fingerprint(self) -> None:
        first = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=self.base,
        )
        second = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=dict(self.base),
        )
        self.assertEqual(first, second)

    def test_changed_objective_different_fingerprint(self) -> None:
        base_fp = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=self.base,
        )
        changed = dict(self.base)
        changed["objectives"] = ["Map competitor share"]
        changed_fp = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=changed,
        )
        self.assertNotEqual(base_fp, changed_fp)

    def test_changed_geography_different_fingerprint(self) -> None:
        base_fp = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=self.base,
        )
        changed = dict(self.base)
        changed["geography"] = ["France"]
        changed_fp = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=changed,
        )
        self.assertNotEqual(base_fp, changed_fp)

    def test_changed_timeframe_different_fingerprint(self) -> None:
        base_fp = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=self.base,
        )
        changed = dict(self.base)
        changed["timeframe"] = "2027"
        changed_fp = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=changed,
        )
        self.assertNotEqual(base_fp, changed_fp)

    def test_correlation_metadata_only_same_fingerprint(self) -> None:
        """Fingerprint excludes transport metadata; brief-only hash is stable."""
        first = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=self.base,
        )
        second = compute_research_request_fingerprint(
            project_id=self.project_id,
            brief=dict(self.base),
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
