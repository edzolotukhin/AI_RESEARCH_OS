from __future__ import annotations

from application.container import ApplicationContainer


def bootstrap_test_api_key(
    container: ApplicationContainer,
    *,
    name: str = "test",
) -> str:
    if container.authentication_service is None:
        raise RuntimeError(
            "Authentication service is not configured for this container."
        )

    plaintext, key_id, key_prefix, key_hash = (
        container.authentication_service.generate_key_material()
    )
    container.authentication_service.register_api_key(
        name=name,
        key_id=key_id,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    container._test_api_key_plaintext = plaintext
    return plaintext


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def bootstrap_second_test_api_key(
    container: ApplicationContainer,
    *,
    name: str = "test-other",
) -> str:
    return bootstrap_test_api_key(container, name=name)
