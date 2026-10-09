"""New Desk activation and separate worker, real PostgreSQL, offline ports only."""
from dataclasses import replace
import unittest

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.methods.desk.profile import profile, PIN
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from infrastructure.persistence.postgresql.kernel_ownership import KEY
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from tests.application.test_ark02_desk import fixture, Search, Retriever, EmptyLLM
from tests.application.test_ark02_kernel import Crash
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, postgresql_application_config
from tests.api.auth_helpers import auth_headers, bootstrap_test_api_key
from tests.api.helpers import (
    AuthenticatedTestClient,
    close_test_client,
    open_test_client,
    prepare_approved_desk_project,
)
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock


class DeskWorkerTests(PostgreSQLIntegrationTestCase):
    def container(self, llm=None, enabled=True):
        config = replace(postgresql_application_config(), **profile(fixture()[0]), ark_desk_enabled=enabled)
        app = create_application_container(config=config, overrides=ApplicationOverrides(
            llm_client=llm or EmptyLLM(), search_provider=Search(), source_retriever=Retriever()))
        self.addCleanup(app.shutdown)
        app.agency.initialize()
        return app, config

    def submit(self, app, config, enabled=True):
        project = app.project_service.create_project("Offline ARK replay")
        design = fixture()[1].workflow_template.research_design_snapshot
        template = ResearchDesignWorkflowMapper(kernel_profile=profile(config) if enabled else None).from_research_design(design, project)
        context = app.durable_workflow_service.submit_research(project, template)
        return context.workflow_run.id

    def results(self, run_id):
        return PostgreSQLWorkflowRunRepository(self.session_factory).get_task_results(run_id)

    def test_new_pinned_run_real_worker_six_plus_two_and_idempotent_restart(self):
        api, config = self.container()
        run_id = self.submit(api, config)
        pin = self.results(run_id)[PIN]
        llm = EmptyLLM()
        worker, _ = self.container(llm, enabled=False)
        self.assertTrue(worker.worker_execution_service.process_once("ark-worker"))
        results = self.results(run_id)
        self.assertEqual(llm.calls, 8)
        self.assertEqual(results[PIN], pin)
        ledger = results[KEY]
        self.assertEqual(ledger["used"]["initial"], 6)
        self.assertEqual(ledger["used"]["continuation"], 2)
        self.assertEqual(ledger["used"]["extractions"], 8)
        self.assertIn(ledger["terminal"], ("insufficient_budget", "insufficient_opportunities"))
        snapshots = [v["shared_state"] for v in results.values() if isinstance(v, dict) and "shared_state" in v]
        self.assertTrue(any(v.get("research_readiness", {}).get("research_outcome") == "insufficient_research" for v in snapshots))
        self.assertFalse(worker.worker_execution_service.process_once("ark-restarted-worker"))
        self.assertEqual(llm.calls, 8)

    def test_crashed_provider_remains_reserved_after_real_worker_restart(self):
        class CrashingLLM(EmptyLLM):
            def generate(self, prompt, *, options=None):
                self.calls += 1
                raise Crash()
        app, config = self.container()
        run_id = self.submit(app, config)
        crashing = CrashingLLM()
        first, _ = self.container(crashing)
        with self.assertRaises(Crash):
            first.worker_execution_service.process_once("old-worker")
        old = self.results(run_id)
        self.assertEqual(crashing.calls, 1)
        self.assertIsNotNone(old[KEY]["pending"])
        second_llm = EmptyLLM()
        second, _ = self.container(second_llm, enabled=False)
        self.assertTrue(second.worker_execution_service.process_once("new-worker"))
        after = self.results(run_id)
        self.assertEqual(second_llm.calls, 0)
        self.assertEqual(after[PIN], old[PIN])
        self.assertEqual(after[KEY]["terminal"], "reconciliation_required")
        self.assertEqual(after[KEY]["reservations"], old[KEY]["reservations"])

    def test_general_checkpoint_cannot_switch_activation_version(self):
        app, config = self.container()
        run_id = self.submit(app, config)
        original = self.results(run_id)[PIN]
        repo = PostgreSQLWorkflowRunRepository(self.session_factory)
        repo.save(repo.get_by_id(run_id), task_results={PIN: {"version": 99}})
        self.assertEqual(self.results(run_id)[PIN], original)

    def test_structured_retry_is_durably_charged_in_the_same_eight_slots(self):
        api, config = self.container()
        run_id = self.submit(api, config)
        llm = EmptyLLM(invalid_first=True)
        worker, _ = self.container(llm, enabled=False)
        self.assertTrue(worker.worker_execution_service.process_once("retry-worker"))
        ledger = self.results(run_id)[KEY]
        self.assertEqual(llm.calls, 8)
        self.assertEqual(ledger["used"]["extractions"], 8)
        actions = [d for d in ledger["decisions"] if d["action"].startswith("extract:")]
        self.assertEqual(len(actions), 7)
        self.assertEqual([a["ordinal"] for a in actions[0]["attempts"]], [1, 2])
        self.assertEqual(actions[0]["attempts"][1]["reservation"]["extractions"], 2)
        self.assertTrue(actions[0]["attempts"][1]["retry"])

    def test_old_run_is_not_promoted_by_enabled_worker(self):
        app, config = self.container()
        run_id = self.submit(app, config, enabled=False)
        self.assertNotIn(PIN, self.results(run_id))
        app.worker_execution_service.process_once("legacy-worker")
        self.assertNotIn(PIN, self.results(run_id))
        self.assertNotIn(KEY, self.results(run_id))

    def test_authenticated_api_activation_pins_version_for_separate_worker(self):
        api, _ = self.container(create_brief_aligned_llm_mock())
        bootstrap_test_api_key(api)
        raw, _, context = open_test_client(api)
        self.addCleanup(lambda: close_test_client(context, api))
        client = AuthenticatedTestClient(raw, auth_headers(api._test_api_key_plaintext))
        project_id = client.post("/projects", json={"name": "ARK API replay"}).json()["id"]
        prepare_approved_desk_project(api, project_id, CANONICAL_BRIEF_REQUEST)
        response = client.post(
            f"/ui/projects/{project_id}/methods/DESK/activate",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        run_id = api.project_planning_service._desk_run(project_id).id
        pin = self.results(run_id)[PIN]
        llm = EmptyLLM()
        worker, _ = self.container(llm, enabled=False)
        self.assertTrue(worker.worker_execution_service.process_once("api-worker"))
        result = self.results(run_id)
        self.assertEqual(result[PIN], pin)
        self.assertIn(KEY, result)
        self.assertGreater(llm.calls, 0)
        self.assertLessEqual(llm.calls, 8)


if __name__ == "__main__":
    unittest.main()
