from __future__ import annotations

from typing import Protocol


class DeterministicDigestProvider(Protocol):
    """Produces deterministic digests without exposing crypto primitives."""

    def sha256_hex(self, data: bytes) -> str:
        """Return the lowercase SHA-256 hexadecimal digest of ``data``."""
