from __future__ import annotations

import argparse
import sys

from application.composition_root import create_application_container
from application.config import ApplicationConfig
from application.persistence.exceptions import EntityNotFoundError


def resolve_owner_principal(container, *, principal_id: str, project_id: str) -> str:
    """Validate an existing active principal against a project owner."""
    try:
        project = container.project_service.get_project(project_id)
    except EntityNotFoundError as exc:
        raise ValueError("project does not exist") from exc
    if project.owner_principal_id != principal_id:
        raise ValueError("principal is not the project owner")
    if container.identity_service is None:
        raise ValueError("identity service is unavailable")
    user = container.identity_service.store.get_user(principal_id)
    if user is None or getattr(user.status, "value", user.status) != "active":
        raise ValueError("principal does not exist or is not active")
    return principal_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a service API key for AI Research OS.",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Human-readable label for the API key (e.g. n8n).",
    )
    parser.add_argument(
        "--principal-id",
        help="Existing active owner principal to bind the API key to.",
    )
    parser.add_argument(
        "--project-id",
        help="Project whose owner must match --principal-id.",
    )
    args = parser.parse_args(argv)

    if args.principal_id and not args.project_id:
        parser.error("--project-id is required when --principal-id is provided")
    if args.project_id and not args.principal_id:
        parser.error("--principal-id is required when --project-id is provided")

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

        principal_id = None
        if args.principal_id:
            try:
                principal_id = resolve_owner_principal(
                    container,
                    principal_id=args.principal_id,
                    project_id=args.project_id,
                )
            except Exception as exc:
                print(f"ERROR: cannot validate owner principal ({exc}).", file=sys.stderr)
                return 1

        plaintext, key_id, key_prefix, key_hash = (
            container.authentication_service.generate_key_material()
        )
        record = container.authentication_service.register_api_key(
            name=args.name,
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            principal_id=principal_id,
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
