from __future__ import annotations

import unittest

from application.services.authentication_service import AuthenticationService
from infrastructure.persistence.postgresql.repositories.postgresql_api_key_repository import (
    PostgreSQLApiKeyRepository,
)
from infrastructure.security.sha256_api_key_material_provider import (
    Sha256ApiKeyMaterialProvider,
)

from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


def _build_service(session_factory) -> AuthenticationService:
    return AuthenticationService(
        api_key_repository=PostgreSQLApiKeyRepository(session_factory),
        material_provider=Sha256ApiKeyMaterialProvider(),
    )


class PostgreSQLApiKeyPersistenceTests(PostgreSQLIntegrationTestCase):

    def test_create_hashed_key_and_verify(self) -> None:
        service = _build_service(self.session_factory)
        plaintext, key_id, key_prefix, key_hash = service.generate_key_material()
        service.register_api_key(
            name="integration",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        principal = service.authenticate_api_key(plaintext)
        self.assertEqual(principal.name, "integration")

    def test_invalid_secret_rejected(self) -> None:
        service = _build_service(self.session_factory)
        plaintext, key_id, key_prefix, key_hash = service.generate_key_material()
        service.register_api_key(
            name="reject",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        bad = plaintext[:-1] + ("x" if plaintext[-1] != "x" else "y")
        from application.persistence.exceptions import InvalidCredentialsError

        with self.assertRaises(InvalidCredentialsError):
            service.authenticate_api_key(bad)

    def test_plaintext_key_not_stored_in_database(self) -> None:
        from sqlalchemy import text

        provider = Sha256ApiKeyMaterialProvider()
        plaintext, key_id, key_prefix, key_hash = provider.generate_key()
        service = _build_service(self.session_factory)
        service.register_api_key(
            name="storage",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT key_hash, key_prefix FROM api_keys WHERE id = :id"),
                {"id": key_id},
            ).one()
        self.assertEqual(row.key_hash, provider.hash_secret(plaintext))
        self.assertNotEqual(row.key_hash, plaintext)
        self.assertEqual(row.key_prefix, key_prefix)

    def test_revoked_key_rejected(self) -> None:
        from datetime import datetime, timezone

        service = _build_service(self.session_factory)
        plaintext, key_id, key_prefix, key_hash = service.generate_key_material()
        service.register_api_key(
            name="revoked",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        service._api_key_repository.revoke(
            key_id,
            revoked_at=datetime.now(timezone.utc),
        )
        from application.persistence.exceptions import InvalidCredentialsError

        with self.assertRaises(InvalidCredentialsError):
            service.authenticate_api_key(plaintext)

    def test_inactive_key_rejected(self) -> None:
        from datetime import datetime, timezone

        service = _build_service(self.session_factory)
        plaintext, key_id, key_prefix, key_hash = service.generate_key_material()
        service.register_api_key(
            name="inactive",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        service._api_key_repository.revoke(
            key_id,
            revoked_at=datetime.now(timezone.utc),
        )
        from application.persistence.exceptions import InvalidCredentialsError

        with self.assertRaises(InvalidCredentialsError):
            service.authenticate_api_key(plaintext)

        stored = service._api_key_repository.get_by_id(key_id)
        assert stored is not None
        self.assertFalse(stored.is_active)
        self.assertIsNotNone(stored.revoked_at)


if __name__ == "__main__":
    unittest.main()
