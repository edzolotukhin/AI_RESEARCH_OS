import unittest
from pathlib import Path
from types import SimpleNamespace

from api.ui.method_workflow import qualitative_workflow_guidance


def record(kind, **payload):
    return SimpleNamespace(record_type=kind, payload=payload)


class Ux01cWorkflowGuidanceTests(unittest.TestCase):
    def guidance(self, *records):
        return qualitative_workflow_guidance(records, project_id="project", run_id="run")

    def test_fresh_run_has_one_primary_action(self):
        value = self.guidance()
        self.assertEqual((value.stage, value.action_target), ("Research material", "#participants"))

    def test_prepared_transcript_is_first_class(self):
        value = self.guidance(record("participant"), record("consent", state="eligible"), record("session"))
        self.assertEqual(value.action_label, "Upload prepared transcript")

    def test_resume_derives_review_without_browser_history(self):
        value = self.guidance(record("participant"), record("consent", state="eligible"), record("session"), record("transcript"), record("thematic_revision", status="accepted"), record("qualitative_finding", status="accepted"))
        self.assertEqual((value.stage, value.action_target), ("Review", "#review"))

    def test_final_report_hands_off_to_project_outputs(self):
        value = self.guidance(record("participant"), record("consent", state="eligible"), record("session"), record("transcript"), record("thematic_revision", status="accepted"), record("qualitative_finding", status="accepted"), record("qualitative_approved_revision"), record("qualitative_report_revision", status="final"))
        self.assertEqual((value.state, value.action_target), ("Complete", "/ui/projects/project/outputs"))

    def test_template_targets_actions_and_explains_privacy_safe_source_choice(self):
        template = Path("api/templates/qualitative/detail.html").read_text(encoding="utf-8")
        for target in ("participants", "consent", "sessions", "source-choice", "analysis", "conclusions", "review", "deliverables"):
            self.assertIn(f'id="{target}"', template)
        self.assertIn("підготовлений транскрипт", template.casefold())
        self.assertIn("політикою приватності", template.casefold())
        self.assertIn("захисне обмеження", template.casefold())


if __name__ == "__main__":
    unittest.main()
