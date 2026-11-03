from __future__ import annotations

import unittest
from dataclasses import replace
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from application.authority_extension import AuthorityCompositionError, ComposedAuthorityReader, build_composition
from domain.research_authority import AuthorityExtensionStatus, ResearchAuthorityExtension
from infrastructure.persistence.postgresql.repositories.postgresql_authority_extension_repository import PostgreSQLAuthorityExtensionRepository, PostgreSQLComposedAuthorityRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled
from application.authority_extension.identity import canonical_gap_digest
from application.authority_extension.selected_workflow import (
    SelectedAuthorityExtensionService,
    WorkflowExtensionStateStore,
    derive_gap_contract,
    extension_template_id,
)
from application.persistence.exceptions import DuplicateEntityError
from application.authority_extension.stage_adapters import (
    AuthorityExtensionStageExecutor,
    ExtensionImmutableSourceRepositoryProxy,
    _extension_dispatch,
    _extension_runtime_context,
)
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from application.services.workflow_service import WorkflowService
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.sources.source import Source
from domain.workflow_template import WorkflowTemplate
from runtime.workflow_context import WorkflowContext
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import PostgreSQLWorkflowTemplateRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import PostgreSQLSourceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import PostgreSQLEvidenceRepository
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import PostgreSQLFindingRepository
from infrastructure.evidence.deterministic_evidence_extractor import DeterministicEvidenceExtractor
from tests.application.authority_extension.test_p2_acceptance_harness import _SearchBoundary, _EvidenceBoundary, _AnalysisBoundary
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY

SYNTHETIC_TIMESTAMP = "2025-01-01T00:00:00+00:00"


@unittest.skipUnless(integration_tests_enabled(), "isolated PostgreSQL integration database required")
class PostgreSQLAuthorityExtensionTests(PostgreSQLIntegrationTestCase):
    def setUp(self):
        super().setUp()
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO projects (id,name,status,created_at,updated_at,version) VALUES ('project','P','ACTIVE',:ts,:ts,1)"), {"ts": SYNTHETIC_TIMESTAMP})
            connection.execute(text("INSERT INTO projects (id,name,status,created_at,updated_at,version) VALUES ('foreign-project','F','ACTIVE',:ts,:ts,1)"), {"ts": SYNTHETIC_TIMESTAMP})
            for run_id, project_id in (("parent", "project"), ("extension", "project"),
                                       ("wrong-design", "project"), ("foreign", "foreign-project")):
                connection.execute(text("INSERT INTO workflow_runs (id,project_id,workflow_template_id,status,dependency_graph,task_results,version) VALUES (:id,:project_id,'template','completed',CAST('{}' AS jsonb),CAST('{}' AS jsonb),0)"), {"id": run_id, "project_id": project_id})
        PostgreSQLWorkflowTemplateRepository(self.session_factory).save_snapshot(
            WorkflowTemplate(
                "template", "Parent template", [],
                research_brief_snapshot=ResearchBrief(
                    title="Authority extension fixture",
                    business_question="Close selected authority gaps",
                    timeframe="2021–2022",
                ),
            ),
            project_id="project",
        )

    def test_extension_and_composition_round_trip_and_idempotency(self):
        extensions = PostgreSQLAuthorityExtensionRepository(self.session_factory)
        extension = ResearchAuthorityExtension("ext", "project", "design", "parent", "extension", ("in1", "in2"), "gap", "idem", SYNTHETIC_TIMESTAMP)
        self.assertEqual(extensions.create_or_get(extension), extension)
        self.assertEqual(extensions.create_or_get(extension).extension_id, "ext")
        fresh_extensions = PostgreSQLAuthorityExtensionRepository(DatabaseSessionFactory(self.engine))
        self.assertEqual(fresh_extensions.get_by_id("ext"), extension)
        completed = replace(extension, status=AuthorityExtensionStatus.SUCCEEDED)
        extensions.save(completed)
        self.assertEqual(
            fresh_extensions.get_by_id("ext").status,
            AuthorityExtensionStatus.SUCCEEDED,
        )

        value = build_composition(composition_id="composition", project_id="project", research_design_id="design", parent_source_workflow_run_id="parent", member_workflow_run_ids=("parent", "extension"), selected_information_need_ids=("in1", "in2"), created_at=SYNTHETIC_TIMESTAMP)
        compositions = PostgreSQLComposedAuthorityRepository(self.session_factory)
        self.assertEqual(compositions.create_or_get(value), value)
        self.assertEqual(compositions.create_or_get(value).composition_digest, value.composition_digest)
        fresh = PostgreSQLComposedAuthorityRepository(DatabaseSessionFactory(self.engine)).get_by_id("composition")
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.composition_digest, value.composition_digest)
        self.assertEqual(set(fresh.member_workflow_run_ids), {"parent", "extension"})
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM research_authority_extensions")).scalar_one(), 1)
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM composed_research_authorities")).scalar_one(), 1)
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM composed_research_authority_members")).scalar_one(), 2)

    def test_second_attempt_uses_distinct_immutable_template_and_survives_reload(self):
        def graph(factory):
            workflows = WorkflowService(
                workflow_template_repository=PostgreSQLWorkflowTemplateRepository(factory),
                workflow_run_repository=PostgreSQLWorkflowRunRepository(factory),
                workflow_run_factory=WorkflowRunFactory(TaskFactory()),
            )
            extensions = PostgreSQLAuthorityExtensionRepository(factory)
            return workflows, extensions, SelectedAuthorityExtensionService(
                workflow_service=workflows,
                extension_repository=extensions,
                composed_authority_repository=PostgreSQLComposedAuthorityRepository(factory),
                state_store=WorkflowExtensionStateStore(workflows),
                capability_check=lambda: True,
            )

        design = ResearchDesign("design", (ResearchQuestion("rq", "RQ"),), (
            InformationNeed("in1", "rq", "nominal", timeframe="2021,2022", geography="UA"),
            InformationNeed("in2_real_adjustment", "rq", "retail real-volume", timeframe="2021,2022", geography="UA"),
            InformationNeed("in3", "rq", "trend", timeframe="2021,2022", geography="UA"),
        ))
        selected = ("in1", "in2_real_adjustment", "in3")
        workflows, extensions, service = graph(self.session_factory)
        first = service.start(
            project_id="project", parent_workflow_run_id="parent", design=design,
            selected_information_need_ids=selected,
            idempotency_key="first-attempt", confirmed=True,
        )
        service.fail_technical(first.extension_workflow_run_id, "first attempt failed")
        first_run = workflows.get_workflow_run(first.extension_workflow_run_id)
        first_template = workflows.get_template(first_run.workflow_template_id)

        fresh_factory = DatabaseSessionFactory(self.engine)
        workflows, extensions, service = graph(fresh_factory)
        second = service.start(
            project_id="project", parent_workflow_run_id="parent", design=design,
            selected_information_need_ids=selected,
            idempotency_key="second-attempt", confirmed=True,
        )
        second_run = workflows.get_workflow_run(second.extension_workflow_run_id)
        self.assertNotEqual(second.extension_id, first.extension_id)
        self.assertNotEqual(second_run.id, first_run.id)
        self.assertNotEqual(second_run.workflow_template_id, first_run.workflow_template_id)
        self.assertEqual(workflows.get_template(first_run.workflow_template_id), first_template)
        self.assertEqual(
            extensions.get_by_id(first.extension_id).status,
            AuthorityExtensionStatus.TECHNICAL_ERROR,
        )

        repeated = service.start(
            project_id="project", parent_workflow_run_id="parent", design=design,
            selected_information_need_ids=tuple(reversed(selected)),
            idempotency_key="second-attempt", confirmed=True,
        )
        self.assertEqual(repeated.extension_id, second.extension_id)
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM research_authority_extensions"
            )).scalar_one(), 2)
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM workflow_runs WHERE workflow_template_id LIKE 'desk-authority-extension-v1-%'"
            )).scalar_one(), 2)
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM workflow_templates WHERE id LIKE 'desk-authority-extension-v1-%'"
            )).scalar_one(), 2)

        reloaded_factory = DatabaseSessionFactory(self.engine)
        reloaded_workflows, reloaded_extensions, _ = graph(reloaded_factory)
        self.assertEqual(
            reloaded_extensions.get_by_idempotency_key("project", "second-attempt").extension_id,
            second.extension_id,
        )
        self.assertEqual(
            reloaded_workflows.get_workflow_run(second.extension_workflow_run_id).workflow_template_id,
            second_run.workflow_template_id,
        )
        self.assertEqual(
            reloaded_workflows.get_template(second_run.workflow_template_id).id,
            second_run.workflow_template_id,
        )

        mismatch_key = "mismatched-attempt"
        gaps = derive_gap_contract(design, selected)
        mismatch_id = extension_template_id(
            project_id="project",
            parent_workflow_run_id="parent",
            design_id=design.id,
            gap_contract_digest=canonical_gap_digest([gap.to_dict() for gap in gaps]),
            idempotency_key=mismatch_key,
        )
        PostgreSQLWorkflowTemplateRepository(reloaded_factory).save_snapshot(
            WorkflowTemplate(mismatch_id, "Materially different", []),
            project_id="project",
        )
        with self.assertRaisesRegex(
            DuplicateEntityError,
            f"WorkflowTemplate already exists: {mismatch_id}",
        ):
            service.start(
                project_id="project", parent_workflow_run_id="parent", design=design,
                selected_information_need_ids=selected,
                idempotency_key=mismatch_key, confirmed=True,
            )
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM research_authority_extensions"
            )).scalar_one(), 2)
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM workflow_runs WHERE workflow_template_id=:template_id"
            ), {"template_id": mismatch_id}).scalar_one(), 0)

    def test_composition_rejects_foreign_lineage_and_reader_preserves_owners(self):
        extensions = PostgreSQLAuthorityExtensionRepository(self.session_factory)
        extensions.create_or_get(ResearchAuthorityExtension(
            "ext", "project", "design", "parent", "extension", ("in1",),
            "gap", "idem", SYNTHETIC_TIMESTAMP,
        ))
        extensions.create_or_get(ResearchAuthorityExtension(
            "wrong", "project", "other-design", "parent", "wrong-design", ("in1",),
            "gap", "wrong-idem", SYNTHETIC_TIMESTAMP,
        ))
        compositions = PostgreSQLComposedAuthorityRepository(self.session_factory)
        valid = build_composition(
            composition_id="composition", project_id="project", research_design_id="design",
            parent_source_workflow_run_id="parent",
            member_workflow_run_ids=("parent", "extension"),
            selected_information_need_ids=("in1",), created_at=SYNTHETIC_TIMESTAMP,
        )
        compositions.create_or_get(valid)
        loaded = PostgreSQLComposedAuthorityRepository(
            DatabaseSessionFactory(self.engine),
        ).get_by_id("composition")

        class Item:
            def __init__(self, run_id):
                self.project_id = "project"
                self.workflow_run_id = run_id

        class Repo:
            def list_for_project(self, project_id, *, workflow_run_id=None, **kwargs):
                return [Item(workflow_run_id)] if workflow_run_id in {"parent", "extension"} else []

        reader = ComposedAuthorityReader(Repo(), Repo(), Repo(), Repo())
        self.assertEqual(
            {item.workflow_run_id for item in reader.list_findings(loaded)},
            {"parent", "extension"},
        )
        with self.assertRaises(AuthorityCompositionError):
            reader.validate_member(
                loaded, project_id="project", research_design_id="design",
                workflow_run_id="non-member",
            )

        wrong_design = build_composition(
            composition_id="wrong-design-composition", project_id="project",
            research_design_id="design", parent_source_workflow_run_id="parent",
            member_workflow_run_ids=("parent", "wrong-design"),
            selected_information_need_ids=("in1",), created_at=SYNTHETIC_TIMESTAMP,
        )
        with self.assertRaises(ValueError):
            compositions.create_or_get(wrong_design)

        cross_project = build_composition(
            composition_id="foreign-composition", project_id="project",
            research_design_id="design", parent_source_workflow_run_id="parent",
            member_workflow_run_ids=("parent", "foreign"),
            selected_information_need_ids=("in1",), created_at=SYNTHETIC_TIMESTAMP,
        )
        with self.assertRaises(ValueError):
            compositions.create_or_get(cross_project)

        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO research_authority_extensions "
                    "(extension_id,project_id,research_design_id,parent_source_workflow_run_id,"
                    "extension_workflow_run_id,selected_information_need_ids,gap_contract_digest,"
                    "idempotency_key,created_at,status) VALUES "
                    "('bad','project','design','parent','missing',CAST('[]' AS jsonb),'gap','bad',:ts,'completed')"
                ), {"ts": SYNTHETIC_TIMESTAMP})

    def test_complete_extension_resumes_from_post_evidence_with_fresh_services(self):
        def graph(factory):
            workflows = WorkflowService(
                workflow_template_repository=PostgreSQLWorkflowTemplateRepository(factory),
                workflow_run_repository=PostgreSQLWorkflowRunRepository(factory),
                workflow_run_factory=WorkflowRunFactory(TaskFactory()),
            )
            extensions = PostgreSQLAuthorityExtensionRepository(factory)
            compositions = PostgreSQLComposedAuthorityRepository(factory)
            service = SelectedAuthorityExtensionService(
                workflow_service=workflows, extension_repository=extensions,
                composed_authority_repository=compositions,
                state_store=WorkflowExtensionStateStore(workflows), capability_check=lambda: True,
            )
            return workflows, extensions, compositions, service

        def runtime_context(workflows, run_id):
            run = workflows.get_workflow_run(run_id)
            context = WorkflowContext(
                run,
                Project("project", "P"),
                workflows.get_template(run.workflow_template_id),
            )
            context.services[CHECKPOINT_SERVICE_KEY] = WorkflowRuntimePersister(
                workflow_service=workflows,
                audit=None,
                run_id=run_id,
                initial_version=workflows.get_workflow_run_version(run_id),
                task_results=workflows.get_task_results(run_id),
            )
            return context

        design = ResearchDesign("design", (ResearchQuestion("rq", "RQ"),), (
            InformationNeed("in1", "rq", "nominal", timeframe="2021,2022", geography="UA"),
            InformationNeed("in2_real_adjustment", "rq", "retail real-volume", timeframe="2021,2022", geography="UA"),
            InformationNeed("in3", "rq", "trend", timeframe="2021,2022", geography="UA"),
        ))
        workflows, extensions, _, service = graph(self.session_factory)
        extension = service.start(
            project_id="project", parent_workflow_run_id="parent", design=design,
            selected_information_need_ids=("in1", "in2_real_adjustment", "in3"),
            idempotency_key="pg-complete", confirmed=True,
        )
        service.activate(extension.extension_id)
        run_id = extension.extension_workflow_run_id
        sources, evidence, findings = (
            PostgreSQLSourceRepository(self.session_factory),
            PostgreSQLEvidenceRepository(self.session_factory),
            PostgreSQLFindingRepository(self.session_factory),
        )
        context = runtime_context(workflows, run_id)
        for stage, delegate in (
            ("extension_plan", None), ("extension_search", _SearchBoundary(sources, run_id)),
            ("extension_evidence", _EvidenceBoundary(sources, evidence, run_id)),
        ):
            AuthorityExtensionStageExecutor(stage, service, delegate, evidence, findings).run(context)
        before_budget = service._state(run_id).budget

        fresh_factory = DatabaseSessionFactory(self.engine)
        workflows, extensions, compositions, service = graph(fresh_factory)
        sources, evidence, findings = (
            PostgreSQLSourceRepository(fresh_factory), PostgreSQLEvidenceRepository(fresh_factory),
            PostgreSQLFindingRepository(fresh_factory),
        )
        evidence_count = len(evidence.list_for_project("project", workflow_run_id=run_id))
        service.record_observations(run_id, service._state(run_id).observations)
        self.assertEqual(
            len(evidence.list_for_project("project", workflow_run_id=run_id)),
            evidence_count,
        )
        context = runtime_context(workflows, run_id)
        AuthorityExtensionStageExecutor(
            "extension_readiness", service, None, evidence, findings,
        ).run(context)
        readiness_state = service._state(run_id)
        self.assertTrue(readiness_state.outcomes)
        self.assertEqual(readiness_state.budget, before_budget)

        # A second complete reconstruction proves the pre-Analysis checkpoint
        # is durable rather than retained by the post-Evidence service graph.
        analysis_factory = DatabaseSessionFactory(self.engine)
        workflows, extensions, compositions, service = graph(analysis_factory)
        sources, evidence, findings = (
            PostgreSQLSourceRepository(analysis_factory), PostgreSQLEvidenceRepository(analysis_factory),
            PostgreSQLFindingRepository(analysis_factory),
        )
        context = runtime_context(workflows, run_id)
        self.assertEqual(service._state(run_id).budget, before_budget)
        self.assertTrue(service._state(run_id).outcomes)
        for stage, delegate in (
            ("extension_analysis", _AnalysisBoundary(evidence, findings, run_id)),
            ("extension_finalize", None),
        ):
            AuthorityExtensionStageExecutor(stage, service, delegate, evidence, findings).run(context)
        state = service._state(run_id)
        finding_count = len(findings.list_for_project("project", workflow_run_id=run_id))
        service.record_findings(run_id, state.findings)
        self.assertEqual(
            len(findings.list_for_project("project", workflow_run_id=run_id)),
            finding_count,
        )
        self.assertEqual(state.budget, before_budget)
        self.assertEqual(extensions.get_by_id(extension.extension_id).status, AuthorityExtensionStatus.SUCCEEDED)
        self.assertEqual(len(evidence.list_for_project("project", workflow_run_id=run_id)), 6)
        self.assertEqual(len(findings.list_for_project("project", workflow_run_id=run_id)), 3)
        self.assertIsNotNone(compositions.get_by_id(state.composition_id))
        again = service.finalize(run_id, created_at=SYNTHETIC_TIMESTAMP)
        self.assertEqual(again.composition_digest, state.composition_digest)
        self.assertEqual(again.composition_id, state.composition_id)

    def test_parent_source_selected_by_extension_is_visible_after_repository_reload(self):
        def graph(factory):
            workflows = WorkflowService(
                workflow_template_repository=PostgreSQLWorkflowTemplateRepository(factory),
                workflow_run_repository=PostgreSQLWorkflowRunRepository(factory),
                workflow_run_factory=WorkflowRunFactory(TaskFactory()),
            )
            extensions = PostgreSQLAuthorityExtensionRepository(factory)
            return workflows, SelectedAuthorityExtensionService(
                workflow_service=workflows,
                extension_repository=extensions,
                composed_authority_repository=PostgreSQLComposedAuthorityRepository(factory),
                state_store=WorkflowExtensionStateStore(workflows),
                capability_check=lambda: True,
            )

        design = ResearchDesign(
            "parent-source-design",
            (ResearchQuestion("rq", "What is the market outlook?"),),
            (InformationNeed("in1", "rq", "Need market data"),),
        )
        workflows, service = graph(self.session_factory)
        extension = service.start(
            project_id="project",
            parent_workflow_run_id="parent",
            design=design,
            selected_information_need_ids=("in1",),
            idempotency_key="pg-parent-source-visibility",
            confirmed=True,
        )
        service.activate(extension.extension_id)
        run_id = extension.extension_workflow_run_id
        sources = PostgreSQLSourceRepository(self.session_factory)
        parent_source = Source(
            id="parent-selected-source",
            project_id="project",
            url="https://example.com/parent-source",
            canonical_url="https://example.com/parent-source",
            title="Parent source",
            retrieved_at=SYNTHETIC_TIMESTAMP,
            content_text="Acquired market report body text.",
            content_checksum="parent-source-checksum",
            workflow_run_refs=("parent",),
            research_design_refs=(design.id,),
            information_need_refs=("in1",),
            research_question_refs=("rq",),
            metadata={
                "discovery_records": [
                    {
                        "workflow_run_id": "parent",
                        "research_design_id": design.id,
                        "research_question_id": "rq",
                        "information_need_id": "in1",
                        "query_id": "sq-in1",
                    },
                ],
            },
        )
        sources.create(parent_source)
        before = sources.get_by_id(parent_source.id).to_dict()

        run = workflows.get_workflow_run(run_id)
        results = workflows.get_task_results(run_id)
        results.update(
            {
                "source_acquisition": {"source_ids": [parent_source.id]},
                "research_funnel_v1": {
                    "version": 1,
                    "sequence": 0,
                    "events": [
                        {
                            "kind": "candidate_decision",
                            "source_id": parent_source.id,
                            "target_in": "in1",
                            "reason": "selected",
                        },
                    ],
                    "dropped_events": 0,
                    "observer_errors": 0,
                },
            },
        )
        workflows.save_workflow_run(
            run,
            expected_version=workflows.get_workflow_run_version(run_id),
            task_results=results,
        )

        fresh_factory = DatabaseSessionFactory(self.engine)
        fresh_workflows, fresh_service = graph(fresh_factory)
        fresh_sources = PostgreSQLSourceRepository(fresh_factory)
        evidence = PostgreSQLEvidenceRepository(fresh_factory)
        fresh_run = fresh_workflows.get_workflow_run(run_id)
        context = WorkflowContext(
            fresh_run,
            Project("project", "P"),
            fresh_workflows.get_template(fresh_run.workflow_template_id),
        )
        context.shared_state.update(fresh_workflows.get_task_results(run_id))
        proxy = ExtensionImmutableSourceRepositoryProxy(fresh_sources)
        extraction = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=evidence,
            source_repository=proxy,
        )
        dispatch_token = _extension_dispatch.set((fresh_service, run_id))
        context_token = _extension_runtime_context.set(context)
        try:
            visible = proxy.list_for_project("project", workflow_run_id=run_id)
            summary = extraction.extract_for_context(context)
        finally:
            _extension_runtime_context.reset(context_token)
            _extension_dispatch.reset(dispatch_token)

        self.assertEqual([item.id for item in visible], [parent_source.id])
        self.assertEqual(summary.evidence_extracted, 1)
        self.assertEqual(
            evidence.list_for_project("project", workflow_run_id=run_id)[0].source_id,
            parent_source.id,
        )
        self.assertEqual(fresh_sources.get_by_id(parent_source.id).to_dict(), before)
        self.assertEqual(len(fresh_sources.list_for_project("project")), 1)

    def test_extension_plan_runtime_checkpoint_owns_postgresql_version(self):
        workflows = WorkflowService(
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(self.session_factory),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(self.session_factory),
            workflow_run_factory=WorkflowRunFactory(TaskFactory()),
        )
        extensions = PostgreSQLAuthorityExtensionRepository(self.session_factory)
        service = SelectedAuthorityExtensionService(
            workflow_service=workflows,
            extension_repository=extensions,
            composed_authority_repository=PostgreSQLComposedAuthorityRepository(self.session_factory),
            state_store=WorkflowExtensionStateStore(workflows),
            capability_check=lambda: True,
        )
        design = ResearchDesign("runtime-design", (ResearchQuestion("rq", "RQ"),), (
            InformationNeed("in1", "rq", "nominal", timeframe="2021,2022", geography="UA"),
        ))
        extension = service.start(
            project_id="project",
            parent_workflow_run_id="parent",
            design=design,
            selected_information_need_ids=("in1",),
            idempotency_key="pg-runtime-version",
            confirmed=True,
        )
        service.activate(extension.extension_id)
        run_id = extension.extension_workflow_run_id
        run = workflows.get_workflow_run(run_id)
        task = run.tasks[0]
        task.ready()
        task.start()
        context = WorkflowContext(run, Project("project", "P"), workflows.get_template(run.workflow_template_id))
        context.current_task = task
        persister = WorkflowRuntimePersister(
            workflow_service=workflows,
            audit=None,
            run_id=run_id,
            initial_version=workflows.get_workflow_run_version(run_id),
            task_results=workflows.get_task_results(run_id),
        )
        context.services[CHECKPOINT_SERVICE_KEY] = persister

        persister.on_task_running(context)
        AuthorityExtensionStageExecutor("extension_plan", service).run(context)
        task.complete()
        persister.on_task_finished(context, error=None)

        fresh_workflows = WorkflowService(
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(DatabaseSessionFactory(self.engine)),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(DatabaseSessionFactory(self.engine)),
            workflow_run_factory=WorkflowRunFactory(TaskFactory()),
        )
        self.assertEqual(persister.expected_version, fresh_workflows.get_workflow_run_version(run_id))
        self.assertIn(WorkflowExtensionStateStore.KEY, fresh_workflows.get_task_results(run_id))

    def test_runtime_persister_advances_version_across_multiple_named_results(self):
        workflows = WorkflowService(
            workflow_template_repository=PostgreSQLWorkflowTemplateRepository(self.session_factory),
            workflow_run_repository=PostgreSQLWorkflowRunRepository(self.session_factory),
            workflow_run_factory=WorkflowRunFactory(TaskFactory()),
        )
        run = workflows.get_workflow_run("extension")
        context = WorkflowContext(run, Project("project", "P"), None)
        persister = WorkflowRuntimePersister(
            workflow_service=workflows,
            audit=None,
            run_id=run.id,
            initial_version=workflows.get_workflow_run_version(run.id),
            task_results=workflows.get_task_results(run.id),
        )
        context.services[CHECKPOINT_SERVICE_KEY] = persister

        expected_version = persister.expected_version
        for index in range(1, 4):
            persister.persist_named_result(
                context,
                f"authority_extension_checkpoint_{index}",
                {"sequence": index},
            )
            expected_version += 1
            self.assertEqual(persister.expected_version, expected_version)
            self.assertEqual(workflows.get_workflow_run_version(run.id), expected_version)

        stored_results = workflows.get_task_results(run.id)
        self.assertEqual(
            [stored_results[f"authority_extension_checkpoint_{index}"]["sequence"]
             for index in range(1, 4)],
            [1, 2, 3],
        )
