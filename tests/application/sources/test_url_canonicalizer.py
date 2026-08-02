from __future__ import annotations

import unittest

from application.sources.url_canonicalizer import canonicalize_url


class UrlCanonicalizerTests(unittest.TestCase):
    def test_removes_tracking_params_and_fragment(self) -> None:
        url = "HTTPS://Example.com/report?utm_source=x&id=1#section"
        self.assertEqual(
            canonicalize_url(url),
            "https://example.com/report?id=1",
        )

    def test_normalizes_trailing_slash(self) -> None:
        self.assertEqual(
            canonicalize_url("https://example.com/market-report/"),
            "https://example.com/market-report",
        )

    def test_preserves_distinct_query_params(self) -> None:
        first = canonicalize_url("https://example.com/doc?version=1")
        second = canonicalize_url("https://example.com/doc?version=2")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
