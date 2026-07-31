import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_PREFIXES = ("application.", "infrastructure.", "agency.")


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


if __name__ == "__main__":
    unittest.main()
