from __future__ import annotations

import os
import tempfile
import unittest

from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock


@unittest.skipUnless(os.environ.get("DATABASE_URL"), "PostgreSQL integration database is not configured")
class QuantitativeUiPostgreSQLPersistenceTests(unittest.TestCase):
    def test_safe_study_projection_survives_container_recreation(self):
        with tempfile.TemporaryDirectory() as root:
            config=ApplicationConfig(projects_root=root,persistence_backend="postgresql",database_url=os.environ["DATABASE_URL"],background_execution_mode="external",deterministic_stage_executors=True,search_provider="deterministic")
            first=create_application_container(config=config,overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()))
            study=first.quantitative_ui_service.create_study(owner_id="qo-owner",title="Persistent synthetic study",description="safe metadata",submission_key="qo-pg-restart")
            first.shutdown()
            second=create_application_container(config=config,overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()))
            recovered=second.quantitative_ui_service.get(study.study_id,owner_id="qo-owner")
            self.assertEqual(recovered,study)
            self.assertEqual(second.workflow_service.get_workflow_run(study.run_id).id,study.run_id)
            second.shutdown()


if __name__ == "__main__":
    unittest.main()
