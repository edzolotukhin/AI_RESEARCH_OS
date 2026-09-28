"""CMF repeats accepted real DB/API/worker contracts with pinned routing enabled."""
from dataclasses import replace

from application.composition_root import create_application_container
from application.config import ApplicationOverrides
from application.methods.catalog import production_methods
from application.methods.desk.profile import profile, PIN
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from tests.integration.postgresql import test_ark02_desk_worker as legacy
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.application.test_ark02_desk import fixture, Search, Retriever, EmptyLLM


class CMFWorkerTests(legacy.DeskWorkerTests):
    def container(self, llm=None, enabled=True):
        config = replace(postgresql_application_config(), **profile(fixture()[0]),
                         ark_desk_enabled=enabled, cmf_desk_enabled=enabled)
        app = create_application_container(config=config, overrides=ApplicationOverrides(
            llm_client=llm or EmptyLLM(), search_provider=Search(), source_retriever=Retriever()))
        self.addCleanup(app.shutdown)
        app.agency.initialize()
        return app, config

    def submit(self, app, config, enabled=True):
        project = app.project_service.create_project("CMF offline worker replay")
        design = replace(fixture()[1].workflow_template.research_design_snapshot,
                         source_strategy=("web",), analysis_plan=("synthesis",), deliverable_plan=("report",))
        template = ResearchDesignWorkflowMapper(kernel_profile=profile(config) if enabled else None,
            method_binding=production_methods().resolve("DESK", "1") if enabled else None
        ).from_research_design(design, project)
        run_id = app.durable_workflow_service.submit_research(project, template).workflow_run.id
        if enabled:
            self.assertEqual(self.results(run_id)[PIN]["cmf"]["identity"]["method_id"], "DESK")
        return run_id

    def test_pin_survives_repository_save_and_cannot_be_injected_into_history(self):
        app, config = self.container()
        run_id = self.submit(app, config)
        before = self.results(run_id)[PIN]
        run = app.workflow_service.get_workflow_run(run_id)
        app.workflow_service.save_workflow_run(run, task_results={PIN: {"version": 99}})
        self.assertEqual(self.results(run_id)[PIN], before)
        historical = self.submit(app, config, enabled=False)
        run = app.workflow_service.get_workflow_run(historical)
        app.workflow_service.save_workflow_run(run, task_results={PIN: before})
        self.assertNotIn(PIN, self.results(historical))
