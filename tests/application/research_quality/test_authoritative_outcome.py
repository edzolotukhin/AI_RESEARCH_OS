import unittest
from types import SimpleNamespace

from application.research_quality.authoritative_outcome import derive_authoritative_outcome


def _records(*, design="design", project="project", run="run", needs=("in-1",), valid=True):
    evidence = tuple(SimpleNamespace(
        id=f"e-{need}", project_id=project, workflow_run_id=run,
        research_design_id=design, information_need_refs=(need,),
    ) for need in needs)
    finding = SimpleNamespace(
        project_id=project, workflow_run_id=run, research_design_id=design,
        information_need_refs=needs, evidence_refs=tuple(item.id for item in evidence),
        metadata={"validation_status": "validated" if valid else "rejected"},
    )
    return finding, evidence


class AuthoritativeOutcomeTests(unittest.TestCase):
    def _payload(self, *, required=("in-1",), eligible=None, blocking=()):
        return {
            "analysis_eligible_information_need_ids": list(eligible or required),
            "blocking_information_need_ids": list(blocking),
        }

    def test_all_required_needs_with_validated_lineage_are_completed(self):
        finding, evidence = _records(needs=("in-1", "in-2"))
        self.assertEqual(
            derive_authoritative_outcome(
                required_information_need_ids=("in-1", "in-2"),
                readiness_payload=self._payload(required=("in-1", "in-2")),
                findings=(finding,), evidence=evidence, project_id="project",
                workflow_run_id="run", research_design_id="design",
            ),
            ("COMPLETED", ()),
        )

    def test_partial_and_insufficient_are_distinct(self):
        finding, evidence = _records()
        args = dict(readiness_payload=self._payload(), findings=(finding,), evidence=evidence,
                    project_id="project", workflow_run_id="run", research_design_id="design")
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=("in-1", "in-2"), **args)[0], "PARTIAL")
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=("in-1",), readiness_payload=self._payload(), findings=(), evidence=(), project_id="project", workflow_run_id="run", research_design_id="design")[0], "INSUFFICIENT")

    def test_foreign_or_unvalidated_records_do_not_qualify(self):
        finding, evidence = _records(project="other")
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=("in-1",), readiness_payload=self._payload(), findings=(finding,), evidence=evidence, project_id="project", workflow_run_id="run", research_design_id="design")[0], "INSUFFICIENT")
        finding, evidence = _records(valid=False)
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=("in-1",), readiness_payload=self._payload(), findings=(finding,), evidence=evidence, project_id="project", workflow_run_id="run", research_design_id="design")[0], "INSUFFICIENT")
        finding, evidence = _records()
        finding.metadata = {}
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=("in-1",), readiness_payload=self._payload(), findings=(finding,), evidence=evidence, project_id="project", workflow_run_id="run", research_design_id="design")[0], "INSUFFICIENT")

    def test_missing_readiness_never_fabricates_success(self):
        finding, evidence = _records()
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=("in-1",), readiness_payload=None, findings=(finding,), evidence=evidence, project_id="project", workflow_run_id="run", research_design_id="design")[0], "INSUFFICIENT")

    def test_confirmed_technical_failure_has_precedence(self):
        finding, evidence = _records()
        self.assertEqual(derive_authoritative_outcome(required_information_need_ids=("in-1",), readiness_payload=self._payload(), findings=(finding,), evidence=evidence, project_id="project", workflow_run_id="run", research_design_id="design", technical_failure=True)[0], "FAILED")

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
        finding, evidence = _records(design="d1", project="p1", run="r1")
        outcome, unresolved = derive_authoritative_outcome(
            required_information_need_ids=("in-1", "in-2"),
            readiness_payload={"analysis_eligible_information_need_ids": ("in-1", "in-2")},
            findings=(finding,), evidence=evidence, project_id="p1", workflow_run_id="r1",
            research_design_id="d1", coverage_missing_information_need_ids=("in-2",),
        )
        self.assertEqual(outcome, "PARTIAL")
        self.assertEqual(unresolved, ("in-2",))


if __name__ == "__main__":
    unittest.main()
