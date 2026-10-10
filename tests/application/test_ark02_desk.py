"""Real Desk services and adapter with deterministic provider ports, no network."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch
from uuid import UUID

from application.config import ApplicationConfig, ApplicationOverrides
from application.methods.desk.adapter import DeskAdapter
from application.methods.desk.primitives import DeskPrimitives
from application.methods.desk.profile import profile, PIN, template_marker
from application.methods.desk.executor import VersionedDeskExecutor
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.research_kernel.controller import Controller
from application.research_kernel.contracts import Stop, OutcomeKind
from application.execution.execution_budget_factory import create_execution_budget
from application.execution.execution_budget_context import execution_budget_scope
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from application.sources.search_factory import build_source_acquisition_service
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.research_quality.research_readiness_service import ResearchReadinessService
from application.research_quality.deterministic_research_sufficiency_evaluator import DeterministicResearchSufficiencyEvaluator
from application.ports.source_ports import SearchProvider, SourceRetriever
from domain.ai.llm_response import LLMResponse
from domain.planning.research_design import ResearchDesign, ResearchQuestion, InformationNeed
from domain.project import Project
from domain.sources.source_candidate import SourceCandidate
from domain.sources.source import Source
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.factories.task_factory import TaskFactory
from infrastructure.llm.budget_enforcing_llm_client import BudgetEnforcingLLMClient
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import InMemoryEvidenceRepository
from runtime.workflow_context import WorkflowContext
from tests.application.test_ark02_kernel import Store


class Search(SearchProvider):
    def search(self, query):
        return [SourceCandidate("synthetic", f"https://example.test/{query.information_need_id}/{i}",
            "Irrigation meter definitions", "Irrigation meter definitions", query.id, i + 1)
            for i in range(4)]


class Retriever(SourceRetriever):
    def retrieve(self, candidate):
        return Source("", "", candidate.url, candidate.url, candidate.title, "2026-01-01",
            content_text="Irrigation meter definitions. Fictional material " + candidate.url,
            source_type="web")


class EmptyLLM:
    def __init__(self, invalid_first=False):
        self.calls = 0
        self.invalid_first = invalid_first

    def generate(self, prompt, *, options=None):
        self.calls += 1
        return LLMResponse(content="invalid" if self.invalid_first and self.calls == 1 else '{"items":[]}',
                           finish_reason="stop")


class Checkpoint:
    def __init__(self):
        self.snapshots = []

    def on_task_progress(self, context):
        self.snapshots.append(deepcopy(context.shared_state))


def fixture(*, invalid_first=False):
    config = ApplicationConfig(ark_desk_enabled=True, persistence_backend="postgresql",
        evidence_max_llm_calls=8, evidence_remediation_reserved_llm_calls=2,
        evidence_remediation_max_llm_calls_per_attempt=1, source_max_sources_per_run=8,
        research_max_gap_rounds_per_run=1, targeted_max_attempts_per_gap=1,
        targeted_max_queries_per_gap=1, targeted_max_sources_per_gap=1,
        llm_max_calls_per_run=24, sufficiency_max_llm_calls=6,
        analysis_max_llm_calls=2, report_max_llm_calls=2, review_max_calls=1,
        search_provider="deterministic", research_sufficiency_assessor="deterministic")
    design = ResearchDesign("design", research_questions=(ResearchQuestion("rq", "Irrigation meter definitions"),),
        information_needs=tuple(InformationNeed(f"in-{i}", "rq", "Irrigation meter definitions") for i in range(2)))
    project = Project("project", "Synthetic irrigation project")
    template = ResearchDesignWorkflowMapper(kernel_profile=profile(config)).from_research_design(design, project)
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(template=template)
    context = WorkflowContext(run, project, template, run.tasks[0])
    context.services[CHECKPOINT_SERVICE_KEY] = Checkpoint()
    context.execution_metadata[PIN] = template_marker(template)
    sources, evidence, llm = InMemorySourceRepository(), InMemoryEvidenceRepository(), EmptyLLM(invalid_first)
    client = BudgetEnforcingLLMClient(llm)
    overrides = ApplicationOverrides(search_provider=Search(), source_retriever=Retriever())
    acquisition = build_source_acquisition_service(config=config, overrides=overrides,
        source_repository=sources, evidence_repository=evidence)
    extraction = build_evidence_extraction_service(config=config, overrides=overrides,
        source_repository=sources, evidence_repository=evidence, llm_client=client)
    readiness = ResearchReadinessService(evaluator=DeterministicResearchSufficiencyEvaluator(),
        evidence_repository=evidence, source_repository=sources)
    adapter = DeskAdapter(context, config, DeskPrimitives(context, acquisition, extraction), readiness, evidence)
    return config, context, sources, evidence, llm, adapter, overrides, client


class DeskReplayTests(unittest.TestCase):
    def test_exhausted_initial_llm_opens_bounded_continuation(self):
        _, _, _, _, _, adapter, _, _ = fixture()
        state = adapter.initial_state()
        state.used["initial"] = 1
        state.used["initial_llm"] = state.limits["initial_llm"]
        actions = adapter.propose(state, adapter.observe(state))
        self.assertTrue(actions)
        self.assertTrue(all("initial_llm" not in dict(action.resources) for action in actions))
        self.assertEqual(state.limits["extractions"], 8)
        self.assertEqual(state.limits["initial"], 6)
        self.assertEqual(state.limits["continuation"], 2)

    def test_expired_acquisition_deadline_is_not_reset_on_restart(self):
        _, context, _, _, llm, adapter, _, _ = fixture()
        context.shared_state["ark_acquisition_deadline"] = 0
        state = adapter.initial_state()
        self.assertFalse(adapter.propose(state, adapter.observe(state)))
        self.assertEqual(Controller(Store(), adapter).run(state).terminal, Stop.SAFETY)
        self.assertEqual(llm.calls, 0)

    def test_no_search_without_feasible_fetch_and_extraction_path(self):
        _, _, _, _, llm, adapter, _, _ = fixture()
        state = adapter.initial_state()
        state.used["initial_acquisitions"] = state.limits["initial_acquisitions"]
        self.assertFalse(adapter.propose(state, adapter.observe(state)))
        self.assertEqual(llm.calls, 0)

    def test_real_desk_prf08s_telemetry_does_not_change_policy(self):
        from application import research_funnel_telemetry as funnel
        from application.research_kernel.telemetry import observe_decision
        results = []
        for enabled in (False, True):
            config, context, _, _, _, adapter, _, _ = fixture()
            context.workflow_run.id = "deterministic-replay"
            context.execution_metadata["research_funnel_enabled"] = enabled
            @funnel.observed("adaptive_kernel")
            def replay(_self, context):
                return Controller(Store(), adapter, observe_decision).run(adapter.initial_state())
            with execution_budget_scope(create_execution_budget(config)), patch(
                    "application.sources.source_acquisition_service.uuid4", side_effect=[UUID(int=i) for i in range(1, 30)]):
                results.append(replay(None, context))
        self.assertEqual(results[0], results[1])

    def test_downstream_uses_the_same_restored_budget(self):
        from application.execution.execution_budget_context import get_execution_budget, EXECUTION_BUDGET_KEY
        config, context, sources, evidence, _, _, overrides, client = fixture()
        executor = VersionedDeskExecutor(None, "search", config=config, overrides=overrides,
            sources=sources, evidence=evidence, llm_client=client, store_factory=lambda c: Store())
        with execution_budget_scope(create_execution_budget(config)):
            executor.run(context)
            self.assertIs(get_execution_budget(), context.execution_metadata[EXECUTION_BUDGET_KEY])
            self.assertEqual(get_execution_budget().stage_calls("evidence"), 8)

    def test_real_desk_six_empty_then_two_continuations_no_fabrication(self):
        config, context, sources, evidence, llm, adapter, _, _ = fixture()
        store = Store()
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(store, adapter).run(adapter.initial_state())
            adapter.finish(result)
        self.assertEqual(llm.calls, 8)
        self.assertEqual(result.used["initial"], 6)
        self.assertEqual(result.used["continuation"], 2)
        self.assertEqual(result.used["extractions"], 8)
        extractions = [d for d in result.decisions if d["action"].startswith("extract:")]
        self.assertEqual(len(extractions), 8)
        self.assertTrue(all(d["outcome"] == OutcomeKind.EMPTY.value for d in extractions))
        self.assertFalse(evidence.list_for_project(context.project.id))
        self.assertFalse(context.shared_state["research_readiness"]["ready_for_analysis"])
        self.assertEqual(context.shared_state["research_readiness"]["research_outcome"], "insufficient_research")
        self.assertTrue(all(task.is_terminal for task in context.workflow_run.tasks[3:]))
        self.assertTrue(extractions[6]["gaps"])
        self.assertEqual(extractions[6]["reservation"]["continuation"], 1)
        self.assertEqual(extractions[7]["reservation"]["continuation"], 1)

    def test_structured_retry_uses_same_eight_call_ceiling(self):
        config, context, _, evidence, llm, adapter, _, _ = fixture(invalid_first=True)
        with execution_budget_scope(create_execution_budget(config)):
            result = Controller(Store(), adapter).run(adapter.initial_state())
        self.assertEqual(llm.calls, 8)
        self.assertEqual(result.used["extractions"], 8)
        extractions = [d for d in result.decisions if d["action"].startswith("extract:")]
        self.assertEqual(len(extractions), 7)
        self.assertEqual(len(extractions[0]["attempts"]), 2)
        self.assertTrue(extractions[0]["attempts"][1]["retry"])
        self.assertFalse(evidence.list_for_project(context.project.id))

    def test_missing_durable_checkpoint_blocks_desk(self):
        _, context, _, _, llm, adapter, _, _ = fixture()
        context.services.clear()
        with self.assertRaises(RuntimeError):
            adapter.checkpoint()
        self.assertEqual(llm.calls, 0)

    def test_legacy_version_not_silently_promoted(self):
        config, context, sources, evidence, llm, _, overrides, client = fixture()
        context.execution_metadata.pop(PIN)
        executor = VersionedDeskExecutor(None, "search", config=config, overrides=overrides,
            sources=sources, evidence=evidence, llm_client=client, store_factory=lambda c: Store())
        with self.assertRaises(RuntimeError):
            executor.run(context)
        self.assertEqual(llm.calls, 0)

    def test_pinned_executor_works_with_new_activation_disabled(self):
        config, context, sources, evidence, llm, _, overrides, client = fixture()
        executor = VersionedDeskExecutor(None, "search", config=replace(config, ark_desk_enabled=False),
            overrides=overrides, sources=sources, evidence=evidence, llm_client=client,
            store_factory=lambda c: Store())
        with execution_budget_scope(create_execution_budget(config)):
            executor.run(context)
        self.assertEqual(llm.calls, 8)
        self.assertIn("ark_stop", context.shared_state)

    def test_changed_version_profile_is_rejected(self):
        config, context, sources, evidence, llm, _, overrides, client = fixture()
        context.execution_metadata[PIN] = {"version": 99, "profile": profile(config)}
        executor = VersionedDeskExecutor(None, "search", config=config, overrides=overrides,
            sources=sources, evidence=evidence, llm_client=client, store_factory=lambda c: Store())
        with self.assertRaises(RuntimeError):
            executor.run(context)
        self.assertEqual(llm.calls, 0)


if __name__ == "__main__":
    unittest.main()
