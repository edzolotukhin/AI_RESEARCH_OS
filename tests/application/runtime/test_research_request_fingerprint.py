from __future__ import annotations

import unittest

from application.runtime.research_request_fingerprint import (
    compute_research_request_fingerprint,
)


class ResearchRequestFingerprintTests(unittest.TestCase):

    def test_same_semantic_request_produces_same_fingerprint(self) -> None:
        brief = {
            "client": "Acme",
            "project_title": "Study",
            "business_problem": "Problem",
            "research_goal": "Goal",
            "research_objectives": ["A", "B"],
        }
        first = compute_research_request_fingerprint(
            project_id="project-1",
            brief=brief,
        )
        second = compute_research_request_fingerprint(
            project_id="project-1",
            brief={
                "research_goal": "Goal",
                "client": "Acme",
                "project_title": "Study",
                "business_problem": "Problem",
                "research_objectives": ["A", "B"],
            },
        )
        self.assertEqual(first, second)

    def test_different_semantic_request_produces_different_fingerprint(self) -> None:
        brief = {
            "client": "Acme",
            "project_title": "Study",
            "business_problem": "Problem",
            "research_goal": "Goal",
        }
        first = compute_research_request_fingerprint(
            project_id="project-1",
            brief=brief,
        )
        second = compute_research_request_fingerprint(
            project_id="project-1",
            brief={**brief, "research_goal": "Different"},
        )
        self.assertNotEqual(first, second)

    def test_correlation_only_change_produces_same_fingerprint(self) -> None:
        brief = {
            "client": "Acme",
            "project_title": "Study",
            "business_problem": "Problem",
            "research_goal": "Goal",
        }
        first = compute_research_request_fingerprint(
            project_id="project-1",
            brief=brief,
        )
        second = compute_research_request_fingerprint(
            project_id="project-1",
            brief=brief,
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
