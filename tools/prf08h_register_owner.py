"""Register only the disposable PRF-08H UI owner; never seed research."""

from __future__ import annotations

import hashlib
import os

from application.composition_root import create_application_container
from application.security.api_key_format import parse_api_key


def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://prf08h:") or not url.endswith(
        "@postgres:5432/prf08h_acceptance"
    ):
        raise RuntimeError("Refusing non-PRF-08H database")
    key = os.environ.get("UI_INTERNAL_API_KEY", "")
    parsed = parse_api_key(key)
    if parsed is None:
        raise RuntimeError("Invalid disposable UI key")
    key_id, _ = parsed
    container = create_application_container()
    ready, reason = container.check_readiness()
    if not ready:
        raise RuntimeError(f"PRF-08H schema not ready: {reason}")
    service = container.authentication_service
    if service is None:
        raise RuntimeError("Authentication unavailable")
    record = service._api_key_repository.get_by_id(key_id)
    if record is None:
        service.register_api_key(
            name="prf08h-local-owner",
            key_id=key_id,
            key_prefix=f"airos_{key_id}",
            key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        )
    service.authenticate_api_key(key)
    print("PRF-08H disposable owner authentication ready")


if __name__ == "__main__":
    main()
