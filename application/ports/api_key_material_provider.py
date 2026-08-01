from __future__ import annotations

from typing import Protocol


class ApiKeyMaterialProvider(Protocol):
    """Generates and verifies API key cryptographic material."""

    def generate_key(self) -> tuple[str, str, str, str]:
        """
        Generate API key material.

        Returns (plaintext_key, key_id, key_prefix, key_hash).
        """

    def hash_secret(self, plaintext_key: str) -> str:
        """Return the stored verifier for a presented plaintext key."""

    def verify_secret(self, *, plaintext_key: str, expected_hash: str) -> bool:
        """Constant-time comparison of plaintext key against stored verifier."""

    def dummy_verifier_hash(self) -> str:
        """Fixed verifier used when lookup misses to reduce timing enumeration."""
