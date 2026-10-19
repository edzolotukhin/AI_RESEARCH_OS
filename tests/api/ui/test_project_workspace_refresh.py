from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]


class ProjectWorkspaceRefreshTests(unittest.TestCase):
    def test_replacement_launch_must_navigate_to_new_run_overview(self):
        handler = (ROOT / "api/routers/ui_projects.py").read_text(encoding="utf-8")
        self.assertIn(
            'return RedirectResponse(f"/ui/research/{run.id}/overview", status_code=303)',
            handler,
        )
        self.assertIn("run = _facade(request).retry_desk(project_id)", handler)

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

    def test_run_overview_contains_polling_root_for_new_nonterminal_run(self):
        template = (ROOT / "api/templates/research/workbench_overview.html").read_text(encoding="utf-8")
        self.assertIn('id="desk-live-root"', template)
        self.assertIn('data-run-id="{{ view.header.run_id }}"', template)
        self.assertIn('data-execution-status="{{ view.header.execution_status }}"', template)


if __name__ == "__main__":
    unittest.main()
