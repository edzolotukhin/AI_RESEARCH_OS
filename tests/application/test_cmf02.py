"""Reusable registry contract and real Desk deterministic CMF parity."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest

from application.methods.catalog import production_methods
from application.methods.registry import MethodRegistry, MethodResolutionError
from application.methods.desk.binding import DeskBinding
from application.methods.executor import MethodExecutor
from application.methods.versioning import envelope, resolve_context, resolve_pin
from application.methods.desk.profile import PIN, profile, template_marker
from application.methods.desk.executor import VersionedDeskExecutor
from application.planner.research_design_workflow_mapper import ResearchDesignWorkflowMapper
from application.execution.execution_budget_context import execution_budget_scope
from application.execution.execution_budget_factory import create_execution_budget
from infrastructure.persistence.postgresql.kernel_ownership import checkpoint_results
from tests.application.test_ark02_desk import fixture
from tests.application.test_ark02_kernel import Store


class RegistryContract:
    """Future method test classes provide binding(); core tests stay unchanged."""
    def test_exact_resolution(self):
        method = self.binding()
        self.assertIs(MethodRegistry((method,)).resolve(method.identity.method_id, method.identity.version), method)

    def test_duplicate_rejected(self):
        method = self.binding()
        with self.assertRaises(MethodResolutionError):
            MethodRegistry((method, method))

    def test_unknown_version_rejected(self):
        method = self.binding()
        with self.assertRaises(MethodResolutionError):
            MethodRegistry((method,)).resolve(method.identity.method_id, "absent")

    def test_unknown_method_rejected(self):
        with self.assertRaises(MethodResolutionError):
            MethodRegistry((self.binding(),)).resolve("UNKNOWN", "1")


class DeskRegistryTests(RegistryContract, unittest.TestCase):
    binding = staticmethod(DeskBinding)


class FakeMethod:
    identity = replace(DeskBinding.identity, method_id="TEST_ONLY", name="Fake contract proof")
    capabilities = DeskBinding.capabilities
    def validate_design(self, design, brief): pass
    def research_needs(self, design): return ("fake-need",)
    def research_adapter(self, **kwargs): raise NotImplementedError
    def run_stage(self, stage, context, delegate): return (stage, "fake")
    def report_sources(self, project_id, run_ids, delegate): return ()


class FakeRegistryTests(RegistryContract, unittest.TestCase):
    binding = staticmethod(FakeMethod)

    def test_fake_resolves_and_dispatches_without_desk_switch(self):
        config, context, *_ = fixture()
        pin_context(config, context)
        from dataclasses import asdict
        pin = context.execution_metadata[PIN]
        pin["cmf"]["identity"] = asdict(FakeMethod.identity)
        for definition in context.workflow_template.task_definitions:
            definition.metadata["research_kernel"] = deepcopy(pin)
        result = MethodExecutor("analysis", SimpleNamespace(run=lambda ctx: ctx),
                                MethodRegistry((FakeMethod(),))).run(context)
        self.assertEqual(result, ("analysis", "fake"))


def pin_context(config, context):
    marker = deepcopy(template_marker(context.workflow_template))
    marker["cmf"] = envelope(DeskBinding(), context.workflow_template.research_design_snapshot,
                              context.workflow_template.research_brief_snapshot, marker["profile"])
    for definition in context.workflow_template.task_definitions:
        definition.metadata["research_kernel"] = deepcopy(marker)
    context.execution_metadata[PIN] = deepcopy(marker)


class DeskContracts(unittest.TestCase):
    def test_mapper_pins_and_validates(self):
        config, context, *_ = fixture()
        method = DeskBinding()
        mapper = ResearchDesignWorkflowMapper(kernel_profile=profile(config), method_binding=method)
        design = replace(context.workflow_template.research_design_snapshot,
                         source_strategy=("web",), analysis_plan=("synthesis",), deliverable_plan=("report",))
        template = mapper.from_research_design(design, context.project)
        self.assertEqual(template_marker(template)["cmf"]["identity"]["method_id"], "DESK")
        self.assertEqual(method.research_needs(design), design.information_needs)
        with self.assertRaises(ValueError):
            ResearchDesignWorkflowMapper(method_binding=method)
        from domain.common.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            mapper.from_research_design(replace(design, research_questions=()), context.project)

    def test_history_without_envelope_remains_legacy(self):
        _, context, *_ = fixture()
        self.assertIsNone(resolve_context(context))
        self.assertIsNone(resolve_pin(None))

    def test_restart_exact_pin_and_checkpoint_cannot_replace_it(self):
        config, context, *_ = fixture()
        pin_context(config, context)
        stored = {PIN: deepcopy(context.execution_metadata[PIN])}
        result = checkpoint_results(stored, {PIN: {"version": 99}})
        self.assertEqual(result[PIN], stored[PIN])
        context.execution_metadata[PIN] = result[PIN]
        self.assertEqual(resolve_context(context).identity, DeskBinding.identity)
        self.assertEqual(checkpoint_results(stored, {})[PIN], stored[PIN])

    def test_unknown_pinned_version_fails_closed(self):
        config, context, *_ = fixture()
        pin_context(config, context)
        pin = context.execution_metadata[PIN]
        pin["cmf"]["identity"]["version"] = "unknown"
        with self.assertRaises(MethodResolutionError): resolve_pin(pin)

    def test_missing_pin_and_changed_design_fail_closed(self):
        config, context, *_ = fixture()
        pin_context(config, context)
        pin = context.execution_metadata.pop(PIN)
        with self.assertRaises(ValueError): resolve_context(context)
        context.execution_metadata[PIN] = pin
        context.workflow_template = replace(context.workflow_template,
            research_design_snapshot=replace(context.workflow_template.research_design_snapshot, id="changed"))
        with self.assertRaises(ValueError): resolve_context(context)

    def test_changed_profile_and_identity_fail_closed(self):
        config, context, *_ = fixture()
        pin_context(config, context)
        pin = deepcopy(context.execution_metadata[PIN])
        pin["profile"]["evidence_max_llm_calls"] = 9
        with self.assertRaises(ValueError): resolve_pin(pin)
        pin = deepcopy(context.execution_metadata[PIN])
        pin["cmf"]["identity"]["integrity_version"] = "permissive"
        with self.assertRaises(ValueError): resolve_pin(pin)

    def test_source_repository_required_for_readiness(self):
        config, context, _, evidence, _, adapter, *_ = fixture()
        method = DeskBinding()
        args = dict(context=context, config=config, primitives=adapter.primitives,
                    readiness=adapter.readiness, evidence=evidence)
        self.assertIsInstance(method.research_adapter(**args), type(adapter))
        with self.assertRaises(RuntimeError):
            method.research_adapter(**{**args, "readiness": SimpleNamespace(_source_repository=None)})

    def test_all_downstream_stages_delegate_same_context_without_evidence_changes(self):
        config, context, _, evidence, *_ = fixture()
        pin_context(config, context)
        before = deepcopy(evidence.list_for_project(context.project.id))
        for stage in ("analysis", "report", "review"):
            seen = []
            delegate = SimpleNamespace(run=lambda value: seen.append(value) or value)
            self.assertIs(MethodExecutor(stage, delegate, production_methods()).run(context), context)
            self.assertEqual(seen, [context])
        self.assertEqual(before, evidence.list_for_project(context.project.id))

    def test_report_binding_keeps_exact_source_objects(self):
        documents = (SimpleNamespace(source_id="report", source_version="revision-2-review-x", status="draft"),)
        def provider(project, runs):
            self.assertEqual((project, runs), ("p", {"r"}))
            return documents
        self.assertIs(DeskBinding().report_sources("p", {"r"}, provider), documents)

    def test_real_executor_equivalence_zero_evidence_six_plus_two(self):
        outcomes = []
        for migrated, telemetry in ((False, False), (True, False), (True, True)):
            config, context, sources, evidence, llm, _, overrides, client = fixture()
            context.execution_metadata["research_funnel_enabled"] = telemetry
            if migrated: pin_context(config, context)
            store = Store()
            executor = VersionedDeskExecutor(None, "search", config=config, overrides=overrides,
                sources=sources, evidence=evidence, llm_client=client, store_factory=lambda c: store)
            routed = MethodExecutor("search", executor, production_methods())
            with execution_budget_scope(create_execution_budget(config)):
                routed.run(context)
            state = store.load()
            outcomes.append((state.used, state.terminal, llm.calls,
                context.shared_state["research_readiness"], evidence.list_for_project(context.project.id)))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[1], outcomes[2])
        self.assertEqual(outcomes[1][0]["initial"], 6)
        self.assertEqual(outcomes[1][0]["continuation"], 2)
        self.assertEqual(outcomes[1][2], 8)
        self.assertEqual(outcomes[1][4], [])
