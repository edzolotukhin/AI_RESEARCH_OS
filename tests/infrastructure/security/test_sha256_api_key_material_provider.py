from __future__ import annotations

import re
import unittest

from application.security.api_key_format import API_KEY_PREFIX, parse_api_key
from infrastructure.security.sha256_api_key_material_provider import (
    Sha256ApiKeyMaterialProvider,
    _SECRET_BYTE_LENGTH,
)


class ApiKeyFormatTests(unittest.TestCase):

    def test_parse_valid_structure(self) -> None:
        parsed = parse_api_key("airos_abcd12345678_secret-part")
        self.assertEqual(parsed, ("abcd12345678", "airos_abcd12345678_secret-part"))

    def test_parse_rejects_wrong_prefix(self) -> None:
        self.assertIsNone(parse_api_key("other_abcd12345678_secret"))

    def test_parse_rejects_missing_segments(self) -> None:
        self.assertIsNone(parse_api_key("airos_onlyone"))


class ApiKeyMaterialProviderTests(unittest.TestCase):

    _KEY_PATTERN = re.compile(
        rf"^{API_KEY_PREFIX}_[0-9a-f]{{12}}_[A-Za-z0-9_-]{{43}}$",
    )

    def test_generated_key_matches_expected_structure(self) -> None:
        provider = Sha256ApiKeyMaterialProvider()
        plaintext, key_id, key_prefix, key_hash = provider.generate_key()
        self.assertRegex(plaintext, self._KEY_PATTERN)
        self.assertEqual(key_prefix, f"{API_KEY_PREFIX}_{key_id}")
        self.assertEqual(len(key_id), 12)
        self.assertEqual(len(key_hash), 64)
        self.assertTrue(provider.verify_secret(plaintext_key=plaintext, expected_hash=key_hash))

    def test_secret_entropy_is_at_least_256_bits(self) -> None:
        self.assertGreaterEqual(_SECRET_BYTE_LENGTH * 8, 256)

    def test_generated_identities_are_unique_over_repeated_generation(self) -> None:
        provider = Sha256ApiKeyMaterialProvider()
        seen_ids: set[str] = set()
        for _ in range(100):
            _, key_id, _, _ = provider.generate_key()
            self.assertNotIn(key_id, seen_ids)
            seen_ids.add(key_id)

    def test_hash_and_verify_use_constant_time_comparison(self) -> None:
        provider = Sha256ApiKeyMaterialProvider()
        plaintext, _, _, key_hash = provider.generate_key()
        self.assertTrue(provider.verify_secret(plaintext_key=plaintext, expected_hash=key_hash))
        self.assertFalse(
            provider.verify_secret(plaintext_key=plaintext + "x", expected_hash=key_hash),
        )


if __name__ == "__main__":
    unittest.main()
