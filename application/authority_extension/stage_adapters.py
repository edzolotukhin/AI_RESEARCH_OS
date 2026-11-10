from __future__ import annotations

from dataclasses import dataclass, replace
from contextvars import ContextVar
import re
from typing import Any

from application.authority_extension.selected_workflow import (
    EXISTING_QUALIFYING_EVIDENCE_ONLY, AuthorityObservation, ExtensionContractError, ExtensionFinding,
)
from application.authority_extension.remediation import evidence_observation
from application.contracts.base_executor import BaseExecutor
from application.runtime.task_result_codec import capture_task_result
from application.runtime.checkpoint_context import CHECKPOINT_FAILURE_HANDLER_KEY
from runtime.workflow_context import WorkflowContext

_extension_dispatch: ContextVar[tuple[Any, str, str] | None] = ContextVar("authority_extension_dispatch", default=None)
_extension_runtime_context: ContextVar[Any | None] = ContextVar(
    "authority_extension_runtime_context",
    default=None,
)


class ExtensionSearchBudgetProxy:
    def __init__(self, delegate) -> None: self._delegate = delegate
    def supports_retrieval_arm(self, arm, query): return self._delegate.supports_retrieval_arm(arm, query)
    def search(self, query):
        current = _extension_dispatch.get()
        if current is None: return self._delegate.search(query)
        service, run_id, *_ = current
        return service.dispatch_search(
            run_id, lambda: self._delegate.search(query),
            information_need_id=query.information_need_id,
        )


class ExtensionProviderBudgetProxy:
    def __init__(self, delegate) -> None: self._delegate = delegate
    def generate(self, *args, **kwargs):
        current = _extension_dispatch.get()
        if current is None: return self._delegate.generate(*args, **kwargs)
        service, run_id, *stage = current
        return service.dispatch_provider(
            run_id,
            lambda: self._delegate.generate(*args, **kwargs),
            stage=stage[0] if stage else None,
        )
    def __getattr__(self, name): return getattr(self._delegate, name)


class ExtensionImmutableSourceRepositoryProxy:
    """Prevents rediscovery from appending extension refs to a parent Source."""
    def __init__(self, delegate) -> None: self._delegate = delegate
    def save(self, source, *, expected_version=None):
        current = _extension_dispatch.get()
        if current is not None:
            _, run_id, *_ = current
            persisted = self._delegate.get_by_id(source.id)
            if persisted is not None and run_id not in persisted.workflow_run_refs:
                return persisted.version
        return self._delegate.save(source, expected_version=expected_version)

    def list_for_project(
        self,
        project_id,
        *,
        research_question_id=None,
        retrieval_status=None,
        workflow_run_id=None,
    ):
        values = self._delegate.list_for_project(
            project_id,
            research_question_id=research_question_id,
            retrieval_status=retrieval_status,
            workflow_run_id=workflow_run_id,
        )
        current = _extension_dispatch.get()
        context = _extension_runtime_context.get()
        if current is None or context is None:
            return values
        service, run_id, *_ = current
        if workflow_run_id != run_id:
            return values

        acquisition = context.read_shared("source_acquisition")
        funnel = context.read_shared("research_funnel_v1")
        if not isinstance(acquisition, dict) or not isinstance(funnel, dict):
            return values
        raw_source_ids = acquisition.get("source_ids")
        raw_events = funnel.get("events")
        if not isinstance(raw_source_ids, list) or not isinstance(raw_events, list):
            return values

        extension = service.extensions.get_by_id(service._state(run_id).extension_id)
        gaps = {gap.information_need_id: gap for gap in service._state(run_id).gaps}
        needs_by_source: dict[str, set[str]] = {}
        for event in raw_events:
            if not isinstance(event, dict) or event.get("kind") != "candidate_decision":
                continue
            source_id = str(event.get("source_id") or "")
            need_id = str(event.get("target_in") or "")
            if source_id and need_id in gaps:
                needs_by_source.setdefault(source_id, set()).add(need_id)

        by_id = {source.id: source for source in values}
        for raw_source_id in raw_source_ids:
            source_id = str(raw_source_id)
            if source_id in by_id:
                continue
            source = self._delegate.get_by_id(source_id)
            need_ids = tuple(sorted(needs_by_source.get(source_id, ())))
            if source is None or source.project_id != project_id or not need_ids:
                continue
            question_ids = tuple(
                dict.fromkeys(gaps[need_id].research_question_id for need_id in need_ids)
            )
            if research_question_id is not None and research_question_id not in question_ids:
                continue
            if retrieval_status is not None and source.retrieval_status.value != retrieval_status:
                continue
            records = list((source.metadata or {}).get("discovery_records") or [])
            records.extend(
                {
                    "workflow_run_id": run_id,
                    "research_design_id": extension.research_design_id,
                    "research_question_id": gaps[need_id].research_question_id,
                    "information_need_id": need_id,
                    "query_id": f"sq-{need_id}",
                }
                for need_id in need_ids
            )
            virtual = replace(
                source,
                query_refs=tuple(
                    dict.fromkeys(
                        (*source.query_refs, *(f"sq-{item}" for item in need_ids)),
                    ),
                ),
                research_question_refs=tuple(
                    dict.fromkeys((*source.research_question_refs, *question_ids)),
                ),
                information_need_refs=tuple(
                    dict.fromkeys((*source.information_need_refs, *need_ids)),
                ),
                workflow_run_refs=tuple(
                    dict.fromkeys((*source.workflow_run_refs, run_id)),
                ),
                research_design_refs=tuple(
                    dict.fromkeys(
                        (*source.research_design_refs, extension.research_design_id),
                    ),
                ),
                metadata={**(source.metadata or {}), "discovery_records": records},
            )
            by_id[virtual.id] = virtual
        return sorted(by_id.values(), key=lambda item: item.id)

    def __getattr__(self, name): return getattr(self._delegate, name)


@dataclass
class AuthorityExtensionStageExecutor(BaseExecutor):
    stage: str
    service: Any
    delegate: Any | None = None
    evidence_repository: Any | None = None
    finding_repository: Any | None = None
    remediation_adapter: Any | None = None

    def run(self, context: WorkflowContext) -> WorkflowContext:
        run_id = context.workflow_run.id
        context.services[CHECKPOINT_FAILURE_HANDLER_KEY] = (
            lambda error: self.service.fail_technical(
                run_id,
                type(error).__name__,
            )
        )
        with self.service.runtime_state_scope(context):
            return self._run_in_scope(context)

    def _run_in_scope(self, context: WorkflowContext) -> WorkflowContext:
        run_id = context.workflow_run.id
        execution_mode = self.service._state(run_id).execution_mode
        try:
            if self.stage == "extension_plan":
                state = self.service._state(run_id)
                state = self.service.reserve_analysis_budget(run_id)
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
            elif self.stage in {"extension_search", "extension_evidence"} and execution_mode == EXISTING_QUALIFYING_EVIDENCE_ONLY:
                # Existing-evidence mode deliberately consumes only persisted parent
                # authority; acquisition and extraction are not entered.
                pass
            elif self.stage in {"extension_search", "extension_evidence"}:
                if self.delegate is None:
                    raise ExtensionContractError("extension stage delegate unavailable")
                token = _extension_dispatch.set((self.service, run_id, self.stage.removeprefix("extension_")))
                context_token = _extension_runtime_context.set(context)
                try:
                    context = self.delegate.run(context)
                finally:
                    _extension_runtime_context.reset(context_token)
                    _extension_dispatch.reset(token)
                if self.stage == "extension_evidence":
                    self._capture_evidence(context)
            elif self.stage == "extension_readiness":
                if execution_mode == EXISTING_QUALIFYING_EVIDENCE_ONLY:
                    self._capture_evidence(context)
                elif self.remediation_adapter is not None:
                    token = _extension_dispatch.set((self.service, run_id, "evidence"))
                    context_token = _extension_runtime_context.set(context)
                    try:
                        context = self.remediation_adapter.run(context)
                    finally:
                        _extension_runtime_context.reset(context_token)
                        _extension_dispatch.reset(token)
                    self._capture_evidence(context)
                self.service.evaluate(run_id)
            elif self.stage == "extension_analysis":
                allowed, reason = self.service.analysis_gate(run_id)
                if not allowed:
                    context.write_shared("authority_extension_analysis_gate", {
                        "allowed": False,
                        "reason": reason,
                    })
                    task = context.current_task
                    if task is not None:
                        context.intermediate_results[task.id] = capture_task_result(
                            context,
                            task.id,
                        )
                    return context
                if self.delegate is None:
                    raise ExtensionContractError("extension analysis delegate unavailable")
                token = _extension_dispatch.set((self.service, run_id, "analysis"))
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
            if not isinstance(metadata.get("semantic_assignment"), dict):
                raise ExtensionContractError("extension evidence lacks validated semantic assignment")
            observations.append(evidence_observation(value))
        self.service.record_observations(context.workflow_run.id, observations)

    def _capture_findings(self, context: WorkflowContext) -> None:
        state = self.service._state(context.workflow_run.id)
        extension = self.service.extensions.get_by_id(state.extension_id)
        assert extension is not None
        selected = set(extension.selected_information_need_ids)
        values = self.finding_repository.list_for_project(
            context.project.id, workflow_run_id=context.workflow_run.id,
        )
        findings = []
        for value in values:
            if len(value.information_need_refs) != 1:
                raise ExtensionContractError("extension finding must own exactly one selected information need")
            if value.information_need_refs[0] not in selected:
                raise ExtensionContractError("extension finding owns an unselected information need")
            if (value.project_id, value.research_design_id, value.workflow_run_id) != (
                extension.project_id, extension.research_design_id, context.workflow_run.id,
            ):
                raise ExtensionContractError("finding ownership mismatch")
            findings.append(ExtensionFinding(
                finding_id=value.id, information_need_id=value.information_need_refs[0],
                evidence_ids=tuple(value.evidence_refs), workflow_run_id=value.workflow_run_id,
                project_id=value.project_id, research_design_id=value.research_design_id,
            ))
        self.service.record_findings(context.workflow_run.id, findings)
