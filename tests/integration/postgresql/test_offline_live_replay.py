"""PostgreSQL offline replay integration for persisted live run shape."""

from __future__ import annotations

import os
import unittest

from tests.integration.postgresql.offline_replay_harness import (
    DEFAULT_SOURCE_RUN_ID,
    execute_offline_replay,
    load_source_snapshot,
    _engine,
    _design_from_snapshot,
)
from tests.integration.postgresql.helpers import (
    PostgreSQLIntegrationTestCase,
    integration_tests_enabled,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "PostgreSQL integration tests require POSTGRESQL_INTEGRATION_TESTS=1.",
)
class OfflineLiveReplayPostgreSQLTests(PostgreSQLIntegrationTestCase):
    def test_offline_replay_from_source_or_fixture_shape(self) -> None:
        source_run_id = os.environ.get("SOURCE_RUN_ID", DEFAULT_SOURCE_RUN_ID)
        source_url = os.environ.get("DATABASE_URL")
        if not source_url:
            self.skipTest("DATABASE_URL is required for offline replay source reads")

        source_engine = _engine(source_url)
        try:
            source = load_source_snapshot(source_engine, source_run_id)
        except LookupError:
            self.skipTest(f"Source run {source_run_id} not found in DATABASE_URL database")

        metrics = execute_offline_replay(
            source_engine=source_engine,
            replay_session_factory=self.session_factory,
            source_run_id=source_run_id,
            report_max_sections=12,
            review_max_calls=7,
        )

        self.assertLessEqual(metrics.replay_section_count, 12)
        self.assertLessEqual(metrics.semantic_review_calls, 7)
        self.assertLess(metrics.replay_issue_count, max(metrics.source_issue_count, 1))
        self.assertTrue(metrics.contradiction_acknowledged)
        self.assertTrue(metrics.issues_below_original)
        self.assertEqual(
            len(metrics.rq_coverage),
            len(_design_from_snapshot(source["snapshot"]).research_questions),
        )
        for row in metrics.rq_coverage:
            self.assertGreaterEqual(row["substantive_section_count"], 1)


if __name__ == "__main__":
    unittest.main()
