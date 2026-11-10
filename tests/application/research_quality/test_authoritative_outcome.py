import unittest
from types import SimpleNamespace

from application.research_quality.authoritative_outcome import derive_authoritative_outcome


class AuthoritativeOutcomeCoverageTests(unittest.TestCase):
    def _finding(self, need):
        return SimpleNamespace(
            project_id="p1", workflow_run_id="r1", research_design_id="d1",
            information_need_refs=(need,), evidence_refs=(f"e-{need}",),
            metadata={"validation_status": "validated"},
        )

    def _evidence(self, need):
        return SimpleNamespace(
            id=f"e-{need}", project_id="p1", workflow_run_id="r1",
            research_design_id="d1", information_need_refs=(need,),
        )

    def test_coverage_missing_keeps_zero_resolved_needs_insufficient(self):
        outcome, unresolved = derive_authoritative_outcome(
            required_information_need_ids=("in-1", "in-2"),
            readiness_payload={"analysis_eligible_information_need_ids": ("in-1",)},
            findings=(), evidence=(), project_id="p1", workflow_run_id="r1",
            research_design_id="d1", coverage_missing_information_need_ids=("in-1", "in-2"),
        )
        self.assertEqual(outcome, "INSUFFICIENT")
        self.assertEqual(unresolved, ("in-1", "in-2"))

    def test_coverage_missing_with_valid_finding_remains_partial(self):
        outcome, unresolved = derive_authoritative_outcome(
            required_information_need_ids=("in-1", "in-2"),
            readiness_payload={"analysis_eligible_information_need_ids": ("in-1", "in-2")},
            findings=(self._finding("in-1"),), evidence=(self._evidence("in-1"),),
            project_id="p1", workflow_run_id="r1", research_design_id="d1",
            coverage_missing_information_need_ids=("in-2",),
        )
        self.assertEqual(outcome, "PARTIAL")
        self.assertEqual(unresolved, ("in-2",))


if __name__ == "__main__":
    unittest.main()
