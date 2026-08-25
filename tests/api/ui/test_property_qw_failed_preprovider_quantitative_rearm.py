from __future__ import annotations

from dataclasses import replace
import unittest

from domain.quantitative.workflow import QuantitativeRunRearmEvent
from domain.value_objects.task_status import TaskStatus
from domain.workflow_status import WorkflowStatus
from tests.api.helpers import ApiTestCase
from tests.application.quantitative.test_property_qa_byte_to_statistic_provenance import (
    xlsx_bytes,
)
from tests.fixtures.quantitative.sav_sample_fixture import sav_sample_bytes


class PropertyQwFailedPreProviderQuantitativeRearmTests(ApiTestCase):
    def _principal(self) -> str:
        return self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext
        ).principal_id

    def _create_uploaded(self, key: str):
        created = self.client.post(
            "/ui/quantitative/studies",
            data={
                "title": "QW synthetic recovery",
                "description": "offline only",
                "submission_key": key,
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        study_id = created.headers["location"].rsplit("/", 1)[-1]
        uploaded = self.client.post(
            f"/ui/quantitative/studies/{study_id}/dataset",
            files={
                "dataset": (
                    "initial.sav",
                    sav_sample_bytes(),
                    "application/octet-stream",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(uploaded.status_code, 303)
        return self.container.quantitative_ui_service.get(
            study_id,
            owner_id=self._principal(),
        )

    def _fail_preprovider(self, study, *, usage=None, template_id=None):
        workflows = self.container.workflow_service
        run = workflows.get_workflow_run(study.run_id)
        run.resume()
        failed_task = run.tasks[0]
        failed_task.ready()
        failed_task.start()
        failed_task.fail()
        run.fail()
        if template_id is not None:
            run = replace(run, workflow_template_id=template_id)
        zero_usage = {
            "total_llm_calls": 0,
            "stages": {
                "quant_findings": {"llm_calls": 0},
                "quant_insights": {"llm_calls": 0},
                "quant_report": {"llm_calls": 0},
            },
        }
        workflows.save_workflow_run(
            run,
            expected_version=workflows.get_workflow_run_version(run.id),
            task_results={
                "_run_usage_summary": usage if usage is not None else zero_usage,
                "failure": "synthetic pre-provider failure",
            },
        )
        return run

    def _rearm(self, study_id: str, reason: str = "Replace unreadable protected payload"):
        return self.client.post(
            f"/ui/quantitative/studies/{study_id}/rearm",
            data={"reason": reason},
            follow_redirects=False,
        )

    @staticmethod
    def _replacement_bytes() -> bytes:
        return xlsx_bytes(
            ["respondent_id", "sex", "age", "region", "choice", "score", "nps"],
            [
                ["r1", "F", "18-34", "North", "A", 7, 10],
                ["r2", "M", "35-54", "South", "B", 6, 8],
                ["r3", "F", "35-54", "North", "A", 8, 9],
                ["r4", "M", "18-34", "South", "B", 5, 6],
            ],
        )

    def test_eligible_run_rearms_idempotently_and_survives_reload(self):
        study = self._create_uploaded("qw-eligible")
        original_project, original_run = study.project_id, study.run_id
        failed = self._fail_preprovider(study)

        response = self._rearm(study.study_id)
        self.assertEqual(response.status_code, 303)
        current = self.container.quantitative_ui_service.get(
            study.study_id,
            owner_id=self._principal(),
        )
        rearmed = self.container.workflow_service.get_workflow_run(study.run_id)
        self.assertEqual((current.project_id, current.run_id), (original_project, original_run))
        self.assertIs(rearmed.status, WorkflowStatus.PAUSED)
        self.assertTrue(all(task.status is TaskStatus.CREATED for task in rearmed.tasks))
        self.assertEqual(self.container.workflow_service.get_task_results(study.run_id), {})
        self.assertIsNone(current.qc_record_id)
        self.assertIsNone(current.weight_set_record_id)
        self.assertIsNone(current.terminal_result_record_id)
        self.assertEqual(current.state, "IMPORTED")
        self.assertFalse(self.container.worker_execution_service.process_once("qw-worker"))

        events = self.container.quantitative_ui_service.state.list_for_run(
            study.run_id,
            project_id=study.project_id,
            expected_type=QuantitativeRunRearmEvent,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].previous_status, WorkflowStatus.FAILED.value)
        self.assertIn((failed.tasks[0].definition_id, TaskStatus.FAILED.value), events[0].previous_task_statuses)

        replay = self._rearm(study.study_id)
        self.assertEqual(replay.status_code, 303)
        self.assertEqual(
            len(self.container.quantitative_ui_service.state.list_for_run(
                study.run_id,
                project_id=study.project_id,
                expected_type=QuantitativeRunRearmEvent,
            )),
            1,
        )
        revision = current.revision
        self.container.quantitative_ui_service._studies.clear()
        recovered = self.container.quantitative_ui_service.get(
            study.study_id,
            owner_id=self._principal(),
        )
        self.assertEqual(recovered.revision, revision)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study.run_id).status,
            WorkflowStatus.PAUSED,
        )
        self.assertEqual(self.container._test_llm_client.generate.call_count, 0)

    def test_rearm_allows_explicit_qu_replacement_without_new_run(self):
        study = self._create_uploaded("qw-qu")
        old_dataset_record = study.dataset_record_id
        self._fail_preprovider(study)
        self.assertEqual(self._rearm(study.study_id).status_code, 303)

        replaced = self.client.post(
            f"/ui/quantitative/studies/{study.study_id}/dataset",
            data={"replace_existing": "true"},
            files={
                "dataset": (
                    "replacement.xlsx",
                    self._replacement_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(replaced.status_code, 303)
        current = self.container.quantitative_ui_service.get(
            study.study_id,
            owner_id=self._principal(),
        )
        self.assertEqual((current.project_id, current.run_id), (study.project_id, study.run_id))
        self.assertNotEqual(current.dataset_record_id, old_dataset_record)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(study.run_id).status,
            WorkflowStatus.PAUSED,
        )

    def test_wrong_owner_and_non_quantitative_run_fail_closed(self):
        study = self._create_uploaded("qw-guards")
        self._fail_preprovider(study)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.container.quantitative_ui_service.rearm_failed_run(
                study.study_id,
                owner_id="wrong-owner",
                actor_id="wrong-owner",
                reason="unauthorized",
            )

        other = self._create_uploaded("qw-non-quant")
        self._fail_preprovider(other, template_id="desk-template")
        response = self._rearm(other.study_id)
        self.assertEqual(response.status_code, 422)
        self.assertIs(
            self.container.workflow_service.get_workflow_run(other.run_id).status,
            WorkflowStatus.FAILED,
        )

    def test_usage_terminal_and_completed_authority_prevent_rearm(self):
        used = self._create_uploaded("qw-used")
        usage = {
            "total_llm_calls": 1,
            "stages": {"quant_findings": {"llm_calls": 1}},
        }
        self._fail_preprovider(used, usage=usage)
        self.assertEqual(self._rearm(used.study_id).status_code, 422)

        terminal = self._create_uploaded("qw-terminal")
        self._fail_preprovider(terminal)
        service = self.container.quantitative_ui_service
        service._save(replace(terminal, terminal_result_record_id="accepted-terminal"))
        self.assertEqual(self._rearm(terminal.study_id).status_code, 422)

        completed = self._create_uploaded("qw-completed")
        workflows = self.container.workflow_service
        run = workflows.get_workflow_run(completed.run_id)
        run.resume()
        run.complete()
        workflows.save_workflow_run(
            run,
            expected_version=workflows.get_workflow_run_version(run.id),
        )
        self.assertEqual(self._rearm(completed.study_id).status_code, 422)


if __name__ == "__main__":
    unittest.main()
