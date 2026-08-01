from __future__ import annotations

import unittest
from uuid import uuid4

from application.persistence.exceptions import DuplicateEntityError
from application.services.authentication_service import AuthenticationService
from infrastructure.persistence.memory.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)
from infrastructure.security.sha256_api_key_material_provider import (
    Sha256ApiKeyMaterialProvider,
)


class ApiKeyBootstrapConcurrencyTests(unittest.TestCase):

    def test_repeated_generation_produces_unique_identities(self) -> None:
        provider = Sha256ApiKeyMaterialProvider()
        service = AuthenticationService(
            api_key_repository=InMemoryApiKeyRepository(),
            material_provider=provider,
        )
        seen: set[str] = set()
        for index in range(50):
            plaintext, key_id, key_prefix, key_hash = service.generate_key_material()
            self.assertNotIn(key_id, seen)
            seen.add(key_id)
            service.register_api_key(
                name=f"bootstrap-{index}",
                key_id=key_id,
                key_prefix=key_prefix,
                key_hash=key_hash,
            )
            principal = service.authenticate_api_key(plaintext)
            self.assertEqual(principal.api_key_id, key_id)

    def test_duplicate_key_identity_is_rejected(self) -> None:
        service = AuthenticationService(
            api_key_repository=InMemoryApiKeyRepository(),
            material_provider=Sha256ApiKeyMaterialProvider(),
        )
        _, key_id, key_prefix, key_hash = service.generate_key_material()
        service.register_api_key(
            name="first",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        with self.assertRaises(DuplicateEntityError):
            service.register_api_key(
                name="second",
                key_id=key_id,
                key_prefix=f"{key_prefix}-dup",
                key_hash=key_hash,
            )


if __name__ == "__main__":
    unittest.main()
