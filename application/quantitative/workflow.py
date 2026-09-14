from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol

from application.contracts.base_executor import BaseExecutor
from application.runtime.checkpoint_context import CHECKPOINT_SERVICE_KEY
from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import canonical_approval_fingerprint, canonical_digest
from application.quantitative.state_persistence import QuantitativeStateService
from domain.quantitative.workflow import (
    QuantitativeApproval,
    QuantitativeApprovalDecision,
    QuantitativeSemanticAuthorization,
    QuantitativeSemanticAuthorizationConsumption,
    QuantitativeSemanticAuthorizationState,
)
from domain.value_objects.executor_type import ExecutorType
from domain.value_objects.task_status import TaskStatus
from domain.workflow import Workflow
from domain.workflow_template import WorkflowTemplate
from domain.workflow_status import WorkflowStatus
from runtime.workflow_context import WorkflowContext


QUANTITATIVE_WORKFLOW_ID = "quantitative-consumer-survey-v1"
QUANTITATIVE_STAGE_SERVICE_KEY = "quantitative_stage_service"
QUANTITATIVE_SAFE_STATE_KEY = "quantitative"
SEMANTIC_PIPELINE_BOUNDARY = "PRE_QI_SEMANTIC_PIPELINE_V1"
SEMANTIC_AUTHORITY_FINGERPRINT_KEY = "semantic_authority_fingerprint"

STAGES = (
    ("quant_import", "Quantitative import"),
    ("quant_qc", "Quantitative QC"),
    ("quant_qc_approval", "QC approval"),
    ("quant_cleaning", "Approved cleaning"),
    ("quant_weightset", "Weighting authority"),
    ("quant_weight_approval", "Weighting authorization"),
    ("quant_analysis", "Deterministic analysis"),
    ("quant_findings", "Quantitative Findings"),
    ("quant_insights", "Quantitative Insights"),
    ("quant_report", "Quantitative Report"),
    ("quant_rq_coverage", "RQ coverage"),
    ("quant_complete", "Quantitative completion"),
)


class QuantitativeWorkflowError(RuntimeError):
    pass


class QuantitativeApprovalRequired(QuantitativeWorkflowError):
    def __init__(self, *, subject_type: str, subject_id: str, subject_fingerprint: str, state_updates: Mapping[str, str] | None = None):
        super().__init__(f"{subject_type} approval is required")
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.subject_fingerprint = subject_fingerprint
        self.state_updates = validate_safe_workflow_state(state_updates or {})


class QuantitativeStageService(Protocol):
    def execute_stage(
        self, stage_id: str, *, project_id: str, run_id: str,
        safe_state: Mapping[str, str],
    ) -> Mapping[str, str]: ...


def build_quantitative_workflow_template() -> WorkflowTemplate:
    workflow = Workflow(id=QUANTITATIVE_WORKFLOW_ID, name="Quantitative consumer survey V1")
    previous: str | None = None
    for stage_id, name in STAGES:
        depends_on = [] if previous is None else [previous]
        workflow.task(
            id=stage_id,
            name=name,
            executor_id="quantitative-stage",
            executor_type=ExecutorType.TOOL,
            depends_on=depends_on,
            metadata={"methodology": "QUANTITATIVE", "stage": stage_id},
        )
        previous = stage_id
    return workflow.build()


def validate_safe_workflow_state(value: Mapping[str, object]) -> dict[str, str]:
    forbidden = {"rows", "respondents", "pii", "raw_bytes", "pseudonym_bindings"}
    if forbidden.intersection(key.casefold() for key in value):
        raise QuantitativeWorkflowError("respondent-level data is forbidden in workflow state")
    safe: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise QuantitativeWorkflowError("Quantitative workflow state permits string IDs/fingerprints only")
        if len(item) > 512:
            raise QuantitativeWorkflowError("Quantitative workflow state value is not bounded")
        safe[key] = item
    return safe


class QuantitativeStageExecutor(BaseExecutor):
    """Methodology-specific bridge; all analytical work remains in injected services."""

    def run(self, context: WorkflowContext) -> WorkflowContext:
        task = context.current_task
        service = context.services.get(QUANTITATIVE_STAGE_SERVICE_KEY)
        if task is None or service is None or not hasattr(service, "execute_stage"):
            raise QuantitativeWorkflowError("Quantitative stage service is unavailable")
        state = validate_safe_workflow_state(
            context.shared_state.get(QUANTITATIVE_SAFE_STATE_KEY, {})
        )
        try:
            if task.definition_id == "quant_analysis" and getattr(service,"supports_progress_checkpoint",False):
                checkpoint=context.services.get(CHECKPOINT_SERVICE_KEY)
                def progress(manifest_id):
                    state["analysis_execution_progress_manifest_id"]=manifest_id
                    context.shared_state[QUANTITATIVE_SAFE_STATE_KEY]=validate_safe_workflow_state(state)
                    if checkpoint is not None: checkpoint.on_task_progress(context)
                updated=service.execute_stage(task.definition_id,project_id=context.project.id,run_id=context.workflow_run.id,safe_state=state,progress_callback=progress)
            else:
                updated = service.execute_stage(
                    task.definition_id,
                    project_id=context.project.id,
                    run_id=context.workflow_run.id,
                    safe_state=state,
                )
        except QuantitativeApprovalRequired as required:
            state.update(required.state_updates)
            state.update(
                awaiting_approval_subject_type=required.subject_type,
                awaiting_approval_subject_id=required.subject_id,
                awaiting_approval_subject_fingerprint=required.subject_fingerprint,
            )
            context.shared_state[QUANTITATIVE_SAFE_STATE_KEY] = state
            task.pause()
            context.workflow_run.pause()
            return context
        context.shared_state[QUANTITATIVE_SAFE_STATE_KEY] = validate_safe_workflow_state(updated)
        return context


def resume_after_quantitative_approval(context: WorkflowContext) -> None:
    task = context.current_task
    if task is None or context.workflow_run.status is not WorkflowStatus.PAUSED or task.status is not TaskStatus.PAUSED:
        raise QuantitativeWorkflowError("workflow is not awaiting a Quantitative approval")
    # The caller must persist/validate the approval before invoking this control.
    task.resume()
    task.requeue_after_interrupt()
    context.workflow_run.resume()


@dataclass(frozen=True)
class QuantitativeApprovalService:
    state_service: QuantitativeStateService
    digest_provider: DeterministicDigestProvider

    def record(
        self, *, approval_id: str, project_id: str, run_id: str,
        subject_type: str, subject_id: str, subject_fingerprint: str,
        decision: QuantitativeApprovalDecision, actor_id: str,
        decided_at: str, rationale: str,
    ) -> QuantitativeApproval:
        authority_fingerprint = canonical_approval_fingerprint(
            contract="QUANTITATIVE_APPROVAL_AUTHORITY_V2",
            project_id=project_id, subject_type=subject_type,
            subject_id=subject_id, subject_fingerprint=subject_fingerprint,
            decision=decision.value, actor_id=actor_id, rationale=rationale,
            stable_authority={"run_id": run_id},
            digest_provider=self.digest_provider,
        )
        approval = QuantitativeApproval(
            approval_id=approval_id, project_id=project_id, run_id=run_id,
            subject_type=subject_type, subject_id=subject_id,
            subject_fingerprint=subject_fingerprint, decision=decision,
            actor_id=actor_id, decided_at=decided_at, rationale=rationale,
            current=True,
            fingerprint=authority_fingerprint,
        )
        self.state_service.persist(
            approval, record_id=approval_id, project_id=project_id, run_id=run_id,
            accepted=decision is QuantitativeApprovalDecision.APPROVED,
        )
        return approval

    def semantic_authority_fingerprint(self, *, project_id: str, run_id: str, safe_state: Mapping[str, str]) -> str:
        excluded = {SEMANTIC_AUTHORITY_FINGERPRINT_KEY, "awaiting_approval_subject_type", "awaiting_approval_subject_id", "awaiting_approval_subject_fingerprint"}
        stable = {key: value for key, value in safe_state.items() if key not in excluded and not key.startswith("semantic_authorization_")}
        return canonical_digest({"contract": "QUANTITATIVE_PRE_SEMANTIC_AUTHORITY_V1", "project_id": project_id, "run_id": run_id, "boundary": SEMANTIC_PIPELINE_BOUNDARY, "safe_state": stable}, digest_provider=self.digest_provider)

    def grant_semantic_pipeline(self, *, project_id: str, run_id: str, quantitative_authority_fingerprint: str, actor_id: str, authorized_at: str, rationale: str) -> QuantitativeSemanticAuthorization:
        payload = {"contract": "QUANTITATIVE_SEMANTIC_AUTHORIZATION_V1", "project_id": project_id, "run_id": run_id, "boundary": SEMANTIC_PIPELINE_BOUNDARY, "quantitative_authority_fingerprint": quantitative_authority_fingerprint, "state": QuantitativeSemanticAuthorizationState.AUTHORIZED.value, "actor_id": actor_id, "rationale": rationale}
        fingerprint = canonical_digest(payload, digest_provider=self.digest_provider)
        value = QuantitativeSemanticAuthorization(f"{run_id}:semantic-authorization:{fingerprint}", project_id, run_id, SEMANTIC_PIPELINE_BOUNDARY, quantitative_authority_fingerprint, QuantitativeSemanticAuthorizationState.AUTHORIZED, actor_id, authorized_at, rationale, fingerprint)
        existing = self.state_service.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeSemanticAuthorization)
        if existing:
            if len(existing) != 1 or existing[0].fingerprint != value.fingerprint:
                raise QuantitativeWorkflowError("conflicting semantic authorization authority")
            return existing[0]
        self.state_service.persist(value, record_id=value.authorization_id, project_id=project_id, run_id=run_id, accepted=True)
        return value

    def require_semantic_pipeline(self, *, project_id: str, run_id: str, safe_state: Mapping[str, str]) -> QuantitativeSemanticAuthorization:
        fingerprint = self.semantic_authority_fingerprint(project_id=project_id, run_id=run_id, safe_state=safe_state)
        declared = safe_state.get(SEMANTIC_AUTHORITY_FINGERPRINT_KEY)
        if declared is not None and declared != fingerprint:
            raise QuantitativeWorkflowError("stale semantic authorization boundary")
        grants = self.state_service.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeSemanticAuthorization)
        matching = tuple(item for item in grants if item.project_id == project_id and item.run_id == run_id and item.boundary == SEMANTIC_PIPELINE_BOUNDARY and item.quantitative_authority_fingerprint == fingerprint and item.state is QuantitativeSemanticAuthorizationState.AUTHORIZED)
        if len(matching) != 1:
            raise QuantitativeApprovalRequired(subject_type="SEMANTIC_PIPELINE", subject_id=SEMANTIC_PIPELINE_BOUNDARY, subject_fingerprint=fingerprint, state_updates={SEMANTIC_AUTHORITY_FINGERPRINT_KEY: fingerprint})
        grant = matching[0]
        if self.state_service.list_for_run(run_id, project_id=project_id, expected_type=QuantitativeSemanticAuthorizationConsumption):
            raise QuantitativeWorkflowError("semantic authorization was already consumed")
        return grant

    def require_and_consume_semantic_pipeline(self, *, project_id: str, run_id: str, safe_state: Mapping[str, str]) -> QuantitativeSemanticAuthorizationConsumption:
        grant = self.require_semantic_pipeline(project_id=project_id, run_id=run_id, safe_state=safe_state)
        fingerprint = self.semantic_authority_fingerprint(project_id=project_id, run_id=run_id, safe_state=safe_state)
        consumption_fingerprint = canonical_digest({"contract": "QUANTITATIVE_SEMANTIC_AUTHORIZATION_CONSUMPTION_V1", "authorization": grant.fingerprint, "project_id": project_id, "run_id": run_id, "boundary": SEMANTIC_PIPELINE_BOUNDARY, "quantitative_authority_fingerprint": fingerprint, "state": QuantitativeSemanticAuthorizationState.CONSUMED.value}, digest_provider=self.digest_provider)
        value = QuantitativeSemanticAuthorizationConsumption(f"{run_id}:semantic-consumption:{consumption_fingerprint}", grant.authorization_id, grant.fingerprint, project_id, run_id, SEMANTIC_PIPELINE_BOUNDARY, fingerprint, QuantitativeSemanticAuthorizationState.CONSUMED, datetime.now(timezone.utc).isoformat(), consumption_fingerprint)
        self.state_service.persist(value, record_id=value.consumption_id, project_id=project_id, run_id=run_id, accepted=True)
        return value

    def require_current(
        self, approval_id: str, *, project_id: str, subject_fingerprint: str,
    ) -> QuantitativeApproval:
        approval = self.state_service.load(
            approval_id, project_id=project_id, expected_type=QuantitativeApproval
        )
        if (
            not approval.current
            or approval.subject_fingerprint != subject_fingerprint
            or approval.decision is not QuantitativeApprovalDecision.APPROVED
        ):
            raise QuantitativeWorkflowError("approval is rejected, stale, or non-current")
        return approval
