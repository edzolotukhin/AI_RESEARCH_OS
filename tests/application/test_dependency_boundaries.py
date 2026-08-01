import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_PREFIXES = ("application.", "infrastructure.", "agency.")
SQLALCHEMY_MARKERS = ("sqlalchemy", "psycopg", "alembic")


def _python_files(relative_dir: str) -> list[Path]:
    root = REPO_ROOT / relative_dir
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _imports_from_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    return imports


def _assert_no_imports_matching(
    test_case: unittest.TestCase,
    files: list[Path],
    forbidden_prefixes: tuple[str, ...],
    label: str,
) -> None:
    violations: list[str] = []

    for path in files:
        for imported in _imports_from_file(path):
            if any(
                imported == prefix.rstrip(".")
                or imported.startswith(prefix)
                for prefix in forbidden_prefixes
            ):
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {imported}")

    test_case.assertEqual(
        violations,
        [],
        f"{label} must not import forbidden modules:\n" + "\n".join(violations),
    )


class DependencyBoundaryTests(unittest.TestCase):

    def test_domain_does_not_import_application_or_infrastructure(self) -> None:
        _assert_no_imports_matching(
            self,
            _python_files("domain"),
            FORBIDDEN_PREFIXES,
            "domain",
        )

    def test_application_services_do_not_import_infrastructure(self) -> None:
        _assert_no_imports_matching(
            self,
            _python_files("application/services"),
            ("infrastructure.",),
            "application.services",
        )

    def test_agency_does_not_import_infrastructure(self) -> None:
        agency_files = [REPO_ROOT / "agency" / "agency.py"]
        _assert_no_imports_matching(
            self,
            agency_files,
            ("infrastructure.",),
            "agency",
        )

    def test_agency_does_not_import_repository_ports(self) -> None:
        agency_files = [REPO_ROOT / "agency" / "agency.py"]
        _assert_no_imports_matching(
            self,
            agency_files,
            ("application.ports.",),
            "agency",
        )

    def test_workflow_engine_does_not_import_persistence_infrastructure(self) -> None:
        engine_files = [REPO_ROOT / "application" / "workflow_engine.py"]
        _assert_no_imports_matching(
            self,
            engine_files,
            ("infrastructure.", "application.ports.execution_log_store"),
            "workflow_engine",
        )

    def test_domain_does_not_import_sqlalchemy_or_postgresql(self) -> None:
        violations: list[str] = []
        for path in _python_files("domain"):
            for imported in _imports_from_file(path):
                root = imported.split(".")[0]
                if root in SQLALCHEMY_MARKERS:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} -> {imported}"
                    )
        self.assertEqual(violations, [])

    def test_application_does_not_import_sqlalchemy(self) -> None:
        violations: list[str] = []
        for path in _python_files("application"):
            for imported in _imports_from_file(path):
                root = imported.split(".")[0]
                if root in SQLALCHEMY_MARKERS:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} -> {imported}"
                    )
        self.assertEqual(violations, [])

    def test_postgresql_adapters_confined_to_infrastructure(self) -> None:
        allowed_roots = (
            REPO_ROOT / "infrastructure",
            REPO_ROOT / "tests",
            REPO_ROOT / "alembic",
        )
        violations: list[str] = []
        for path in REPO_ROOT.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            if any(path.is_relative_to(root) for root in allowed_roots):
                continue
            if path.name == "composition_root.py":
                continue
            for imported in _imports_from_file(path):
                if "infrastructure.persistence.postgresql" in imported:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} -> {imported}"
                    )
        self.assertEqual(violations, [])

    def test_api_does_not_import_infrastructure_adapters(self) -> None:
        _assert_no_imports_matching(
            self,
            _python_files("api"),
            ("infrastructure.", "application.ports."),
            "api",
        )

    def test_domain_and_application_do_not_import_fastapi(self) -> None:
        violations: list[str] = []
        for relative in ("domain", "application"):
            for path in _python_files(relative):
                for imported in _imports_from_file(path):
                    if imported == "fastapi" or imported.startswith("fastapi."):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)} -> {imported}"
                        )
        self.assertEqual(violations, [])

    def test_fastapi_imports_confined_to_api_package(self) -> None:
        violations: list[str] = []
        for path in REPO_ROOT.rglob("*.py"):
            if path.is_relative_to(REPO_ROOT / "tests"):
                continue
            if path.is_relative_to(REPO_ROOT / "api"):
                continue
            for imported in _imports_from_file(path):
                if imported == "fastapi" or imported.startswith("fastapi."):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} -> {imported}"
                    )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
