from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from application.persistence.exceptions import EntityNotFoundError
from tools.create_api_key import resolve_owner_principal


class CreateApiKeyValidationTests(unittest.TestCase):
    def _container(self, *, owner: str, user=None):
        project_service = Mock()
        project_service.get_project.return_value = SimpleNamespace(
            owner_principal_id=owner,
        )
        identity_service = SimpleNamespace(store=Mock())
        identity_service.store.get_user.return_value = user
        return SimpleNamespace(
            project_service=project_service,
            identity_service=identity_service,
        )

    def test_active_project_owner_is_returned(self):
        principal = "owner-1"
        container = self._container(
            owner=principal,
            user=SimpleNamespace(status=SimpleNamespace(value="active")),
        )
        self.assertEqual(
            resolve_owner_principal(container, principal_id=principal, project_id="p1"),
            principal,
        )

    def test_foreign_principal_is_rejected(self):
        container = self._container(
            owner="owner-1",
            user=SimpleNamespace(status=SimpleNamespace(value="active")),
        )
        with self.assertRaisesRegex(ValueError, "project owner"):
            resolve_owner_principal(container, principal_id="other", project_id="p1")

    def test_unknown_project_is_rejected(self):
        container = self._container(
            owner="owner-1",
            user=SimpleNamespace(status=SimpleNamespace(value="active")),
        )
        container.project_service.get_project.side_effect = EntityNotFoundError("missing")
        with self.assertRaisesRegex(ValueError, "project does not exist"):
            resolve_owner_principal(container, principal_id="owner-1", project_id="p1")

    def test_unknown_or_inactive_principal_is_rejected(self):
        for user in (None, SimpleNamespace(status=SimpleNamespace(value="disabled"))):
            with self.subTest(user=user):
                container = self._container(owner="owner-1", user=user)
                with self.assertRaisesRegex(ValueError, "does not exist or is not active"):
                    resolve_owner_principal(
                        container, principal_id="owner-1", project_id="p1"
                    )


if __name__ == "__main__":
    unittest.main()
