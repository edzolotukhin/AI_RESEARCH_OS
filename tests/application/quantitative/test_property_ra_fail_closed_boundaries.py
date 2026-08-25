from __future__ import annotations

from dataclasses import replace
import unittest

from application.quantitative.questionnaire_authority import QuantitativeQuestionnaireError
from tests.application.quantitative import test_property_ra_questionnaire_authority as ra_fixture


class PropertyRAFailClosedBoundaryTests(unittest.TestCase):
    def fixture(self):
        value = ra_fixture.PropertyRAQuestionnaireAuthorityTests(methodName="runTest")
        value.setUp()
        return value

    def test_unsupported_question_type_fails_closed(self):
        fixture = self.fixture()
        questions = tuple(replace(item, question_type="RANKING") if item.question_id == "q-brand" else item for item in fixture.questions())
        with self.assertRaisesRegex(QuantitativeQuestionnaireError, "unsupported Questionnaire question type"):
            fixture.create(questions=questions)

    def test_mandatory_not_measured_cannot_be_approved(self):
        fixture = self.fixture()
        questions = tuple(item for item in fixture.questions() if item.question_id != "q-brand")
        draft = fixture.create(questions=questions)
        review = fixture.service.submit_for_review(draft.version_id, project_id=fixture.project, run_id=fixture.run, new_version_id="no-measurement-review", actor_id="researcher", changed_at="later")
        with self.assertRaisesRegex(QuantitativeQuestionnaireError, "mandatory Analytical Requirement"):
            fixture.service.approve(review.version_id, project_id=fixture.project, run_id=fixture.run, new_version_id="must-not-approve", approval_id="must-not-approve", expected_fingerprint=review.fingerprint, expected_validation_fingerprint=review.validation_manifest_fingerprint, expected_coverage_fingerprint=review.coverage_manifest_fingerprint, actor_id="owner", decided_at="later", rationale="Must fail")


if __name__ == "__main__": unittest.main()
