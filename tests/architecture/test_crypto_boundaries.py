from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class CryptoBoundaryTests(unittest.TestCase):

    def test_application_does_not_import_hashlib_hmac_or_secrets(self) -> None:
        forbidden = {"hashlib", "hmac", "secrets"}
        violations: list[str] = []
        for path in (REPO_ROOT / "application").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in forbidden:
                            violations.append(f"{path.relative_to(REPO_ROOT)} -> {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] in forbidden:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)} -> {node.module}",
                        )
        self.assertEqual(violations, [])

    def test_application_services_do_not_import_infrastructure_security(self) -> None:
        violations: list[str] = []
        for path in (REPO_ROOT / "application" / "services").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "infrastructure.security" in source:
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(violations, [])

    def test_infrastructure_does_not_reexport_application_crypto(self) -> None:
        security_dir = REPO_ROOT / "infrastructure" / "security"
        if not security_dir.exists():
            self.skipTest("No infrastructure security package.")
        for path in security_dir.glob("*.py"):
            if path.name == "__init__.py":
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "from application.security.api_key_material",
                source,
                msg=str(path),
            )


if __name__ == "__main__":
    unittest.main()
