from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from infrastructure.retrieval.network_safety import UnsafeUrlError
from infrastructure.retrieval.redirect_fetcher import fetch_with_validated_redirects


class RedirectFetcherTests(unittest.TestCase):
    @patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url")
    def test_blocks_redirect_to_localhost(self, validate_mock) -> None:
        def _validate(url: str) -> None:
            if "127.0.0.1" in url or "localhost" in url:
                raise UnsafeUrlError("blocked")

        validate_mock.side_effect = _validate
        client = Mock()
        first = Mock()
        first.status_code = 302
        first.headers = {"location": "http://127.0.0.1/internal"}
        client.get.return_value = first
        with self.assertRaises(UnsafeUrlError):
            fetch_with_validated_redirects(
                client,
                "https://example.com/start",
                max_redirects=3,
            )
        client.get.assert_called_once()

    @patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url")
    def test_blocks_redirect_to_private_ip(self, validate_mock) -> None:
        def _validate(url: str) -> None:
            if "10.0.0.5" in url:
                raise UnsafeUrlError("private")

        validate_mock.side_effect = _validate
        client = Mock()
        first = Mock()
        first.status_code = 302
        first.headers = {"location": "http://10.0.0.5/report"}
        client.get.return_value = first
        with self.assertRaises(UnsafeUrlError):
            fetch_with_validated_redirects(
                client,
                "https://example.com/start",
                max_redirects=3,
            )

    @patch("infrastructure.retrieval.redirect_fetcher.validate_fetch_url")
    def test_bounded_redirect_chain(self, _validate) -> None:
        client = Mock()
        redirect = Mock()
        redirect.status_code = 302
        redirect.headers = {"location": "/next"}
        client.get.return_value = redirect
        with self.assertRaises(UnsafeUrlError):
            fetch_with_validated_redirects(
                client,
                "https://example.com/start",
                max_redirects=1,
            )
        self.assertEqual(client.get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
