from __future__ import annotations

import argparse
import sys

from application.composition_root import create_application_container
from application.config import ApplicationConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a service API key for AI Research OS.",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Human-readable label for the API key (e.g. n8n).",
    )
    args = parser.parse_args(argv)

    config = ApplicationConfig.from_env()
    if config.persistence_backend != "postgresql":
        print(
            "ERROR: API key bootstrap requires PERSISTENCE_BACKEND=postgresql.",
            file=sys.stderr,
        )
        return 1

    container = create_application_container(config=config)
    try:
        if container.authentication_service is None:
            print(
                "ERROR: Authentication service is not available. "
                "Run Alembic migrations to head first.",
                file=sys.stderr,
            )
            return 1

        ready, reason = container.check_readiness()
        if not ready:
            print(
                f"ERROR: PostgreSQL schema is not ready ({reason}). "
                "Run: python -m alembic upgrade head",
                file=sys.stderr,
            )
            return 1

        plaintext, key_id, key_prefix, key_hash = (
            container.authentication_service.generate_key_material()
        )
        record = container.authentication_service.register_api_key(
            name=args.name,
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
    finally:
        container.shutdown()

    print("API key created successfully.")
    print(f"name: {args.name}")
    print(f"principal_id: {record.principal_id}")
    print(f"key_prefix: {record.key_prefix}")
    print("plaintext_key (shown once):")
    print(plaintext)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
