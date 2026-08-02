from __future__ import annotations

import unittest

from application.report.deduplication import (
    DR06_RESEARCH_REPORT_TYPE,
    compute_artifact_deduplication_key,
    compute_report_deduplication_key,
)


class ReportDeduplicationTests(unittest.TestCase):
    def test_report_key_is_run_scoped_not_title_scoped(self) -> None:
        key_a = compute_report_deduplication_key(
            workflow_run_id="run-1",
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method="deterministic",
        )
        key_b = compute_report_deduplication_key(
            workflow_run_id="run-1",
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method="deterministic",
        )
        key_other_title = compute_report_deduplication_key(
            workflow_run_id="run-1",
            report_type="research_report",
            generation_method="deterministic",
        )
        key_other_run = compute_report_deduplication_key(
            workflow_run_id="run-2",
            report_type=DR06_RESEARCH_REPORT_TYPE,
            generation_method="deterministic",
        )

        self.assertEqual(key_a, key_b)
        self.assertEqual(key_a, key_other_title)
        self.assertNotEqual(key_a, key_other_run)

    def test_artifact_key_ignores_filename_and_report_id(self) -> None:
        key_a = compute_artifact_deduplication_key(
            workflow_run_id="run-1",
            artifact_type=DR06_RESEARCH_REPORT_TYPE,
        )
        key_b = compute_artifact_deduplication_key(
            workflow_run_id="run-1",
            artifact_type=DR06_RESEARCH_REPORT_TYPE,
        )
        key_other_run = compute_artifact_deduplication_key(
            workflow_run_id="run-2",
            artifact_type=DR06_RESEARCH_REPORT_TYPE,
        )

        self.assertEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_other_run)


if __name__ == "__main__":
    unittest.main()
