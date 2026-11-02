from __future__ import annotations

import unittest

from application.authority_extension.stage_adapters import AuthorityExtensionStageExecutor
from application.report.h3_coverage_plan import build_h3_coverage_plan
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.project import Project
from domain.sources.source import Source
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from infrastructure.persistence.memory.in_memory_finding_repository import InMemoryFindingRepository
from infrastructure.persistence.memory.in_memory_insight_repository import InMemoryInsightRepository
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from runtime.workflow_context import WorkflowContext
from tests.application.authority_extension.test_selected_workflow import SelectedAuthorityExtensionTests
from tests.application.authority_extension.test_selected_workflow import _Workflows, _design
from application.authority_extension.selected_workflow import (
    InMemoryExtensionStateStore, SelectedAuthorityExtensionService,
    WorkflowExtensionStateStore,
    _state_from_dict, _state_to_dict,
)
from domain.research_authority import ResearchAuthorityExtension
from infrastructure.persistence.memory.in_memory_authority_extension_repository import InMemoryAuthorityExtensionRepository, InMemoryComposedAuthorityRepository
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY

SYNTHETIC_TIMESTAMP = "2025-01-01T00:00:00+00:00"


class _SearchBoundary:
    def __init__(self, sources, extension_run): self.sources, self.run_id = sources, extension_run
    def run(self, context):
        for need in ("in1", "in2_real_adjustment", "in3"):
            for suffix in ("a", "b"):
                value = Source(
                    f"xs-{need}-{suffix}", "project", f"https://{need}-{suffix}",
                    f"https://{need}-{suffix}", need, SYNTHETIC_TIMESTAMP,
                    information_need_refs=(need,), research_question_refs=("rq",),
                    workflow_run_refs=(self.run_id,), research_design_refs=("design",),
                    content_text=f"{need} 2021 2022", content_checksum=f"c-{need}-{suffix}",
                )
                self.sources.create(value)
        return context


class _EvidenceBoundary:
    def __init__(self, sources, evidence, extension_run):
        self.sources, self.evidence, self.run_id = sources, evidence, extension_run
    def run(self, context):
        for source in self.sources.list_for_project("project", workflow_run_id=self.run_id):
            need = source.information_need_refs[0]
            aspect = (
                "retail_real_volume" if need == "in2_real_adjustment"
                else "nominal_turnover" if need == "in1" else "trend_direction"
            )
            value = Evidence(
                f"xe-{source.id}", "project", source.id, source.content_checksum,
                self.run_id, "design", f"{need} authority", "2021–2022 authority", SYNTHETIC_TIMESTAMP,
                research_question_refs=("rq",), information_need_refs=(need,),
                deduplication_key=f"d-{source.id}", metadata={
                    "observation_period": "2021–2022",
                    "acquired_content_identity": source.canonical_url,
                    "semantic_assignment": {
                        "contract_version": "desk_evidence_candidate_v2",
                        "validation_version": "desk_semantic_assignment_v1",
                        "required_aspect_refs": [aspect],
                        "geography_applicability": ["UA"],
                    },
                },
            )
            self.evidence.create(value)
        return context


class _AnalysisBoundary:
    def __init__(self, evidence, findings, extension_run):
        self.evidence, self.findings, self.run_id = evidence, findings, extension_run
    def run(self, context):
        values = self.evidence.list_for_project("project", workflow_run_id=self.run_id)
        for need in ("in1", "in2_real_adjustment", "in3"):
            refs = tuple(item.id for item in values if need in item.information_need_refs)
            self.findings.create(Finding(
                f"xf-{need}", "project", self.run_id, "design", f"Finding {need}",
                "synthetic validated authority", refs, SYNTHETIC_TIMESTAMP,
                research_question_refs=("rq",), information_need_refs=(need,),
                deduplication_key=f"f-{need}",
            ))
        return context


class P2ProductionShapedAcceptanceTests(SelectedAuthorityExtensionTests):
    def _runtime_graph(self):
        workflows = _Workflows()
        extensions = InMemoryAuthorityExtensionRepository()
        compositions = InMemoryComposedAuthorityRepository(extensions)
        service = SelectedAuthorityExtensionService(
            workflow_service=workflows,
            extension_repository=extensions,
            composed_authority_repository=compositions,
            state_store=WorkflowExtensionStateStore(workflows),
            capability_check=lambda: True,
        )
        extension = service.start(
            project_id="project",
            parent_workflow_run_id="parent",
            design=_design(),
            selected_information_need_ids=("in1", "in2_real_adjustment", "in3"),
            idempotency_key="runtime-lifecycle",
            confirmed=True,
        )
        service.activate(extension.extension_id)
        run_id = extension.extension_workflow_run_id
        run = workflows.get_workflow_run(run_id)
        context = WorkflowContext(run, Project("project", "P"), workflows.templates[0])
        persister = WorkflowRuntimePersister(
            workflow_service=workflows,
            audit=None,
            run_id=run_id,
            initial_version=workflows.get_workflow_run_version(run_id),
            task_results=workflows.get_task_results(run_id),
        )
        context.services[CHECKPOINT_SERVICE_KEY] = persister
        return workflows, extensions, compositions, service, extension, context, persister

    @staticmethod
    def _run_runtime_stage(context, persister, executor):
        task = next(
            item for item in context.workflow_run.tasks
            if item.definition_id == executor.stage
        )
        task.ready()
        task.start()
        context.current_task = task
        persister.on_task_running(context)
        executor.run(context)
        task.complete()
        persister.on_task_finished(context, error=None)

    def test_six_stage_runtime_has_one_workflow_version_owner(self):
        workflows, extensions, compositions, service, extension, context, persister = self._runtime_graph()
        run_id = extension.extension_workflow_run_id
        sources, evidence, findings = (
            InMemorySourceRepository(),
            InMemoryEvidenceRepository(),
            InMemoryFindingRepository(),
        )
        delegates = {
            "extension_search": _SearchBoundary(sources, run_id),
            "extension_evidence": _EvidenceBoundary(sources, evidence, run_id),
            "extension_analysis": _AnalysisBoundary(evidence, findings, run_id),
        }
        for stage in (
            "extension_plan", "extension_search", "extension_evidence",
            "extension_readiness", "extension_analysis", "extension_finalize",
        ):
            self._run_runtime_stage(
                context,
                persister,
                AuthorityExtensionStageExecutor(
                    stage, service, delegates.get(stage), evidence, findings,
                ),
            )
        context.workflow_run.complete()
        persister.on_workflow_finalized(context, error=None)

        self.assertEqual(context.workflow_run.status.value, "completed")
        self.assertEqual(extensions.get_by_id(extension.extension_id).status.value, "succeeded")
        self.assertEqual(len(compositions._items), 1)
        self.assertEqual(persister.expected_version, workflows.get_workflow_run_version(run_id))

    def test_runtime_technical_failure_is_terminal_for_run_and_extension(self):
        workflows, extensions, _, service, extension, context, persister = self._runtime_graph()
        evidence, findings = InMemoryEvidenceRepository(), InMemoryFindingRepository()
        self._run_runtime_stage(
            context, persister,
            AuthorityExtensionStageExecutor("extension_plan", service),
        )

        class FailingSearch:
            def run(self, context):
                raise RuntimeError("deterministic search failure")

        task = next(item for item in context.workflow_run.tasks if item.definition_id == "extension_search")
        task.ready()
        task.start()
        context.current_task = task
        persister.on_task_running(context)
        error = RuntimeError("deterministic search failure")
        with self.assertRaisesRegex(RuntimeError, "deterministic search failure"):
            AuthorityExtensionStageExecutor(
                "extension_search", service, FailingSearch(), evidence, findings,
            ).run(context)
        task.fail()
        context.workflow_run.fail()
        persister.on_task_finished(context, error=error)
        persister.on_workflow_finalized(context, error=error)

        self.assertEqual(context.workflow_run.status.value, "failed")
        stored = extensions.get_by_id(extension.extension_id)
        self.assertEqual(stored.status.value, "technical_error")
        self.assertEqual(stored.terminal_reason, "RuntimeError")
        self.assertEqual(persister.expected_version, workflows.get_workflow_run_version(extension.extension_workflow_run_id))

    def _checkpoint_after_evidence(self, *, evaluate=False):
        sources, evidence, findings = InMemorySourceRepository(), InMemoryEvidenceRepository(), InMemoryFindingRepository()
        run_id = self.extension.extension_workflow_run_id
        self.service.activate(self.extension.extension_id)
        context = WorkflowContext(self.workflows.runs[run_id], Project("project", "P"), self.workflows.templates[0])
        for stage, delegate in (
            ("extension_plan", None), ("extension_search", _SearchBoundary(sources, run_id)),
            ("extension_evidence", _EvidenceBoundary(sources, evidence, run_id)),
        ):
            AuthorityExtensionStageExecutor(stage, self.service, delegate, evidence, findings).run(context)
        if evaluate: self.service.evaluate(run_id)
        payload = _state_to_dict(self.states.load(run_id))
        extension_payload = self.extensions.get_by_id(self.extension.extension_id).to_dict()
        source_payloads = [item.to_dict() for item in sources.list_for_project("project")]
        evidence_payloads = [item.to_dict() for item in evidence.list_for_project("project")]

        workflows = _Workflows()
        template = self.workflows.templates[0]
        workflows.templates.append(template)
        run = WorkflowRunFactory(TaskFactory()).create(template, run_id=run_id, project_id="project")
        run.ready(); run.start()
        workflows.runs[run_id] = run; workflows.results[run_id] = {}; workflows.versions[run_id] = 0
        extensions = InMemoryAuthorityExtensionRepository()
        extensions.create_or_get(ResearchAuthorityExtension(
            extension_payload["extension_id"], extension_payload["project_id"], extension_payload["research_design_id"],
            extension_payload["parent_source_workflow_run_id"], extension_payload["extension_workflow_run_id"],
            tuple(extension_payload["selected_information_need_ids"]), extension_payload["gap_contract_digest"],
            extension_payload["idempotency_key"], extension_payload["created_at"], extension_payload["status"],
            extension_payload["terminal_reason"],
        ))
        states = InMemoryExtensionStateStore(); states.save(_state_from_dict(payload))
        compositions = InMemoryComposedAuthorityRepository(extensions)
        service = SelectedAuthorityExtensionService(
            workflow_service=workflows, extension_repository=extensions,
            composed_authority_repository=compositions, state_store=states,
            capability_check=lambda: True,
        )
        fresh_sources, fresh_evidence, fresh_findings = InMemorySourceRepository(), InMemoryEvidenceRepository(), InMemoryFindingRepository()
        for item in source_payloads: fresh_sources.create(Source.from_dict(item))
        for item in evidence_payloads: fresh_evidence.create(Evidence.from_dict(item))
        fresh_context = WorkflowContext(run, Project("project", "P"), template)
        return service, extensions, states, compositions, fresh_sources, fresh_evidence, fresh_findings, fresh_context

    def _resume_checkpoint(self, *, evaluate=False):
        service, extensions, states, compositions, sources, evidence, findings, context = self._checkpoint_after_evidence(evaluate=evaluate)
        run_id = context.workflow_run.id
        before_sources, before_evidence = len(sources.list_for_project("project")), len(evidence.list_for_project("project"))
        for stage, delegate in (
            ("extension_readiness", None),
            ("extension_analysis", _AnalysisBoundary(evidence, findings, run_id)),
            ("extension_finalize", None),
        ):
            AuthorityExtensionStageExecutor(stage, service, delegate, evidence, findings).run(context)
        self.assertEqual((len(sources.list_for_project("project")), len(evidence.list_for_project("project"))), (before_sources, before_evidence))
        self.assertEqual(len(findings.list_for_project("project", workflow_run_id=run_id)), 3)
        self.assertEqual(extensions.get_by_id(self.extension.extension_id).status.value, "succeeded")
        return states.load(run_id), compositions

    def test_fresh_service_restart_after_evidence(self):
        state, compositions = self._resume_checkpoint(evaluate=False)
        self.assertEqual(state.budget, self.states.load(self.extension.extension_workflow_run_id).budget)
        self.assertEqual(len(compositions._items), 1)

    def test_fresh_service_restart_before_analysis(self):
        state, compositions = self._resume_checkpoint(evaluate=True)
        self.assertTrue(state.outcomes)
        self.assertEqual(len(compositions._items), 1)

    def test_fresh_restart_does_not_bypass_cpi_only_insufficiency(self):
        run_id = self.extension.extension_workflow_run_id
        cpi = [
            self._observation("in2_real_adjustment", "a", kind="cpi"),
            self._observation("in2_real_adjustment", "b", kind="cpi"),
        ]
        self.service.record_observations(run_id, cpi)
        self.service.evaluate(run_id)
        payload = _state_to_dict(self.states.load(run_id))
        stored = self.extensions.get_by_id(self.extension.extension_id)
        workflows = _Workflows(); extensions = InMemoryAuthorityExtensionRepository()
        extensions.create_or_get(stored)
        states = InMemoryExtensionStateStore(); states.save(_state_from_dict(payload))
        compositions = InMemoryComposedAuthorityRepository(extensions)
        fresh = SelectedAuthorityExtensionService(
            workflow_service=workflows, extension_repository=extensions,
            composed_authority_repository=compositions, state_store=states,
            capability_check=lambda: True,
        )
        result = fresh.finalize(run_id, created_at=SYNTHETIC_TIMESTAMP)
        self.assertIsNone(result.composition_id)
        self.assertEqual(extensions.get_by_id(stored.extension_id).status.value, "insufficient")
        self.assertEqual(len(compositions._items), 0)
    def test_real_adapter_chain_preserves_30_19_4_5_and_makes_h3_coverable(self):
        sources, evidence = InMemorySourceRepository(), InMemoryEvidenceRepository()
        findings, insights = InMemoryFindingRepository(), InMemoryInsightRepository()
        for index in range(30):
            sources.create(Source(
                f"ps-{index}", "project", f"https://parent-{index}", f"https://parent-{index}",
                "parent", SYNTHETIC_TIMESTAMP, workflow_run_refs=("parent",), research_design_refs=("design",),
                content_text="parent", content_checksum=f"pc-{index}",
            ))
        for index in range(19):
            evidence.create(Evidence(
                f"pe-{index}", "project", f"ps-{index}", f"pc-{index}", "parent", "design",
                "parent evidence", "parent evidence", SYNTHETIC_TIMESTAMP, deduplication_key=f"pe-{index}",
            ))
        for index in range(4):
            findings.create(Finding(
                f"pf-{index}", "project", "parent", "design", "parent finding", "parent",
                (f"pe-{index}",), SYNTHETIC_TIMESTAMP, deduplication_key=f"pf-{index}",
            ))
        for index in range(5):
            insights.create(Insight(
                f"pi-{index}", "project", "parent", "design", "parent insight", "parent",
                (f"pf-{index % 4}",), SYNTHETIC_TIMESTAMP, deduplication_key=f"pi-{index}",
            ))
        parent_plan = build_h3_coverage_plan(
            design=self.workflows.templates[0].research_design_snapshot,
            required_information_need_ids=self.extension.selected_information_need_ids,
            findings=tuple(findings.list_for_project("project", workflow_run_id="parent")),
            evidence_by_id={item.id: item for item in evidence.list_for_project("project", workflow_run_id="parent")},
            insights=tuple(insights.list_for_project("project", workflow_run_id="parent")),
        )
        self.assertFalse(parent_plan.is_fully_fillable)
        run_id = self.extension.extension_workflow_run_id
        self.service.activate(self.extension.extension_id)
        context = WorkflowContext(
            workflow_run=self.workflows.runs[run_id], project=Project("project", "P"),
            workflow_template=self.workflows.templates[0],
        )
        delegates = {
            "extension_search": _SearchBoundary(sources, run_id),
            "extension_evidence": _EvidenceBoundary(sources, evidence, run_id),
            "extension_analysis": _AnalysisBoundary(evidence, findings, run_id),
        }
        for stage in ("extension_plan", "extension_search", "extension_evidence",
                      "extension_readiness", "extension_analysis", "extension_finalize"):
            AuthorityExtensionStageExecutor(
                stage, self.service, delegates.get(stage), evidence, findings,
            ).run(context)
        stored = self.extensions.get_by_id(self.extension.extension_id)
        self.assertEqual(stored.status.value, "succeeded")
        self.assertEqual((
            len(sources.list_for_project("project", workflow_run_id="parent")),
            len(evidence.list_for_project("project", workflow_run_id="parent")),
            len(findings.list_for_project("project", workflow_run_id="parent")),
            len(insights.list_for_project("project", workflow_run_id="parent")),
        ), (30, 19, 4, 5))
        extension_findings = tuple(findings.list_for_project("project", workflow_run_id=run_id))
        all_evidence = evidence.list_for_project("project", workflow_run_id="parent") + evidence.list_for_project("project", workflow_run_id=run_id)
        composed_plan = build_h3_coverage_plan(
            design=self.workflows.templates[0].research_design_snapshot,
            required_information_need_ids=self.extension.selected_information_need_ids,
            findings=tuple(findings.list_for_project("project", workflow_run_id="parent")) + extension_findings,
            evidence_by_id={item.id: item for item in all_evidence},
            insights=tuple(insights.list_for_project("project", workflow_run_id="parent")),
        )
        self.assertTrue(composed_plan.is_fully_fillable)
        self.assertEqual({slot.information_need_id for slot in composed_plan.coverable_slots}, set(self.extension.selected_information_need_ids))


if __name__ == "__main__": unittest.main()
