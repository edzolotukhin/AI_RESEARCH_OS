"""Regression tests for URL validation and DNS resolution semantics."""

from __future__ import annotations

import unittest

from infrastructure.retrieval.network_safety import UnsafeUrlError, validate_fetch_url


class ValidateFetchUrlTests(unittest.TestCase):
    def test_ipv4_only_public_hostname_passes_when_ipv6_lookup_fails(self) -> None:
        def resolver(host: str) -> list[str]:
            if host != "wise.com":
                raise AssertionError(f"unexpected host: {host}")
            return ["93.184.216.34"]

        validate_fetch_url(
            "https://wise.com/ru/cost-of-living/serbia",
            resolve_addresses=resolver,
        )

    def test_multiple_public_a_records_pass(self) -> None:
        validate_fetch_url(
            "https://example.com/page",
            resolve_addresses=lambda _host: [
                "93.184.216.34",
                "93.184.216.35",
            ],
        )

    def test_localhost_hostname_is_blocked(self) -> None:
        with self.assertRaises(UnsafeUrlError) as ctx:
            validate_fetch_url("http://localhost/report")
        self.assertEqual(ctx.exception.category, "unsafe_address")
        self.assertIn("Localhost", str(ctx.exception))

    def test_private_resolved_address_is_blocked(self) -> None:
        with self.assertRaises(UnsafeUrlError) as ctx:
            validate_fetch_url(
                "https://service.example/report",
                resolve_addresses=lambda _host: ["10.0.0.8"],
            )
        self.assertEqual(ctx.exception.category, "unsafe_address")
        self.assertIn("not allowed", str(ctx.exception))

    def test_true_dns_failure_uses_dns_resolution_failed_category(self) -> None:
        with self.assertRaises(UnsafeUrlError) as ctx:
            validate_fetch_url(
                "https://missing.example/report",
                resolve_addresses=lambda _host: [],
            )
        self.assertEqual(ctx.exception.category, "dns_resolution_failed")
        self.assertIn("Unable to resolve host", str(ctx.exception))

    def test_ipv6_only_failure_without_ipv4_is_dns_failure(self) -> None:
        with self.assertRaises(UnsafeUrlError) as ctx:
            validate_fetch_url(
                "https://missing.example/report",
                resolve_addresses=lambda _host: [],
            )
        self.assertEqual(ctx.exception.category, "dns_resolution_failed")

    def test_literal_public_ip_passes(self) -> None:
        validate_fetch_url(
            "https://93.184.216.34/page",
            resolve_addresses=lambda _host: ["93.184.216.34"],
        )

    def test_literal_private_ip_is_blocked(self) -> None:
        with self.assertRaises(UnsafeUrlError) as ctx:
            validate_fetch_url("https://10.0.0.5/internal")
        self.assertEqual(ctx.exception.category, "unsafe_address")

    def test_dns_resolution_timeout_uses_dns_resolution_failed_category(self) -> None:
        from concurrent.futures import TimeoutError as FuturesTimeoutError
        from unittest.mock import patch

        with patch(
            "infrastructure.retrieval.network_safety.ThreadPoolExecutor"
        ) as executor_cls:
            future = executor_cls.return_value.__enter__.return_value.submit.return_value
            future.result.side_effect = FuturesTimeoutError
            with self.assertRaises(UnsafeUrlError) as ctx:
                validate_fetch_url(
                    "https://slow.example/report",
                    dns_timeout_seconds=0.01,
                )
        self.assertEqual(ctx.exception.category, "dns_resolution_failed")
        self.assertIn("timed out", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
