"""Seed/verify a disposable OPS-01A fixture through canonical application ports.

This module is an operator-invoked acceptance helper, not an API endpoint.
It never calls providers and never prints credentials.
"""
from __future__ import annotations

import hashlib
import os

from application.composition_root import create_application_container
from application.identity import ProjectRole
from infrastructure.quantitative.storage.protected_file_dataset_storage import (
    ProtectedFileDatasetStorage,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


PROJECT_NAME = "OPS-01A disposable persistence proof"
RAW_ID = "ops01a-protected-fixture"
RAW_BYTES = b"OPS-01A synthetic protected artifact\n"


def _password(name: str) -> str:
    value = os.environ.get(name, "")
    if len(value) < 12:
        raise SystemExit(f"{name} is required and must meet the normal password policy")
    return value


def main() -> int:
    owner_email = os.environ.get("OPS01A_OWNER_EMAIL", "ops01a-owner@example.invalid")
    researcher_email = os.environ.get("OPS01A_RESEARCHER_EMAIL", "ops01a-researcher@example.invalid")
    container = create_application_container()
    try:
        identity = container.identity_service
        if identity is None:
            raise SystemExit("identity service unavailable")
        owner = identity.store.get_user_by_email(owner_email) or identity.create_user(
            owner_email,
            "OPS-01A Owner",
            _password("OPS01A_OWNER_PASSWORD"),
        )
        researcher = identity.store.get_user_by_email(researcher_email) or identity.create_user(
            researcher_email,
            "OPS-01A Researcher",
            _password("OPS01A_RESEARCHER_PASSWORD"),
        )
        projects = [
            item for item in container.project_service.list_projects() if item.name == PROJECT_NAME
        ]
        project = projects[0] if projects else container.project_service.create_project(
            PROJECT_NAME,
            owner_principal_id=owner.id,
            selected_methods=("QUANTITATIVE",),
        )
        if identity.store.get_membership(project.id, owner.id) is None:
            identity.add_membership(
                project.id,
                owner.id,
                ProjectRole.OWNER,
                actor_id=owner.id,
            )
        root = os.environ.get("QUANTITATIVE_PROTECTED_STORAGE_ROOT")
        if not root:
            raise SystemExit("QUANTITATIVE_PROTECTED_STORAGE_ROOT unavailable")
        storage = ProtectedFileDatasetStorage(
            root=root,
            project_id=project.id,
            run_id="ops01a-persistence-run",
            digest_provider=Sha256DigestProvider(),
        )
        storage.put_raw_file(RAW_ID, RAW_BYTES)
        restored = storage.get_raw_file(RAW_ID)
        if restored != RAW_BYTES:
            raise SystemExit("protected fixture persistence mismatch")
        print(
            " ".join(
                (
                    f"owner_id={owner.id}",
                    f"researcher_id={researcher.id}",
                    f"project_id={project.id}",
                    f"artifact_sha256={hashlib.sha256(restored).hexdigest()}",
                ),
            ),
        )
        return 0
    finally:
        container.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
