from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class SecurityBoundaryTests(unittest.TestCase):

    def test_domain_does_not_import_fastapi(self) -> None:
        self._assert_package_has_no_imports("domain", {"fastapi", "starlette"})

    def test_application_does_not_import_fastapi_or_sqlalchemy(self) -> None:
        self._assert_package_has_no_imports(
            "application",
            {"fastapi", "starlette", "sqlalchemy"},
        )

    def test_domain_and_application_do_not_import_openpyxl(self) -> None:
        self._assert_package_has_no_imports("domain", {"openpyxl"})
        self._assert_package_has_no_imports("application", {"openpyxl"})

    def test_api_routers_do_not_import_postgresql_repositories(self) -> None:
        router_dir = REPO_ROOT / "api" / "routers"
        forbidden = "infrastructure.persistence.postgresql.repositories"
        for path in router_dir.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn(forbidden, source, msg=str(path))

    def test_worker_does_not_import_api_auth(self) -> None:
        worker_paths = list((REPO_ROOT / "worker").rglob("*.py"))
        if not worker_paths:
            self.skipTest("No worker package present.")
        for path in worker_paths:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("api.auth", source, msg=str(path))
            self.assertNotIn("fastapi.security", source, msg=str(path))

    def _assert_package_has_no_imports(self, package: str, forbidden: set[str]) -> None:
        base = REPO_ROOT / package
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        self.assertNotIn(root, forbidden, msg=f"{path}: {alias.name}")
                if isinstance(node, ast.ImportFrom) and node.module:
                    root = node.module.split(".")[0]
                    self.assertNotIn(root, forbidden, msg=f"{path}: {node.module}")


if __name__ == "__main__":
    unittest.main()
