from __future__ import annotations

from dataclasses import dataclass
from contextvars import ContextVar
import re
from typing import Any

from application.authority_extension.selected_workflow import (
    AuthorityObservation, ExtensionContractError, ExtensionFinding,
)
from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from runtime.workflow_context import WorkflowContext

_extension_dispatch: ContextVar[tuple[Any, str] | None] = ContextVar("authority_extension_dispatch", default=None)


class ExtensionSearchBudgetProxy:
    def __init__(self, delegate) -> None: self._delegate = delegate
    def supports_retrieval_arm(self, arm, query): return self._delegate.supports_retrieval_arm(arm, query)
    def search(self, query):
        current = _extension_dispatch.get()
        if current is None: return self._delegate.search(query)
        service, run_id = current
        return service.dispatch_search(
            run_id, lambda: self._delegate.search(query),
            information_need_id=query.information_need_id,
        )


class ExtensionProviderBudgetProxy:
    def __init__(self, delegate) -> None: self._delegate = delegate
    def generate(self, *args, **kwargs):
        current = _extension_dispatch.get()
        if current is None: return self._delegate.generate(*args, **kwargs)
        service, run_id = current
        return service.dispatch_provider(run_id, lambda: self._delegate.generate(*args, **kwargs))
    def __getattr__(self, name): return getattr(self._delegate, name)


class ExtensionImmutableSourceRepositoryProxy:
    """Prevents rediscovery from appending extension refs to a parent Source."""
    def __init__(self, delegate) -> None: self._delegate = delegate
    def save(self, source, *, expected_version=None):
        current = _extension_dispatch.get()
        if current is not None:
            _, run_id = current
            persisted = self._delegate.get_by_id(source.id)
            if persisted is not None and run_id not in persisted.workflow_run_refs:
                return persisted.version
        return self._delegate.save(source, expected_version=expected_version)
    def __getattr__(self, name): return getattr(self._delegate, name)


@dataclass
class AuthorityExtensionStageExecutor(BaseExecutor):
    stage: str
    service: Any
    delegate: Any | None = None
    evidence_repository: Any | None = None
    finding_repository: Any | None = None

    def run(self, context: WorkflowContext) -> WorkflowContext:
        run_id = context.workflow_run.id
        try:
            if self.stage == "extension_plan":
                state = self.service._state(run_id)
                context.write_shared("authority_extension_plan", {
                    "selected_information_need_ids": [gap.information_need_id for gap in state.gaps],
                    "unresolved_information_need_ids": list(self.service.unresolved_information_need_ids(run_id)),
                })
                extension = self.service.extensions.get_by_id(state.extension_id)
                context.write_shared("authority_extension_members", {
                    "workflow_run_ids": [
                        extension.parent_source_workflow_run_id,
                        extension.extension_workflow_run_id,
                    ],
                })
            elif self.stage in {"extension_search", "extension_evidence"}:
                if self.delegate is None:
                    raise ExtensionContractError("extension stage delegate unavailable")
                token = _extension_dispatch.set((self.service, run_id))
                try:
                    context = self.delegate.run(context)
                finally:
                    _extension_dispatch.reset(token)
                if self.stage == "extension_evidence":
                    self._capture_evidence(context)
            elif self.stage == "extension_readiness":
                self.service.evaluate(run_id)
            elif self.stage == "extension_analysis":
                if self.delegate is None:
                    raise ExtensionContractError("extension analysis delegate unavailable")
                token = _extension_dispatch.set((self.service, run_id))
                try:
                    context = self.delegate.run(context)
                finally:
                    _extension_dispatch.reset(token)
                self._capture_findings(context)
            elif self.stage == "extension_finalize":
                self.service.finalize(run_id, created_at=context.execution_metadata.get("now", "workflow-runtime"))
            else:
                raise ExtensionContractError("unknown authority extension stage")
        except Exception as exc:
            self.service.fail_technical(run_id, type(exc).__name__)
            raise
        task = context.current_task
        if task is not None:
            context.intermediate_results[task.id] = capture_task_result(context, task.id)
        return context

    def _capture_evidence(self, context: WorkflowContext) -> None:
        state = self.service._state(context.workflow_run.id)
        extension = self.service.extensions.get_by_id(state.extension_id)
        values = []
        for member_run_id in (
            extension.parent_source_workflow_run_id,
            extension.extension_workflow_run_id,
        ):
            values.extend(self.evidence_repository.list_for_project(
                context.project.id, workflow_run_id=member_run_id,
            ))
        observations = []
        selected = {gap.information_need_id for gap in state.gaps}
        for value in values:
            if not selected.intersection(value.information_need_refs):
                continue
            metadata = value.metadata if isinstance(value.metadata, dict) else {}
            assignment = metadata.get("semantic_assignment")
            if not isinstance(assignment, dict):
                raise ExtensionContractError("extension evidence lacks validated semantic assignment")
            periods = tuple(sorted(set(re.findall(r"\b20\d{2}\b", str(metadata.get("observation_period", ""))))))
            aspects = tuple(str(item) for item in assignment.get("required_aspect_refs", ()) if str(item))
            aspect_text = " ".join(aspects).casefold()
            if any(token in aspect_text for token in ("real_volume", "real volume", "constant_price", "constant price")):
                authority_kind = "retail_real_volume"
            elif "deflator" in aspect_text:
                authority_kind = "retail_deflator"
            elif "cpi" in aspect_text or "consumer price" in aspect_text:
                authority_kind = "cpi"
            else:
                authority_kind = "nominal"
            lineage = metadata.get("data_lineage") if isinstance(metadata.get("data_lineage"), dict) else {}
            source_identity = str(
                lineage.get("origin_id") or metadata.get("acquired_content_identity") or value.source_id
            )
            geography_values = assignment.get("geography_applicability", ())
            geography = str(geography_values[0]) if isinstance(geography_values, list) and geography_values else ""
            observations.append(AuthorityObservation(
                evidence_id=value.id, source_identity=source_identity,
                information_need_ids=tuple(value.information_need_refs),
                research_question_ids=tuple(value.research_question_refs),
                metric=" ".join(aspects) or value.statement, geography=geography,
                periods=periods, authority_kind=authority_kind,
                workflow_run_id=value.workflow_run_id, research_design_id=value.research_design_id,
                project_id=value.project_id, conflicting=bool(metadata.get("conflicting", False)),
            ))
        self.service.record_observations(context.workflow_run.id, observations)

    def _capture_findings(self, context: WorkflowContext) -> None:
        values = self.finding_repository.list_for_project(
            context.project.id, workflow_run_id=context.workflow_run.id,
        )
        findings = []
        for value in values:
            if len(value.information_need_refs) != 1:
                raise ExtensionContractError("extension finding must own exactly one selected information need")
            findings.append(ExtensionFinding(
                finding_id=value.id, information_need_id=value.information_need_refs[0],
                evidence_ids=tuple(value.evidence_refs), workflow_run_id=value.workflow_run_id,
                project_id=value.project_id, research_design_id=value.research_design_id,
            ))
        self.service.record_findings(context.workflow_run.id, findings)
