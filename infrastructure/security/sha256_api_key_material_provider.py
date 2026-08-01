from __future__ import annotations

import hashlib
import hmac
import secrets

from application.security.api_key_format import API_KEY_PREFIX


# Fixed verifier for lookup-miss timing mitigation (SHA-256 hex of a constant string).
_DUMMY_VERIFIER_HASH = hashlib.sha256(b"airos-dummy-verifier").hexdigest()

# token_urlsafe(32) draws 32 bytes from os.urandom → 256 bits of secret entropy.
_SECRET_BYTE_LENGTH = 32


class Sha256ApiKeyMaterialProvider:
    """SHA-256 verifier storage with CSPRNG key generation."""

    def generate_key(self) -> tuple[str, str, str, str]:
        key_id = secrets.token_hex(6)
        secret = secrets.token_urlsafe(_SECRET_BYTE_LENGTH)
        plaintext = f"{API_KEY_PREFIX}_{key_id}_{secret}"
        key_prefix = f"{API_KEY_PREFIX}_{key_id}"
        key_hash = self.hash_secret(plaintext)
        return plaintext, key_id, key_prefix, key_hash

    def hash_secret(self, plaintext_key: str) -> str:
        return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()

    def verify_secret(self, *, plaintext_key: str, expected_hash: str) -> bool:
        actual = self.hash_secret(plaintext_key)
        return hmac.compare_digest(actual, expected_hash)

    def dummy_verifier_hash(self) -> str:
        return _DUMMY_VERIFIER_HASH
