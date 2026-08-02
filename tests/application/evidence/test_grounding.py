from __future__ import annotations

import unittest

from application.evidence.exceptions import UngroundedEvidenceError
from application.evidence.grounding import (
    locate_excerpt,
    normalize_source_text,
    verify_grounding,
)


class GroundingTests(unittest.TestCase):
    def test_valid_excerpt_accepted_with_whitespace_normalization(self) -> None:
        source = "Line one.\n\n  Acquired market report body text.  "
        locator = verify_grounding(
            source_text=source,
            excerpt="Acquired   market report body text.",
        )
        self.assertGreaterEqual(locator.normalized_start, 0)

    def test_hallucinated_excerpt_rejected(self) -> None:
        with self.assertRaises(UngroundedEvidenceError):
            verify_grounding(
                source_text="Actual source content only.",
                excerpt="Invented excerpt text.",
            )

    def test_locator_prefers_occurrence_within_chunk_range(self) -> None:
        source = "alpha beta gamma alpha beta end"
        from application.evidence.grounding import verify_grounding

        locator = verify_grounding(
            source_text=source,
            excerpt="alpha beta",
            chunk_normalized_start=12,
            chunk_normalized_end=28,
        )
        self.assertEqual(locator.normalized_start, 17)


if __name__ == "__main__":
    unittest.main()
