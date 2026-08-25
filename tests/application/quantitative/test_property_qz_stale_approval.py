from __future__ import annotations

import unittest

from application.quantitative.research_design_authority import QuantitativeResearchDesignError
from tests.application.quantitative.test_property_qz_research_design_authority import PropertyQZResearchDesignAuthorityTests


class PropertyQZStaleApprovalTests(PropertyQZResearchDesignAuthorityTests):
    def test_approval_against_stale_fingerprint_fails_closed(self):
        design = self.design()
        review = self.service.submit_for_review(
            design.version_id, project_id=self.project, run_id=self.run,
            new_version_id="review-stale", actor_id="researcher", changed_at="now",
        )
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "fingerprint is stale"):
            self.service.approve(
                review.version_id, project_id=self.project, run_id=self.run,
                new_version_id="must-not-exist", approval_id="must-not-exist",
                expected_fingerprint="altered", actor_id="owner", decided_at="later",
                rationale="Must fail closed",
            )
        self.assertIsNone(self.repository.get_design("must-not-exist", project_id=self.project))


if __name__ == "__main__": unittest.main()
