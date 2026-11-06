import ast
from pathlib import Path


def test_read_only_diagnostic_script_parses_without_side_effects():
    path = Path(__file__).with_name("p8d_desk_postgres_diagnostic.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert tree.body
    assert "TRUNCATE" not in path.read_text(encoding="utf-8").upper()
    assert "DROP DATABASE" not in path.read_text(encoding="utf-8").upper()
