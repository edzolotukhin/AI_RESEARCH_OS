import unittest

from application.sources.source_identity import acquisition_path_digest, terminal_resource_key


class SourceIdentityTests(unittest.TestCase):
    def test_two_landings_share_terminal_identity_but_not_path(self):
        terminal = "https://example.org/data.xlsx"
        paths = [acquisition_path_digest(project_id="p", landing_url=landing,
                 terminal_url=terminal, navigation_chain=(landing, terminal))
                 for landing in ("https://example.org/a", "https://example.org/b")]
        self.assertNotEqual(*paths)
        self.assertEqual(terminal_resource_key("p", terminal),
                         terminal_resource_key("p", terminal + "?utm_source=test"))

    def test_two_terminals_have_distinct_resource_identity(self):
        self.assertNotEqual(terminal_resource_key("p", "https://example.org/a.xlsx"),
                            terminal_resource_key("p", "https://example.org/b.xlsx"))

    def test_project_scope_is_part_of_identity(self):
        url = "https://example.org/a.xlsx"
        self.assertNotEqual(terminal_resource_key("p", url), terminal_resource_key("q", url))

    def test_navigation_order_is_preserved(self):
        args = dict(project_id="p", landing_url="https://example.org/a",
                    terminal_url="https://example.org/data.xlsx")
        self.assertNotEqual(
            acquisition_path_digest(**args, navigation_chain=("https://example.org/a", "https://example.org/b")),
            acquisition_path_digest(**args, navigation_chain=("https://example.org/b", "https://example.org/a")))
