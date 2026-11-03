from __future__ import annotations

import unittest
from dataclasses import replace

from application.authority_extension.selected_workflow import (
    EXTENSION_STAGES,
    PROVIDER_BUDGET_MAX,
    SEARCH_BUDGET_MAX,
    AuthorityObservation,
    ExtensionBudgetExceeded,
    ExtensionContractError,
    ExtensionFinding,
    GapOutcome,
    InMemoryExtensionStateStore,
    SelectedAuthorityExtensionService,
    WorkflowExtensionStateStore,
    derive_gap_contract,
    extension_template,
    extension_template_id,
    qualify_gap,
)
from application.authority_extension.identity import canonical_gap_digest
from application.persistence.exceptions import DuplicateEntityError
from domain.planning.research_design import InformationNeed, ResearchDesign, ResearchQuestion
from domain.workflow_run import WorkflowRun
from domain.workflow_template import WorkflowTemplate
from domain.research_brief import ResearchBrief
from infrastructure.persistence.memory.in_memory_authority_extension_repository import (
    InMemoryAuthorityExtensionRepository,
    InMemoryComposedAuthorityRepository,
)
from infrastructure.persistence.memory.in_memory_source_repository import InMemorySourceRepository
from infrastructure.persistence.memory.in_memory_evidence_repository import (
    InMemoryEvidenceRepository,
)
from infrastructure.evidence.deterministic_evidence_extractor import (
    DeterministicEvidenceExtractor,
)
from application.authority_extension.stage_adapters import (
    AuthorityExtensionStageExecutor,
    ExtensionImmutableSourceRepositoryProxy,
    _extension_dispatch,
    _extension_runtime_context,
)
from application.evidence.run_scoped_provenance import resolve_run_scoped_context
from application.evidence.evidence_extraction_service import EvidenceExtractionService
from domain.sources.source import Source
from domain.project import Project
from runtime.workflow_context import WorkflowContext
from application.runtime.workflow_runtime_persister import WorkflowRuntimePersister
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from application.persistence.exceptions import CheckpointPersistenceError


class _Workflows:
    def __init__(self):
        self.runs = {"parent": WorkflowRun(id="parent", project_id="project", workflow_template_id="desk")}
        parent_template = WorkflowTemplate(
            "desk", "Desk parent", [],
            research_brief_snapshot=ResearchBrief("Parent", "Parent question"),
            research_design_snapshot=_design(),
        )
        self.templates = []
        self.template_by_id = {parent_template.id: parent_template}
        self.results = {"parent": {}}
        self.versions = {"parent": 0}

    def get_workflow_run(self, run_id): return self.runs[run_id]
    def publish_template_snapshot(self, template, *, project_id):
        if template.id in self.template_by_id:
            raise DuplicateEntityError(f"WorkflowTemplate already exists: {template.id}")
        self.templates.append(template)
        self.template_by_id[template.id] = template
    def get_template(self, template_id): return self.template_by_id[template_id]
    def create_workflow_run(self, template, *, project_id, run_id, initially_paused=False):
        from domain.factories.task_factory import TaskFactory
        from domain.factories.workflow_run_factory import WorkflowRunFactory
        run = WorkflowRunFactory(TaskFactory()).create(template, run_id=run_id, project_id=project_id)
        if initially_paused:
            run.ready(); run.start(); run.pause()
        self.runs[run_id] = run
        self.results[run_id] = {}
        self.versions[run_id] = 0
        return run
    def delete_workflow_run(self, run_id):
        self.runs.pop(run_id, None); self.results.pop(run_id, None); self.versions.pop(run_id, None)
    def get_task_results(self, run_id): return dict(self.results[run_id])
    def get_workflow_run_version(self, run_id): return self.versions[run_id]
    def save_workflow_run(self, run, *, expected_version, task_results):
        if expected_version != self.versions[run.id]: raise RuntimeError("version conflict")
        self.results[run.id] = dict(task_results); self.versions[run.id] += 1
        return self.versions[run.id]


def _design():
    question = ResearchQuestion("rq", "Retail market")
    return ResearchDesign(
        id="design", research_questions=(question,),
        information_needs=(
            InformationNeed("in1", "rq", "nominal retail turnover", timeframe="2021,2022", geography="UA"),
            InformationNeed("in2_real_adjustment", "rq", "retail real-volume constant-price", timeframe="2021,2022", geography="UA"),
            InformationNeed("in3", "rq", "comparable retail trend", timeframe="2021,2022", geography="UA"),
            InformationNeed("unrelated", "rq", "unrelated", timeframe="2021", geography="UA"),
        ),
    )


class SelectedAuthorityExtensionTests(unittest.TestCase):
    def setUp(self):
        self.workflows = _Workflows()
        self.extensions = InMemoryAuthorityExtensionRepository()
        self.compositions = InMemoryComposedAuthorityRepository(self.extensions)
        self.states = InMemoryExtensionStateStore()
        self.service = SelectedAuthorityExtensionService(
            workflow_service=self.workflows, extension_repository=self.extensions,
            composed_authority_repository=self.compositions, state_store=self.states,
            capability_check=lambda: True,
        )
        self.extension = self.service.start(
            project_id="project", parent_workflow_run_id="parent", design=_design(),
            selected_information_need_ids=("in1", "in2_real_adjustment", "in3"),
            idempotency_key="idem", confirmed=True,
        )

    def _observation(self, need, source, *, kind="nominal", periods=("2021", "2022"),
                     run=None, evidence_id=None, project="project", design="design", conflicting=False):
        return AuthorityObservation(
            evidence_id=evidence_id or f"e-{need}-{source}", source_identity=source,
            information_need_ids=(need,), research_question_ids=("rq",), metric=need,
            geography="UA", periods=periods, authority_kind=kind,
            workflow_run_id=run or self.extension.extension_workflow_run_id,
            research_design_id=design, project_id=project, conflicting=conflicting,
        )

    def _sufficient(self):
        items = []
        for need in ("in1", "in3"):
            items += [self._observation(need, "a"), self._observation(need, "b")]
        items += [
            self._observation("in2_real_adjustment", "a", kind="retail_real_volume"),
            self._observation("in2_real_adjustment", "b", kind="retail_real_volume"),
        ]
        return items

    def _findings(self):
        state = self.states.load(self.extension.extension_workflow_run_id)
        assert state is not None
        values = []
        for need in self.extension.selected_information_need_ids:
            evidence = tuple(item.evidence_id for item in state.observations if need in item.information_need_ids)
            values.append(ExtensionFinding(
                f"f-{need}", need, evidence, self.extension.extension_workflow_run_id,
                "project", "design",
            ))
        return values

    def test_static_dag_and_idempotent_submission(self):
        template = self.workflows.templates[0]
        self.assertEqual(tuple(item.id for item in template.task_definitions), EXTENSION_STAGES)
        self.assertEqual(
            {item.id for item in template.research_design_snapshot.information_needs},
            {"in1", "in2_real_adjustment", "in3"},
        )
        again = self.service.start(
            project_id="project", parent_workflow_run_id="parent", design=_design(),
            selected_information_need_ids=("in3", "in2_real_adjustment", "in1"),
            idempotency_key="idem", confirmed=True,
        )
        self.assertEqual(again.extension_id, self.extension.extension_id)
        self.assertEqual(len(self.workflows.runs), 2)

    def test_second_attempt_gets_distinct_immutable_template_and_run(self):
        self.service.fail_technical(
            self.extension.extension_workflow_run_id, "first attempt failed",
        )
        second = self.service.start(
            project_id="project", parent_workflow_run_id="parent", design=_design(),
            selected_information_need_ids=("in1", "in2_real_adjustment", "in3"),
            idempotency_key="second-attempt", confirmed=True,
        )

        first_run = self.workflows.runs[self.extension.extension_workflow_run_id]
        second_run = self.workflows.runs[second.extension_workflow_run_id]
        self.assertNotEqual(second.extension_id, self.extension.extension_id)
        self.assertNotEqual(second_run.id, first_run.id)
        self.assertNotEqual(second_run.workflow_template_id, first_run.workflow_template_id)
        self.assertIs(self.workflows.get_template(first_run.workflow_template_id), self.workflows.templates[0])
        self.assertIs(self.workflows.get_template(second_run.workflow_template_id), self.workflows.templates[1])
        self.assertEqual(
            self.extensions.get_by_id(self.extension.extension_id).status.value,
            "technical_error",
        )

        repeated = self.service.start(
            project_id="project", parent_workflow_run_id="parent", design=_design(),
            selected_information_need_ids=("in3", "in2_real_adjustment", "in1"),
            idempotency_key="second-attempt", confirmed=True,
        )
        self.assertEqual(repeated.extension_id, second.extension_id)
        self.assertEqual(len(self.workflows.templates), 2)
        self.assertEqual(len(self.workflows.runs), 3)

    def test_attempt_template_identity_mismatch_fails_before_run_or_extension(self):
        selected = ("in1", "in2_real_adjustment", "in3")
        gaps = derive_gap_contract(_design(), selected)
        template_id = extension_template_id(
            project_id="project",
            parent_workflow_run_id="parent",
            design_id="design",
            gap_contract_digest=canonical_gap_digest([gap.to_dict() for gap in gaps]),
            idempotency_key="mismatched-attempt",
        )
        self.workflows.publish_template_snapshot(
            WorkflowTemplate(template_id, "Materially different", []),
            project_id="project",
        )
        before_runs = set(self.workflows.runs)
        before_extensions = set(self.extensions._items)

        with self.assertRaisesRegex(
            DuplicateEntityError,
            f"WorkflowTemplate already exists: {template_id}",
        ):
            self.service.start(
                project_id="project", parent_workflow_run_id="parent", design=_design(),
                selected_information_need_ids=selected,
                idempotency_key="mismatched-attempt", confirmed=True,
            )

        self.assertEqual(set(self.workflows.runs), before_runs)
        self.assertEqual(set(self.extensions._items), before_extensions)

    def test_capability_gate_activates_only_complete_runtime(self):
        activated = self.service.activate(self.extension.extension_id)
        self.assertEqual(activated.status.value, "active")
        self.assertEqual(
            self.workflows.runs[self.extension.extension_workflow_run_id].status.value,
            "running",
        )
        blocked_service = SelectedAuthorityExtensionService(
            workflow_service=self.workflows,
            extension_repository=self.extensions,
            composed_authority_repository=self.compositions,
            state_store=self.states,
            capability_check=lambda: False,
        )
        other = blocked_service.start(
            project_id="project", parent_workflow_run_id="parent", design=_design(),
            selected_information_need_ids=("in1",), idempotency_key="blocked", confirmed=True,
        )
        with self.assertRaises(ExtensionContractError):
            blocked_service.activate(other.extension_id)
        self.assertEqual(self.workflows.runs[other.extension_workflow_run_id].status.value, "paused")

    def test_confirmation_and_idempotency_conflict_fail_closed(self):
        with self.assertRaises(ExtensionContractError):
            self.service.start(project_id="project", parent_workflow_run_id="parent", design=_design(),
                               selected_information_need_ids=("in1",), idempotency_key="x", confirmed=False)
        with self.assertRaises(ExtensionContractError):
            self.service.start(project_id="project", parent_workflow_run_id="parent", design=_design(),
                               selected_information_need_ids=("in1",), idempotency_key="idem", confirmed=True)

    def test_search_budget_is_durable_and_n_plus_one_is_pre_dispatch(self):
        calls = []
        for _ in range(SEARCH_BUDGET_MAX):
            self.service.dispatch_search(self.extension.extension_workflow_run_id, lambda: calls.append(1))
        with self.assertRaises(ExtensionBudgetExceeded):
            self.service.dispatch_search(self.extension.extension_workflow_run_id, lambda: calls.append(1))
        self.assertEqual(len(calls), SEARCH_BUDGET_MAX)
        replacement = SelectedAuthorityExtensionService(
            workflow_service=self.workflows, extension_repository=self.extensions,
            composed_authority_repository=self.compositions, state_store=self.states)
        with self.assertRaises(ExtensionBudgetExceeded):
            replacement.dispatch_search(self.extension.extension_workflow_run_id, lambda: calls.append(1))

    def test_satisfied_need_receives_zero_additional_search_calls(self):
        self.service.record_observations(self.extension.extension_workflow_run_id, self._sufficient())
        self.service.evaluate(self.extension.extension_workflow_run_id)
        calls = []
        result = self.service.dispatch_search(
            self.extension.extension_workflow_run_id, lambda: calls.append(1),
            information_need_id="in1",
        )
        self.assertIsNone(result)
        self.assertEqual(calls, [])
        self.assertEqual(self.states.load(self.extension.extension_workflow_run_id).budget.search_used, 0)

    def test_unrelated_search_is_rejected_before_dispatch(self):
        calls = []
        with self.assertRaises(ExtensionContractError):
            self.service.dispatch_search(
                self.extension.extension_workflow_run_id, lambda: calls.append(1),
                information_need_id="unrelated",
            )
        self.assertEqual(calls, [])

    def test_provider_budget_is_durable_and_n_plus_one_is_pre_dispatch(self):
        calls = []
        for _ in range(PROVIDER_BUDGET_MAX):
            self.service.dispatch_provider(self.extension.extension_workflow_run_id, lambda: calls.append(1))
        with self.assertRaises(ExtensionBudgetExceeded):
            self.service.dispatch_provider(self.extension.extension_workflow_run_id, lambda: calls.append(1))
        self.assertEqual(len(calls), PROVIDER_BUDGET_MAX)

    def test_analysis_reservation_caps_evidence_and_survives_reload(self):
        self.service.reserve_analysis_budget(self.extension.extension_workflow_run_id)
        calls = []
        for _ in range(4):
            self.service.dispatch_provider(
                self.extension.extension_workflow_run_id,
                lambda: calls.append("evidence"), stage="evidence",
            )
        with self.assertRaises(ExtensionBudgetExceeded):
            self.service.dispatch_provider(
                self.extension.extension_workflow_run_id,
                lambda: calls.append("evidence"), stage="evidence",
            )
        for _ in range(3):
            self.service.dispatch_provider(
                self.extension.extension_workflow_run_id,
                lambda: calls.append("analysis"), stage="analysis",
            )
        with self.assertRaises(ExtensionBudgetExceeded):
            self.service.dispatch_provider(
                self.extension.extension_workflow_run_id,
                lambda: calls.append("analysis"), stage="analysis",
            )
        durable = WorkflowExtensionStateStore(self.workflows)
        durable.save(self.states.load(self.extension.extension_workflow_run_id))
        replacement = SelectedAuthorityExtensionService(
            workflow_service=self.workflows, extension_repository=self.extensions,
            composed_authority_repository=self.compositions,
            state_store=durable,
        )
        with self.assertRaises(ExtensionBudgetExceeded):
            replacement.dispatch_provider(
                self.extension.extension_workflow_run_id,
                lambda: calls.append("analysis"), stage="analysis",
            )
        restored = durable.load(
            self.extension.extension_workflow_run_id,
        )
        self.assertEqual((7, 3, 3), (
            restored.budget.provider_used,
            restored.budget.analysis_reserved,
            restored.budget.analysis_used,
        ))
        self.assertEqual(calls, ["evidence"] * 4 + ["analysis"] * 3)

    def test_workflow_state_store_survives_service_reconstruction(self):
        workflows = _Workflows()
        extensions = InMemoryAuthorityExtensionRepository()
        compositions = InMemoryComposedAuthorityRepository(extensions)
        first = SelectedAuthorityExtensionService(
            workflow_service=workflows, extension_repository=extensions,
            composed_authority_repository=compositions,
            state_store=WorkflowExtensionStateStore(workflows),
        )
        extension = first.start(
            project_id="project", parent_workflow_run_id="parent", design=_design(),
            selected_information_need_ids=("in1",), idempotency_key="durable", confirmed=True,
        )
        first.dispatch_search(extension.extension_workflow_run_id, lambda: None)
        second = SelectedAuthorityExtensionService(
            workflow_service=workflows, extension_repository=extensions,
            composed_authority_repository=compositions,
            state_store=WorkflowExtensionStateStore(workflows),
        )
        second.dispatch_search(extension.extension_workflow_run_id, lambda: None)
        restored = WorkflowExtensionStateStore(workflows).load(extension.extension_workflow_run_id)
        self.assertEqual(restored.budget.search_used, 2)

    def test_cpi_and_nominal_plus_cpi_do_not_satisfy_real_adjustment(self):
        gap = derive_gap_contract(_design(), ("in2_real_adjustment",))[0]
        cpi = [self._observation("in2_real_adjustment", "a", kind="cpi"),
               self._observation("in2_real_adjustment", "b", kind="cpi")]
        self.assertEqual(qualify_gap(gap, cpi), GapOutcome.INSUFFICIENT)
        nominal = cpi + [self._observation("in2_real_adjustment", "c", kind="nominal")]
        self.assertEqual(qualify_gap(gap, nominal), GapOutcome.INSUFFICIENT)

    def test_real_volume_with_independent_sources_satisfies(self):
        gap = derive_gap_contract(_design(), ("in2_real_adjustment",))[0]
        values = [self._observation("in2_real_adjustment", "a", kind="retail_real_volume"),
                  self._observation("in2_real_adjustment", "b", kind="retail_deflator")]
        self.assertEqual(qualify_gap(gap, values), GapOutcome.SATISFIED)

    def test_same_source_does_not_inflate_independence(self):
        gap = derive_gap_contract(_design(), ("in1",))[0]
        values = [self._observation("in1", "same", evidence_id="one"),
                  self._observation("in1", "same", evidence_id="two")]
        self.assertEqual(qualify_gap(gap, values), GapOutcome.INSUFFICIENT)

    def test_missing_period_is_insufficient(self):
        gap = derive_gap_contract(_design(), ("in1",))[0]
        values = [self._observation("in1", "a", periods=("2022",)),
                  self._observation("in1", "b", periods=("2022",))]
        self.assertEqual(qualify_gap(gap, values), GapOutcome.INSUFFICIENT)

    def test_isolated_trend_observations_are_insufficient(self):
        gap = derive_gap_contract(_design(), ("in3",))[0]
        values = [self._observation("in3", "a", periods=("2022",))]
        self.assertEqual(qualify_gap(gap, values), GapOutcome.INSUFFICIENT)

    def test_conflict_is_separate_outcome(self):
        gap = derive_gap_contract(_design(), ("in1",))[0]
        self.assertEqual(qualify_gap(gap, [self._observation("in1", "a", conflicting=True)]), GapOutcome.CONFLICTING)

    def test_scope_cross_project_design_member_and_unrelated_rejected(self):
        cases = [
            self._observation("in1", "a", project="other"),
            self._observation("in1", "a", design="other"),
            self._observation("in1", "a", run="foreign"),
            self._observation("unrelated", "a"),
        ]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ExtensionContractError):
                    self.service.record_observations(self.extension.extension_workflow_run_id, [value])

    def test_evidence_retry_is_idempotent(self):
        value = self._observation("in1", "a")
        self.service.record_observations(self.extension.extension_workflow_run_id, [value])
        state = self.service.record_observations(self.extension.extension_workflow_run_id, [value])
        self.assertEqual(len(state.observations), 1)

    def test_finding_retry_is_idempotent_and_cross_member_rejected(self):
        self.service.record_observations(self.extension.extension_workflow_run_id, self._sufficient())
        value = self._findings()[0]
        self.service.record_findings(self.extension.extension_workflow_run_id, [value])
        state = self.service.record_findings(self.extension.extension_workflow_run_id, [value])
        self.assertEqual(len(state.findings), 1)
        with self.assertRaises(ExtensionContractError):
            self.service.record_findings(self.extension.extension_workflow_run_id, [replace(value, finding_id="bad", evidence_ids=("foreign",))])

    def test_incomplete_findings_prevent_composition(self):
        self.service.record_observations(self.extension.extension_workflow_run_id, self._sufficient())
        state = self.service.finalize(self.extension.extension_workflow_run_id, created_at="now")
        self.assertIsNone(state.composition_id)
        self.assertEqual(self.extensions.get_by_id(self.extension.extension_id).status.value, "insufficient")

    def test_one_insufficient_need_prevents_composition(self):
        values = [item for item in self._sufficient() if "in3" not in item.information_need_ids]
        self.service.record_observations(self.extension.extension_workflow_run_id, values)
        self.service.record_findings(self.extension.extension_workflow_run_id, [
            ExtensionFinding("f-in1", "in1", tuple(item.evidence_id for item in values if "in1" in item.information_need_ids), self.extension.extension_workflow_run_id, "project", "design")])
        state = self.service.finalize(self.extension.extension_workflow_run_id, created_at="now")
        self.assertIsNone(state.composition_id)
        from application.report.h3_coverage_plan import build_h3_coverage_plan
        plan = build_h3_coverage_plan(
            design=self.workflows.templates[0].research_design_snapshot,
            required_information_need_ids=self.extension.selected_information_need_ids,
            findings=(), evidence_by_id={}, insights=(),
        )
        self.assertFalse(plan.is_fully_fillable)

    def test_happy_path_and_finalize_retry_keep_same_digest(self):
        self.service.record_observations(self.extension.extension_workflow_run_id, self._sufficient())
        self.service.record_findings(self.extension.extension_workflow_run_id, self._findings())
        first = self.service.finalize(self.extension.extension_workflow_run_id, created_at="now")
        second = self.service.finalize(self.extension.extension_workflow_run_id, created_at="later")
        self.assertEqual(first.composition_digest, second.composition_digest)
        self.assertEqual(self.extensions.get_by_id(self.extension.extension_id).status.value, "succeeded")
        self.assertEqual(len(self.compositions._items), 1)

    def test_parent_observation_can_support_composed_authority_without_mutation(self):
        value = self._observation("in1", "parent-source", run="parent")
        state = self.service.record_observations(self.extension.extension_workflow_run_id, [value])
        self.assertEqual(state.observations[0].workflow_run_id, "parent")
        self.assertEqual(self.workflows.runs["parent"].project_id, "project")

    def test_parent_source_rediscovery_does_not_mutate_parent(self):
        repository = InMemorySourceRepository()
        original = Source("s", "project", "https://x", "https://x", "x", "now",
                          workflow_run_refs=("parent",), research_design_refs=("design",))
        repository.create(original)
        proxy = ExtensionImmutableSourceRepositoryProxy(repository)
        candidate = replace(original, workflow_run_refs=("parent", self.extension.extension_workflow_run_id))
        token = _extension_dispatch.set((self.service, self.extension.extension_workflow_run_id))
        try:
            proxy.save(candidate, expected_version=original.version)
        finally:
            _extension_dispatch.reset(token)
        self.assertEqual(repository.get_by_id("s").workflow_run_refs, ("parent",))

    def test_parent_source_selected_by_extension_is_visible_without_mutation(self):
        repository = InMemorySourceRepository()
        original = Source(
            "s",
            "project",
            "https://x",
            "https://x",
            "x",
            "now",
            workflow_run_refs=("parent",),
            research_design_refs=("design",),
            information_need_refs=("in1",),
            content_text="Acquired market report body text.",
            content_checksum="checksum",
        )
        repository.create(original)
        proxy = ExtensionImmutableSourceRepositoryProxy(repository)

        class _Context:
            @staticmethod
            def read_shared(key):
                return {
                    "source_acquisition": {"source_ids": ["s"]},
                    "research_funnel_v1": {
                        "events": [
                            {
                                "kind": "candidate_decision",
                                "source_id": "s",
                                "target_in": "in1",
                                "reason": "selected",
                            },
                        ],
                    },
                }.get(key)

        run_id = self.extension.extension_workflow_run_id
        dispatch_token = _extension_dispatch.set((self.service, run_id))
        context_token = _extension_runtime_context.set(_Context())
        try:
            selected = proxy.list_for_project("project", workflow_run_id=run_id)
        finally:
            _extension_runtime_context.reset(context_token)
            _extension_dispatch.reset(dispatch_token)

        self.assertEqual([source.id for source in selected], ["s"])
        run_context = resolve_run_scoped_context(
            source=selected[0],
            design=_design(),
            workflow_run_id=run_id,
            research_design_id="design",
        )
        self.assertEqual(run_context.information_need_ids, ("in1",))

        workflow_context = WorkflowContext(
            project=Project(id="project", name="Project"),
            workflow_template=self.workflows.templates[0],
            workflow_run=self.workflows.runs[run_id],
        )
        workflow_context.write_shared("source_acquisition", {"source_ids": ["s"]})
        workflow_context.write_shared(
            "research_funnel_v1",
            {
                "version": 1,
                "sequence": 0,
                "dropped_events": 0,
                "observer_errors": 0,
                "events": [
                    {
                        "kind": "candidate_decision",
                        "source_id": "s",
                        "target_in": "in1",
                        "reason": "selected",
                    },
                ],
            },
        )
        evidence = InMemoryEvidenceRepository()
        extraction = EvidenceExtractionService(
            evidence_extractor=DeterministicEvidenceExtractor(),
            evidence_repository=evidence,
            source_repository=proxy,
        )
        dispatch_token = _extension_dispatch.set((self.service, run_id))
        context_token = _extension_runtime_context.set(workflow_context)
        try:
            summary = extraction.extract_for_context(workflow_context)
        finally:
            _extension_runtime_context.reset(context_token)
            _extension_dispatch.reset(dispatch_token)
        self.assertEqual(summary.evidence_extracted, 1)
        self.assertEqual(
            evidence.list_for_project("project", workflow_run_id=run_id)[0].source_id,
            "s",
        )

        persisted = repository.get_by_id("s")
        self.assertEqual(persisted.workflow_run_refs, ("parent",))
        self.assertNotIn(
            run_id,
            {
                record.get("workflow_run_id")
                for record in persisted.metadata.get("discovery_records", [])
            },
        )

    def test_technical_failure_is_durable(self):
        self.service.fail_technical(self.extension.extension_workflow_run_id, "network unavailable")
        stored = self.extensions.get_by_id(self.extension.extension_id)
        self.assertEqual(stored.status.value, "technical_error")
        self.assertEqual(stored.terminal_reason, "network unavailable")

    def _runtime_owned_plan(self):
        workflows = _Workflows()
        extensions = InMemoryAuthorityExtensionRepository()
        states = WorkflowExtensionStateStore(workflows)
        service = SelectedAuthorityExtensionService(
            workflow_service=workflows,
            extension_repository=extensions,
            composed_authority_repository=InMemoryComposedAuthorityRepository(extensions),
            state_store=states,
            capability_check=lambda: True,
        )
        extension = service.start(
            project_id="project",
            parent_workflow_run_id="parent",
            design=_design(),
            selected_information_need_ids=("in1", "in2_real_adjustment", "in3"),
            idempotency_key="runtime-version-test",
            confirmed=True,
        )
        service.activate(extension.extension_id)
        run_id = extension.extension_workflow_run_id
        run = workflows.get_workflow_run(run_id)
        task = run.tasks[0]
        task.ready()
        task.start()
        context = WorkflowContext(run, Project("project", "P"), workflows.templates[0])
        context.current_task = task
        persister = WorkflowRuntimePersister(
            workflow_service=workflows,
            audit=None,
            run_id=run_id,
            initial_version=workflows.get_workflow_run_version(run_id),
            task_results=workflows.get_task_results(run_id),
        )
        context.services[CHECKPOINT_SERVICE_KEY] = persister
        return workflows, extensions, service, extension, context, task, persister

    def test_extension_plan_uses_runtime_as_single_workflow_version_owner(self):
        workflows, _, service, extension, context, task, persister = self._runtime_owned_plan()
        persister.on_task_running(context)
        AuthorityExtensionStageExecutor("extension_plan", service).run(context)
        task.complete()
        persister.on_task_finished(context, error=None)

        self.assertEqual(
            persister.expected_version,
            workflows.get_workflow_run_version(extension.extension_workflow_run_id),
        )
        state = workflows.get_task_results(extension.extension_workflow_run_id)
        self.assertIn(WorkflowExtensionStateStore.KEY, state)

    def test_unresolved_information_needs_is_checkpoint_less_and_read_only(self):
        workflows, _, service, extension, _, _, _ = self._runtime_owned_plan()
        run_id = extension.extension_workflow_run_id
        before_version = workflows.get_workflow_run_version(run_id)
        before_results = workflows.get_task_results(run_id)

        unresolved = service.unresolved_information_need_ids(run_id)

        self.assertEqual(
            unresolved,
            ("in1", "in2_real_adjustment", "in3"),
        )
        self.assertEqual(workflows.get_workflow_run_version(run_id), before_version)
        self.assertEqual(workflows.get_task_results(run_id), before_results)

    def test_evaluate_persists_through_runtime_checkpoint(self):
        workflows, _, service, extension, context, _, persister = self._runtime_owned_plan()
        run_id = extension.extension_workflow_run_id
        with service.runtime_state_scope(context):
            state = service.evaluate(run_id)

        self.assertEqual(
            dict(state.outcomes),
            {
                "in1": GapOutcome.INSUFFICIENT,
                "in2_real_adjustment": GapOutcome.INSUFFICIENT,
                "in3": GapOutcome.INSUFFICIENT,
            },
        )
        self.assertEqual(persister.expected_version, workflows.get_workflow_run_version(run_id))
        persisted = workflows.get_task_results(run_id)[WorkflowExtensionStateStore.KEY]
        self.assertEqual(len(persisted["outcomes"]), 3)

    def test_checkpoint_conflict_marks_extension_technical_error(self):
        workflows, extensions, service, extension, context, task, persister = self._runtime_owned_plan()
        persister.on_task_running(context)
        AuthorityExtensionStageExecutor("extension_plan", service).run(context)
        workflows.save_workflow_run(
            context.workflow_run,
            expected_version=workflows.get_workflow_run_version(extension.extension_workflow_run_id),
            task_results=workflows.get_task_results(extension.extension_workflow_run_id),
        )
        task.complete()

        with self.assertRaises(CheckpointPersistenceError):
            persister.on_task_finished(context, error=None)
        stored = extensions.get_by_id(extension.extension_id)
        self.assertEqual(stored.status.value, "technical_error")
        self.assertEqual(stored.terminal_reason, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
