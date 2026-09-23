from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from application.services.project_planning_service import ProjectPlanningError
from tests.api.helpers import build_test_container


class ActivationCapabilitiesTests(unittest.TestCase):
    def test_memory_mode_serializes_repeated_quantitative_activation(self):
        container = build_test_container(persistence_backend="memory")
        self.addCleanup(container.shutdown)
        project = container.project_service.create_project(
            "Memory project", owner_principal_id="owner",
            selected_methods=("QUANTITATIVE",),
        )
        service = container.quantitative_ui_service
        values = dict(
            project_id=project.id, owner_id="owner", title="Study",
            description="in-process", submission_key="same-key",
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(service.create_quantitative_study_for_project, **values) for _ in range(2)]
            studies = [item.result(timeout=10) for item in futures]
        self.assertEqual(studies[0].study_id, studies[1].study_id)
        self.assertEqual(len(container.workflow_service.list_workflow_runs_for_project(project.id)), 1)

    def test_file_mode_rejects_non_atomic_method_activation(self):
        with tempfile.TemporaryDirectory() as root:
            container = build_test_container(temp_dir=root, persistence_backend="file")
            self.addCleanup(container.shutdown)
            project = container.project_service.create_project(
                "File project", owner_principal_id="owner", selected_methods=("DESK",),
            )
            with self.assertRaisesRegex(ProjectPlanningError, "файловому режимі"):
                container.project_planning_service.activate_desk(project)
            self.assertEqual(container.workflow_service.list_workflow_runs_for_project(project.id), [])
