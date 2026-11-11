from __future__ import annotations

import unittest

from application.authority_extension.selected_workflow import SelectedAuthorityExtensionService


class _RecoveryRepository:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reconcile_failed_active(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class AuthorityExtensionRecoveryContractTests(unittest.TestCase):
    def _service(self, repository):
        return SelectedAuthorityExtensionService(
            workflow_service=object(), extension_repository=repository,
            composed_authority_repository=object(), state_store=object(),
        )

    def test_reconciliation_delegates_one_targeted_operation(self):
        repo = _RecoveryRepository({"ok": True, "code": "reconciled"})
        result = self._service(repo).reconcile_failed_extension(
            project_id="project", extension_id="extension",
            expected_workflow_run_id="run", failure_class="RuntimeError",
            reason="operator-approved stale terminal workflow", dry_run=False,
        )
        self.assertEqual(result["code"], "reconciled")
        self.assertEqual(len(repo.calls), 1)
        self.assertFalse(repo.calls[0]["dry_run"])

    def test_dry_run_is_forwarded_without_external_dispatch(self):
        repo = _RecoveryRepository({"ok": True, "code": "dry_run"})
        result = self._service(repo).reconcile_failed_extension(
            project_id="project", extension_id="extension",
            expected_workflow_run_id="run", failure_class="RuntimeError",
            reason="preflight", dry_run=True,
        )
        self.assertEqual(result["code"], "dry_run")
        self.assertTrue(repo.calls[0]["dry_run"])


if __name__ == "__main__":
    unittest.main()
