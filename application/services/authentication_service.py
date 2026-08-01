from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from application.persistence.records import ApiKeyRecord
from application.ports.api_key_material_provider import ApiKeyMaterialProvider
from application.ports.api_key_repository import ApiKeyRepository
from application.security.api_key_format import parse_api_key
from application.security.principal import AuthenticatedPrincipal


def is_credential_valid(record: ApiKeyRecord) -> bool:
    """Credential is valid only when active and not revoked."""
    return record.is_active and record.revoked_at is None


class AuthenticationService:
    """Validates API keys and resolves authenticated principals."""

    def __init__(
        self,
        *,
        api_key_repository: ApiKeyRepository,
        material_provider: ApiKeyMaterialProvider,
    ) -> None:
        self._api_key_repository = api_key_repository
        self._material_provider = material_provider

    def authenticate_api_key(self, raw_key: str | None) -> AuthenticatedPrincipal:
        from application.persistence.exceptions import InvalidCredentialsError

        if raw_key is None or not raw_key.strip():
            raise InvalidCredentialsError("Authentication credentials were not provided.")

        parsed = parse_api_key(raw_key.strip())
        if parsed is None:
            raise InvalidCredentialsError("Authentication credentials are invalid.")

        key_id, plaintext_key = parsed
        record = self._api_key_repository.get_by_id(key_id)
        expected_hash = (
            record.key_hash
            if record is not None
            else self._material_provider.dummy_verifier_hash()
        )
        if not self._material_provider.verify_secret(
            plaintext_key=plaintext_key,
            expected_hash=expected_hash,
        ):
            raise InvalidCredentialsError("Authentication credentials are invalid.")

        if record is None or not is_credential_valid(record):
            raise InvalidCredentialsError("Authentication credentials are invalid.")

        now = datetime.now(timezone.utc)
        self._api_key_repository.mark_used(key_id, used_at=now)
        return AuthenticatedPrincipal(
            principal_id=record.principal_id,
            name=record.name,
            authentication_type="api_key",
            api_key_id=record.id,
            key_prefix=record.key_prefix,
        )

    def register_api_key(
        self,
        *,
        name: str,
        key_id: str,
        key_prefix: str,
        key_hash: str,
        principal_id: str | None = None,
    ) -> ApiKeyRecord:
        record = ApiKeyRecord(
            id=key_id,
            principal_id=principal_id or str(uuid4()),
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        self._api_key_repository.create(record)
        return record

    def generate_key_material(self) -> tuple[str, str, str, str]:
        return self._material_provider.generate_key()
