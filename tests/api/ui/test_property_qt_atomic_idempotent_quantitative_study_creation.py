from __future__ import annotations

import unittest
from unittest.mock import patch

from application.quantitative.workflow import build_quantitative_workflow_template
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from tests.api.helpers import ApiTestCase, drain_background_runs


class PropertyQtAtomicQuantitativeStudyCreationTests(ApiTestCase):
    def _create(self, key: str, *, title: str = "QT synthetic study"):
        return self.client.post(
            "/ui/quantitative/studies",
            data={"title": title, "description": "QT offline", "submission_key": key},
            follow_redirects=False,
        )

    def _service(self):
        return self.container.quantitative_ui_service

    def _repositories(self):
        return (
            self.container.project_service._project_repository,
            self.container.workflow_service._workflow_template_repository,
            self.container.workflow_service._workflow_run_repository,
        )

    def test_first_and_second_studies_reuse_one_immutable_template(self):
        first = self._create("qt-first")
        second = self._create("qt-second")
        self.assertEqual((first.status_code, second.status_code), (303, 303))
        first_id = first.headers["location"].rsplit("/", 1)[-1]
        second_id = second.headers["location"].rsplit("/", 1)[-1]
        self.assertNotEqual(first_id, second_id)
        projects, templates, runs = self._repositories()
        self.assertEqual(len(projects.list()), 2)
        self.assertEqual(len(runs.list_for_project(first_id)), 1)
        self.assertEqual(len(runs.list_for_project(second_id)), 1)
        self.assertEqual(len(templates._templates), 1)
        self.assertEqual(
            templates.get_by_id(build_quantitative_workflow_template().id),
            build_quantitative_workflow_template(),
        )

    def test_replay_survives_cache_loss_without_duplicate_authority(self):
        first = self._create("qt-replay")
        study_id = first.headers["location"].rsplit("/", 1)[-1]
        service = self._service()
        service._studies.clear()
        service._submission_ids.clear()
        replay = self._create("qt-replay")
        self.assertEqual(replay.headers["location"].rsplit("/", 1)[-1], study_id)
        projects, _, runs = self._repositories()
        self.assertEqual(len(projects.list()), 1)
        self.assertEqual(len(runs.list_for_project(study_id)), 1)

    def test_replay_with_changed_request_fails_closed(self):
        first = self._create("qt-conflict")
        study_id = first.headers["location"].rsplit("/", 1)[-1]
        conflict = self._create("qt-conflict", title="Changed title")
        self.assertEqual(conflict.status_code, 422)
        projects, _, runs = self._repositories()
        self.assertEqual(len(projects.list()), 1)
        self.assertEqual(len(runs.list_for_project(study_id)), 1)

    def test_created_run_is_paused_and_not_worker_claimable(self):
        response = self._create("qt-paused")
        study_id = response.headers["location"].rsplit("/", 1)[-1]
        run = self.container.workflow_service.get_workflow_run(study_id)
        self.assertIs(run.status, WorkflowStatus.PAUSED)
        self.assertEqual(drain_background_runs(self.container), 0)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study_id).status,
            WorkflowStatus.PAUSED,
        )

    def test_incompatible_existing_template_fails_before_project_creation(self):
        projects, templates, runs = self._repositories()
        expected = build_quantitative_workflow_template()
        templates.save_snapshot(
            WorkflowTemplate(expected.id, "corrupted", []),
            project_id="forensic-template-owner",
        )
        response = self._create("qt-incompatible")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(projects.list(), [])
        self.assertEqual(runs.list_for_project("forensic-template-owner"), [])

    def test_run_creation_failure_compensates_project(self):
        service = self._service()
        projects, _, runs = self._repositories()
        with patch.object(
            service.workflows,
            "create_workflow_run",
            side_effect=RuntimeError("synthetic run failure"),
        ):
            with self.assertRaises(RuntimeError):
                service.create_study(
                    owner_id="owner",
                    title="QT failure",
                    description="offline",
                    submission_key="qt-run-failure",
                )
        self.assertEqual(projects.list(), [])
        self.assertEqual(runs._runs, {})

    def test_projection_failure_compensates_project_and_run(self):
        service = self._service()
        projects, _, runs = self._repositories()
        with patch.object(
            service,
            "_persist_study",
            side_effect=RuntimeError("synthetic projection failure"),
        ):
            with self.assertRaises(RuntimeError):
                service.create_study(
                    owner_id="owner",
                    title="QT failure",
                    description="offline",
                    submission_key="qt-projection-failure",
                )
        self.assertEqual(projects.list(), [])
        self.assertEqual(runs._runs, {})


if __name__ == "__main__":
    unittest.main()
