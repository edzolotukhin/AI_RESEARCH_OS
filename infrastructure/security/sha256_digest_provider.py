from __future__ import annotations

import hashlib


class Sha256DigestProvider:
    """Infrastructure implementation of deterministic SHA-256 identity."""

    def sha256_hex(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
