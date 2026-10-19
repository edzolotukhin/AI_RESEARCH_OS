from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]


class ProjectWorkspaceRefreshTests(unittest.TestCase):
    def test_nonterminal_workspace_exposes_run_and_loads_refresh_script(self):
        template = (ROOT / "api/templates/projects/detail.html").read_text(encoding="utf-8")
        base = (ROOT / "api/templates/projects/base.html").read_text(encoding="utf-8")
        script = (ROOT / "api/static/project-workspace.js").read_text(encoding="utf-8")
        self.assertIn("project-desk-live-root", template)
        self.assertIn("project-workspace.js", base)
        self.assertIn("/status.json", script)
        self.assertIn("window.location.reload()", script)

    def test_terminal_workspace_does_not_expose_refresh_root(self):
        template = (ROOT / "api/templates/projects/detail.html").read_text(encoding="utf-8")
        self.assertIn("view.desk.execution_status != 'TERMINAL'", template)

    def test_refresh_script_keeps_polling_after_transient_error(self):
        script = (ROOT / "api/static/project-workspace.js").read_text(encoding="utf-8")
        self.assertIn("window.setInterval(poll, interval)", script)
        self.assertIn("catch (_) {", script)


if __name__ == "__main__":
    unittest.main()
