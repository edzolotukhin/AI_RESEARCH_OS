import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = REPO_ROOT / "examples" / "deterministic_research_demo.py"


class DeterministicResearchDemoTests(unittest.TestCase):

    def _run_demo(
        self,
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        run_env = os.environ.copy()
        run_env.pop("OPENAI_API_KEY", None)
        run_env["OPENAI_API_KEY"] = ""

        if env is not None:
            run_env.update(env)

        return subprocess.run(
            [sys.executable, str(DEMO_SCRIPT)],
            cwd=REPO_ROOT,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_demo_exits_zero_without_openai_key(self):
        before = list((REPO_ROOT / "agency" / "projects").glob("**/*"))

        result = self._run_demo()

        after = list((REPO_ROOT / "agency" / "projects").glob("**/*"))

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertEqual(before, after)

        output = result.stdout
        self.assertIn("=== Deterministic Research Workflow Demo ===", output)
        self.assertIn("Workflow status: completed", output)
        self.assertIn(
            "Execution order: collect_sources -> analyze_findings -> build_report",
            output,
        )
        self.assertIn("Task collect_sources: completed", output)
        self.assertIn("Collected 2 source sets", output)
        self.assertIn("Task analyze_findings: completed", output)
        self.assertIn("Awareness stable, loyalty improving", output)
        self.assertIn("Task build_report: completed", output)
        self.assertIn("Report draft ready", output)
        self.assertIn("Final: workflow completed", output)
        self.assertNotIn("openai", output.lower())
        self.assertNotIn("api_key", output.lower())

    def test_demo_output_is_stable_across_runs(self):
        first = self._run_demo().stdout
        second = self._run_demo().stdout

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
