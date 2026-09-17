from __future__ import annotations

import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.helpers import create_test_engine, integration_tests_enabled, postgresql_application_config, reset_schema


@unittest.skipUnless(integration_tests_enabled(), "PF-01 PostgreSQL proof requires the disposable test database")
class Pf01ProjectBoundQuantitativePostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine(); reset_schema(self.engine); self.addCleanup(self.engine.dispose)
    def _container(self):
        value = create_application_container(
            config=postgresql_application_config(deterministic_stage_executors=True, background_execution_mode="external"),
            overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()))
        self.addCleanup(value.shutdown); return value
    def test_distinct_relationship_and_replay_survive_restart(self):
        first = self._container()
        project = first.project_service.create_project("PF-01", owner_principal_id="owner")
        study = first.quantitative_ui_service.create_quantitative_study_for_project(
            project_id=project.id, owner_id="owner", title="Study", description="durable", submission_key="key")
        self.assertEqual(len({project.id, study.study_id, study.run_id}), 3)
        first.shutdown()
        restarted = self._container()
        replay = restarted.quantitative_ui_service.create_quantitative_study_for_project(
            project_id=project.id, owner_id="owner", title="Study", description="durable", submission_key="key")
        self.assertEqual(replay, study)
        self.assertEqual(restarted.quantitative_ui_service.get(study.study_id, owner_id="owner"), study)


if __name__ == "__main__": unittest.main()
