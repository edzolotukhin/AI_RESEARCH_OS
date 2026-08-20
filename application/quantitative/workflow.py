from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from application.contracts.base_executor import BaseExecutor
from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.state_persistence import QuantitativeStateService
from domain.quantitative.workflow import (
    QuantitativeApproval,
    QuantitativeApprovalDecision,
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

STAGES = (
    ("quant_import", "Quantitative import"),
    ("quant_qc", "Quantitative QC"),
    ("quant_qc_approval", "QC approval"),
    ("quant_cleaning", "Approved cleaning"),
    ("quant_weightset", "Imported WeightSet"),
    ("quant_weight_approval", "WeightSet approval"),
    ("quant_analysis", "Deterministic analysis"),
    ("quant_findings", "Quantitative Findings"),
    ("quant_insights", "Quantitative Insights"),
    ("quant_report", "Quantitative Report"),
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
        workflow.task(
            id=stage_id,
            name=name,
            executor_id="quantitative-stage",
            executor_type=ExecutorType.TOOL,
            depends_on=[] if previous is None else [previous],
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
        payload = {
            "approval_id": approval_id, "project_id": project_id, "run_id": run_id,
            "subject_type": subject_type, "subject_id": subject_id,
            "subject_fingerprint": subject_fingerprint, "decision": decision.value,
            "actor_id": actor_id, "decided_at": decided_at, "rationale": rationale,
        }
        approval = QuantitativeApproval(
            approval_id=approval_id, project_id=project_id, run_id=run_id,
            subject_type=subject_type, subject_id=subject_id,
            subject_fingerprint=subject_fingerprint, decision=decision,
            actor_id=actor_id, decided_at=decided_at, rationale=rationale,
            current=True,
            fingerprint=canonical_digest(payload, digest_provider=self.digest_provider),
        )
        self.state_service.persist(
            approval, record_id=approval_id, project_id=project_id, run_id=run_id,
            accepted=decision is QuantitativeApprovalDecision.APPROVED,
        )
        return approval

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
