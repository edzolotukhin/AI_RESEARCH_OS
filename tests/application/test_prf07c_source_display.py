"""Saved source fields are displayed without Python dict serialization."""

import unittest

from application.report.source_display import source_display


class SourceDisplayTests(unittest.TestCase):
    def test_present_saved_fields_only(self):
        self.assertEqual(
            source_display({"title": "Назва", "canonical_url": "https://example.invalid/a"}),
            "Назва — https://example.invalid/a",
        )
        self.assertEqual(source_display({"title": "Назва"}), "Назва")
        self.assertEqual(source_display({"canonical_url": "https://example.invalid/a"}),
                         "https://example.invalid/a")
        self.assertEqual(source_display({}), "Відомості про джерело недоступні")
        self.assertEqual(source_display("Збережене джерело"), "Збережене джерело")
