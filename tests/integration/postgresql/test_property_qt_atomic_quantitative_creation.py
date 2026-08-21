from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.quantitative.workflow import build_quantitative_workflow_template
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import (
    create_test_engine,
    integration_tests_enabled,
    postgresql_application_config,
    reset_schema,
)


@unittest.skipUnless(
    integration_tests_enabled(),
    "QT PostgreSQL proof requires POSTGRESQL_INTEGRATION_TESTS=1 and a test database",
)
class PropertyQtPostgreSQLCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_test_engine()
        reset_schema(self.engine)
        self.addCleanup(self.engine.dispose)

    def _container(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=True,
                background_execution_mode="external",
            ),
            overrides=ApplicationOverrides(
                llm_client=create_brief_aligned_llm_mock()
            ),
        )
        self.addCleanup(container.shutdown)
        return container

    def test_two_studies_and_restart_replay_reuse_one_template(self):
        first = self._container()
        first_study = first.quantitative_ui_service.create_study(
            owner_id="qt-owner",
            title="First",
            description="durable",
            submission_key="qt-pg-first",
        )
        second_study = first.quantitative_ui_service.create_study(
            owner_id="qt-owner",
            title="Second",
            description="durable",
            submission_key="qt-pg-second",
        )
        self.assertNotEqual(first_study.study_id, second_study.study_id)
        self.assertEqual(
            first.workflow_service.get_template(
                build_quantitative_workflow_template().id
            ),
            build_quantitative_workflow_template(),
        )
        first.shutdown()

        restarted = self._container()
        replay = restarted.quantitative_ui_service.create_study(
            owner_id="qt-owner",
            title="First",
            description="durable",
            submission_key="qt-pg-first",
        )
        self.assertEqual(replay.study_id, first_study.study_id)
        self.assertEqual(
            len(restarted.project_service.list_projects(owner_principal_id="qt-owner")),
            2,
        )
        self.assertEqual(
            len(restarted.workflow_service.list_workflow_runs_for_project(first_study.project_id)),
            1,
        )

    def test_run_failure_leaves_no_postgresql_project_or_run(self):
        container = self._container()
        service = container.quantitative_ui_service
        with patch.object(
            service.workflows,
            "create_workflow_run",
            side_effect=RuntimeError("synthetic durable failure"),
        ):
            with self.assertRaises(RuntimeError):
                service.create_study(
                    owner_id="qt-failure-owner",
                    title="Failure",
                    description="durable",
                    submission_key="qt-pg-failure",
                )
        self.assertEqual(
            container.project_service.list_projects(
                owner_principal_id="qt-failure-owner"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
