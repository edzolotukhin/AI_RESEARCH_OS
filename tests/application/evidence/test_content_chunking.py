from __future__ import annotations

import unittest

from application.evidence.content_chunking import (
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS,
    DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS,
    split_normalized_source_content,
)


class ContentChunkingTests(unittest.TestCase):
    def test_splits_large_normalized_content_with_overlap(self) -> None:
        content = "word " * 5000
        chunks = split_normalized_source_content(
            content,
            chunk_chars=1000,
            overlap_chars=100,
        )
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(len(chunks[0].text), 1000)
        self.assertEqual(chunks[0].original_normalized_start, 0)
        self.assertGreater(chunks[1].original_normalized_start, 0)

    def test_defaults_are_conservative(self) -> None:
        self.assertEqual(DEFAULT_EVIDENCE_EXTRACTION_CHUNK_CHARS, 8000)
        self.assertEqual(DEFAULT_EVIDENCE_EXTRACTION_CHUNK_OVERLAP_CHARS, 500)


if __name__ == "__main__":
    unittest.main()
