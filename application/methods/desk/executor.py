"""Persisted version selection over the existing Desk executor IDs."""
from dataclasses import replace

from application import research_funnel_telemetry as funnel
from application.contracts.base_executor import BaseExecutor
from application.execution.execution_budget_factory import create_execution_budget
from application.execution.execution_budget_context import execution_budget_scope, EXECUTION_BUDGET_KEY, ensure_run_budget
from application.methods.desk.adapter import DeskAdapter
from application.methods.desk.primitives import DeskPrimitives
from application.methods.desk.profile import PIN, template_marker
from application.research_kernel.controller import Controller
from application.research_kernel.telemetry import observe_decision
from application.sources.search_factory import build_source_acquisition_service
from application.evidence.evidence_factory import build_evidence_extraction_service
from application.research_quality.research_quality_factory import build_research_sufficiency_evaluator
from application.research_quality.research_readiness_service import ResearchReadinessService


class VersionedDeskExecutor(BaseExecutor):
    def __init__(self, legacy, stage, *, config, overrides, sources, evidence, llm_client, store_factory):
        self.legacy, self.stage = legacy, stage
        self.config, self.overrides = config, overrides
        self.sources, self.evidence, self.llm = sources, evidence, llm_client
        self.store_factory = store_factory

    def run(self, context):
        marker = template_marker(context.workflow_template) if context.workflow_template else None
        pin = context.execution_metadata.get(PIN)
        if marker is None and pin is None:
            return self.legacy.run(context)
        if marker != pin or not isinstance(pin, dict) or pin.get("version") != 1:
            raise RuntimeError("Desk execution version is not the activation-pinned version")
        if self.stage != "search":
            if not context.shared_state.get("ark_stop"):
                raise RuntimeError("ARK research task did not complete its gate")
            return context
        return self._kernel(context, pin)

    @funnel.observed("adaptive_kernel")
    def _kernel(self, context, pin):
        cfg = replace(self.config, **pin["profile"])
        if (cfg.llm_model, cfg.llm_max_tokens) != (self.config.llm_model, self.config.llm_max_tokens):
            raise RuntimeError("worker LLM configuration differs from pinned Desk profile")
        if self.store_factory is None:
            raise RuntimeError("ARK requires durable PostgreSQL worker execution")
        store = self.store_factory(context)
        saved = store.load()
        budget = create_execution_budget(cfg)
        if saved:
            for purpose, count in (("initial", saved.used.get("initial", 0)),
                                   ("remediation", saved.used.get("continuation", 0))):
                for _ in range(count):
                    budget.record_llm_call("evidence", purpose=purpose)
            for _ in range(saved.used.get("assessments", 0)):
                budget.record_llm_call("sufficiency")
        context.execution_metadata[EXECUTION_BUDGET_KEY] = budget
        acquisition = build_source_acquisition_service(config=cfg, overrides=self.overrides,
            source_repository=self.sources, evidence_repository=self.evidence)
        extraction = build_evidence_extraction_service(config=cfg, overrides=self.overrides,
            source_repository=self.sources, evidence_repository=self.evidence, llm_client=self.llm)
        readiness = ResearchReadinessService(evaluator=build_research_sufficiency_evaluator(
            config=cfg, overrides=self.overrides, llm_client=self.llm),
            evidence_repository=self.evidence, source_repository=self.sources)
        from application.methods.versioning import resolve_context
        method = resolve_context(context)
        primitives = DeskPrimitives(context, acquisition, extraction)
        adapter = (method.research_adapter(context=context, config=cfg, primitives=primitives,
                   readiness=readiness, evidence=self.evidence) if method is not None else
                   DeskAdapter(context, cfg, primitives, readiness, self.evidence))
        adapter.checkpoint()
        with execution_budget_scope(budget):
            result = Controller(store, adapter, observe_decision).run(adapter.initial_state())
            # Hidden transport attempts are already charged durably. Bring the
            # legacy downstream guard up to that conservative exposure too.
            for purpose, dimension, recorded in (("initial", "initial", budget.evidence_initial_calls),
                    ("remediation", "continuation", budget.evidence_remediation_calls)):
                for _ in range(max(0, result.used.get(dimension, 0) - recorded)):
                    budget.record_llm_call("evidence", purpose=purpose, retry=True)
            for _ in range(max(0, result.used.get("assessments", 0) - budget.stage_calls("sufficiency"))):
                budget.record_llm_call("sufficiency", retry=True)
            adapter.finish(result)
        # The workflow binds a budget once, before the search task. Rebind the
        # restored budget for its subsequent canonical tasks, not the old one.
        ensure_run_budget(context)
        return context
