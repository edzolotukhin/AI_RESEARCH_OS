from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.security.principal import AuthenticatedPrincipal
from tools.create_api_key import resolve_owner_principal
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    postgresql_application_config,
)


class PostgreSQLOwnerBoundApiKeyTests(PostgreSQLIntegrationTestCase):
    def test_owner_bound_key_authenticates_and_authorizes_owner_project(self):
        container = create_application_container(config=postgresql_application_config())
        self.addCleanup(container.shutdown)
        owner = container.identity_service.create_user(
            "owner-bound@example.test", "Owner Bound", "not-a-secret-log"
        )
        project = container.project_service.create_project(
            "Owner-bound project", owner_principal_id=owner.id
        )
        principal_id = resolve_owner_principal(
            container, principal_id=owner.id, project_id=project.id
        )
        plaintext, key_id, key_prefix, key_hash = (
            container.authentication_service.generate_key_material()
        )
        container.authentication_service.register_api_key(
            name="owner-bound-test",
            key_id=key_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            principal_id=principal_id,
        )
        authenticated = container.authentication_service.authenticate_api_key(plaintext)
        self.assertEqual(authenticated.principal_id, owner.id)
        authorized = container.authorization_service.require_project(
            authenticated, project.id
        )
        self.assertEqual(authorized.id, project.id)
        self.assertIsInstance(authenticated, AuthenticatedPrincipal)


if __name__ == "__main__":
    unittest.main()
