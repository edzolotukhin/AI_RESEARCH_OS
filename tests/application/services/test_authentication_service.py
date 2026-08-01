from __future__ import annotations

import unittest
from unittest.mock import Mock

from application.persistence.exceptions import InvalidCredentialsError
from application.services.authentication_service import AuthenticationService
from infrastructure.persistence.memory.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)
from infrastructure.security.sha256_api_key_material_provider import (
    Sha256ApiKeyMaterialProvider,
)


def _build_service() -> AuthenticationService:
    return AuthenticationService(
        api_key_repository=InMemoryApiKeyRepository(),
        material_provider=Sha256ApiKeyMaterialProvider(),
    )


class AuthenticationServiceTests(unittest.TestCase):

    def test_unknown_and_wrong_secret_share_public_error(self) -> None:
        service = _build_service()
        plaintext, key_id, key_prefix, key_hash = service.generate_key_material()
        service.register_api_key(
            name="owner",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        wrong_secret = plaintext[:-1] + ("x" if plaintext[-1] != "x" else "y")

        with self.assertRaises(InvalidCredentialsError) as unknown_exc:
            service.authenticate_api_key("airos_deadbeef0000_not-real-secret")
        with self.assertRaises(InvalidCredentialsError) as wrong_exc:
            service.authenticate_api_key(wrong_secret)

        self.assertEqual(
            unknown_exc.exception.args[0],
            wrong_exc.exception.args[0],
        )

    def test_missing_key_runs_dummy_verifier_before_rejection(self) -> None:
        provider = Mock(spec=Sha256ApiKeyMaterialProvider)
        provider.dummy_verifier_hash.return_value = "0" * 64
        provider.verify_secret.return_value = False
        service = AuthenticationService(
            api_key_repository=InMemoryApiKeyRepository(),
            material_provider=provider,
        )
        with self.assertRaises(InvalidCredentialsError):
            service.authenticate_api_key("airos_abcd12345678_secret-part")
        provider.verify_secret.assert_called_once()
        provider.dummy_verifier_hash.assert_called_once()


if __name__ == "__main__":
    unittest.main()
