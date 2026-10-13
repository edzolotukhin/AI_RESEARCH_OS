"""Interactively recover one pilot account through the canonical identity service."""
import argparse
from getpass import getpass
import os

from application.composition_root import create_application_container


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    args = parser.parse_args()
    actor_id = (os.environ.get("PILOT_ADMIN_USER_ID") or "").strip()
    if not actor_id:
        raise SystemExit("PILOT_ADMIN_USER_ID is required")
    first, second = getpass("New password: "), getpass("Repeat new password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    container = create_application_container()
    try:
        container.identity_service.administratively_reset_password(args.user_id, first, actor_id=actor_id)
    finally:
        container.shutdown()
    print(f"Password recovered for user_id={args.user_id}; all browser sessions revoked.")


if __name__ == "__main__":
    main()
