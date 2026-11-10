from __future__ import annotations

import os
import hashlib
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4

from application.methods.desk.profile import PIN
from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from domain.task_definition import TaskDefinition
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate
from application.evidence.temporal_scope import qualifying_evidence
from application.report.h3_coverage_plan import build_h3_coverage_plan


REPLAY_KEY = "desk_downstream_replay_v1"
REPLAY_TEMPLATE_PREFIX = "desk-downstream-replay-v1:"
REPLAY_IDENTITY_VERSION = "desk_downstream_replay_identity_v2"


class DeskDownstreamReplayError(ValueError):
    pass


def source_run_id(context) -> str:
    value = context.read_shared(REPLAY_KEY)
    if isinstance(value, dict) and isinstance(value.get("source_workflow_run_id"), str):
        return value["source_workflow_run_id"]
    return context.workflow_run.id


def update_replay_stage(context, stage: str, status: str, *, failure_code: str | None = None) -> None:
    """Update bounded replay lineage without changing ordinary workflow runs."""
    value = context.read_shared(REPLAY_KEY)
    if not isinstance(value, dict):
        return
    lineage = dict(value)
    stages = dict(lineage.get("downstream_stages") or {})
    if stage in {"report", "review", "deliverables"}:
        stages[stage] = status
    lineage["downstream_stages"] = stages
    lineage["status"] = (
        "failed" if status == "failed" else
        "completed" if stage == "deliverables" and status in {"completed", "skipped"} else
        "finalization_pending" if stage == "deliverables" and status in {
            "review_approved", "pdf_generating", "pdf_complete", "pptx_queued",
            "pptx_pending", "pptx_running", "pptx_processing", "pptx_retry_wait",
        } else
        "running"
    )
    if failure_code:
        lineage["failure_code"] = str(failure_code)[:120]
    context.write_shared(REPLAY_KEY, lineage)


def _shared_value(task_results, key):
    found = task_results.get(key)
    for value in task_results.values():
        if isinstance(value, dict) and isinstance(value.get("shared_state"), dict):
            candidate = value["shared_state"].get(key)
            if candidate is not None:
                found = candidate
    return found


class DeskDownstreamReplayService:
    def __init__(self, *, projects, workflows, durable_workflows, evidence,
                 findings, insights, activation_sessions=None,
                 composed_authorities=None,
                 sources=None,
                 desk_report_contract_version="desk_report_claim_v1") -> None:
        self.projects = projects
        self.workflows = workflows
        self.durable_workflows = durable_workflows
        self.evidence = evidence
        self.findings = findings
        self.insights = insights
        self.activation_sessions = activation_sessions
        self.composed_authorities = composed_authorities
        self.sources = sources
        from application.report.contract_selection import validate_desk_report_contract
        self.desk_report_contract_version = validate_desk_report_contract(
            desk_report_contract_version,
        )

    def start(self, *, project_id: str, source_run_id: str, owner_id: str):
        project = self.projects.get_project(project_id)
        if project.owner_principal_id != owner_id:
            raise AccessDeniedError("Проєкт не знайдено")
        boundary = (self.activation_sessions.activation(project_id)
                    if self.activation_sessions is not None else nullcontext())
        with boundary:
            return self._start_locked(project, source_run_id)

    def can_start(self, *, project_id: str, source_run_id: str, owner_id: str) -> bool:
        """Return whether the exact run is a valid downstream replay source.

        This is a read-only UI capability check. ``start`` repeats the same
        validation under the activation boundary before creating anything.
        """
        try:
            project = self.projects.get_project(project_id)
            if project.owner_principal_id != owner_id:
                return False
            self._validate_source(project, source_run_id)
            return True
        except (AccessDeniedError, EntityNotFoundError, DeskDownstreamReplayError):
            return False

    def reusable_source_run_id(self, *, project_id: str, run_id: str, owner_id: str) -> str | None:
        """Resolve one displayed Desk attempt to its reusable upstream source.

        Replay lineage is intentionally bounded to the persisted one-hop replay
        model.  Eligibility remains delegated to ``can_start`` so this helper
        cannot create a weaker UI-only contract.
        """
        if self.can_start(project_id=project_id, source_run_id=run_id, owner_id=owner_id):
            return run_id
        try:
            project = self.projects.get_project(project_id)
            if project.owner_principal_id != owner_id:
                return None
            run = self.workflows.get_workflow_run(run_id)
            if run.project_id != project_id:
                return None
            lineage = self.workflows.get_task_results(run_id).get(REPLAY_KEY)
            if not isinstance(lineage, dict):
                return None
            source_id = lineage.get("source_workflow_run_id")
            if not isinstance(source_id, str) or source_id == run_id:
                return None
            source_lineage = self.workflows.get_task_results(source_id).get(REPLAY_KEY)
            if isinstance(source_lineage, dict):
                return None
            if self.can_start(project_id=project_id, source_run_id=source_id, owner_id=owner_id):
                return source_id
        except (AccessDeniedError, EntityNotFoundError, DeskDownstreamReplayError):
            return None
        return None

    def _start_locked(self, project, source_id):
        source, source_template, design, readiness, task_results = (
            self._validate_source(project, source_id)
        )

        composition, replay_identity = self._composition_preflight(
            project=project, source=source, design=design,
            brief=source_template.research_brief_snapshot,
        )

        for run in self.workflows.list_workflow_runs_for_project(project.id):
            state = self.workflows.get_task_results(run.id).get(REPLAY_KEY)
            if not isinstance(state, dict):
                continue
            same_identity = (
                replay_identity is not None
                and state.get("replay_identity") == replay_identity
            )
            legacy_source_match = (
                replay_identity is None
                and state.get("source_workflow_run_id") == source.id
            )
            if same_identity or legacy_source_match:
                if not run.is_terminal:
                    return run
                if run.status == WorkflowStatus.COMPLETED:
                    return run

        attempt_id = str(uuid4())
        from application.report.contract_selection import H3_REPORT_CONTRACT
        if self.desk_report_contract_version == H3_REPORT_CONTRACT:
            replay_tasks = [
                TaskDefinition("report", "Replay: Write research report", "report"),
                TaskDefinition("task-review-report-1", "Replay: Review report (round 1)", "review", depends_on=["report"]),
                TaskDefinition("task-revise-report", "Replay: Revise report", "revision", depends_on=["task-review-report-1"]),
                TaskDefinition("task-review-report-2", "Replay: Review report (round 2)", "review", depends_on=["task-revise-report"]),
                TaskDefinition("finalization", "Replay: Finalize PDF and PPTX", "finalization",
                               depends_on=["task-review-report-1", "task-revise-report", "task-review-report-2"]),
            ]
        else:
            replay_tasks = [
                TaskDefinition("report", "Replay: Write research report", "report"),
                TaskDefinition("review", "Replay: Review and finalize", "review", depends_on=["report"]),
                TaskDefinition("finalization", "Replay: Finalize PDF and PPTX", "finalization", depends_on=["review"]),
            ]
        template = WorkflowTemplate(
            id=f"{REPLAY_TEMPLATE_PREFIX}{attempt_id}",
            name="Desk downstream finalization replay",
            task_definitions=replay_tasks,
            research_brief_snapshot=source_template.research_brief_snapshot,
            research_design_snapshot=design,
        )
        lineage = {
            "version": 1,
            "project_id": project.id,
            "source_workflow_run_id": source.id,
            "replay_attempt_id": attempt_id,
            "replay_identity_version": REPLAY_IDENTITY_VERSION if replay_identity else None,
            "replay_identity": replay_identity,
            "research_design_id": design.id,
            "research_subject_id": design.research_subject.subject_id,
            "runtime_sha": os.environ.get("APP_SHA"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "budget_scope": "downstream_report_review_finalization",
            "allowed_provider_stages": ["report", "review"],
            "status": "pending",
            "downstream_stages": {"report": "pending", "review": "pending", "deliverables": "pending"},
        }
        from application.report.contract_selection import pin_desk_report_contract
        initial = pin_desk_report_contract(
            {REPLAY_KEY: lineage, "research_readiness": readiness},
            self.desk_report_contract_version,
        )
        if composition is not None:
            from application.authority_extension import COMPOSED_AUTHORITY_KEY
            initial[COMPOSED_AUTHORITY_KEY] = {
                "composition_id": composition.composition_id,
                "composition_digest": composition.composition_digest,
            }
        if PIN in task_results:
            initial[PIN] = task_results[PIN]
        return self.durable_workflows.submit_research(
            project, template, initial_task_results=initial).workflow_run

    def _composition_preflight(self, *, project, source, design, brief):
        if self.composed_authorities is None:
            return None, None
        composition = self.composed_authorities.get_latest_for_parent(
            project.id, source.id,
        )
        if composition is None:
            return None, None
        if (
            composition.project_id != project.id
            or composition.research_design_id != design.id
            or composition.parent_source_workflow_run_id != source.id
        ):
            raise DeskDownstreamReplayError("composed_authority_lineage_mismatch")
        members = tuple(composition.member_workflow_run_ids)
        if not members or source.id not in members:
            raise DeskDownstreamReplayError("composed_authority_membership_invalid")
        for member_id in members:
            member = self.workflows.get_workflow_run(member_id)
            if member.project_id != project.id:
                raise DeskDownstreamReplayError("composed_authority_foreign_member")
            member_template = self.workflows.get_template(member.workflow_template_id)
            member_design = member_template.research_design_snapshot
            if member_design is None or member_design.id != design.id:
                raise DeskDownstreamReplayError("composed_authority_member_design_mismatch")

        evidence = [
            item for member_id in members
            for item in self.evidence.list_for_project(project.id, workflow_run_id=member_id)
        ]
        findings = [
            item for member_id in members
            for item in self.findings.list_for_project(project.id, workflow_run_id=member_id)
        ]
        insights = [
            item for member_id in members
            for item in self.insights.list_for_project(project.id, workflow_run_id=member_id)
        ]
        needs = {item.id for item in design.information_needs}
        evidence_by_id = {item.id: item for item in evidence}
        finding_ids = {item.id for item in findings}
        if any(
            item.project_id != project.id
            or item.research_design_id != design.id
            or item.workflow_run_id not in members
            for item in (*evidence, *findings, *insights)
        ):
            raise DeskDownstreamReplayError("composed_authority_member_lineage_invalid")
        if any(
            not item.evidence_refs
            or not set(item.evidence_refs) <= set(evidence_by_id)
            or not set(item.information_need_refs) <= needs
            for item in findings
        ):
            raise DeskDownstreamReplayError("composed_authority_finding_provenance_invalid")
        if any(
            not item.finding_refs or not set(item.finding_refs) <= finding_ids
            for item in insights
        ):
            raise DeskDownstreamReplayError("composed_authority_insight_provenance_invalid")
        if self.sources is None:
            raise DeskDownstreamReplayError("composed_authority_source_repository_missing")
        qualifying = qualifying_evidence(
            design=design, evidence=evidence, brief=brief,
            source_repository=self.sources,
        )
        qualifying_by_id = {item.id: item for item in qualifying}
        findings = [
            item for item in findings
            if item.evidence_refs
            and set(item.evidence_refs) <= set(qualifying_by_id)
        ]
        plan = build_h3_coverage_plan(
            design=design,
            required_information_need_ids=tuple(sorted(needs)),
            findings=tuple(findings),
            evidence_by_id=qualifying_by_id,
            insights=tuple(insights),
        )
        if not plan.is_fully_fillable:
            raise DeskDownstreamReplayError(
                "composed_authority_insufficient_coverage:"
                + ",".join(item.information_need_id for item in plan.unfillable_required_information_needs)
            )
        payload = {
            "version": REPLAY_IDENTITY_VERSION,
            "project_id": project.id,
            "parent_workflow_run_id": source.id,
            "research_design_id": design.id,
            "composition_id": composition.composition_id,
            "composition_digest": composition.composition_digest,
            "member_workflow_run_ids": sorted(members),
            "report_contract_version": self.desk_report_contract_version,
        }
        identity = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return composition, identity

    def _validate_source(self, project, source_id):
        source = self.workflows.get_workflow_run(source_id)
        if source.project_id != project.id or source.status not in {
                WorkflowStatus.FAILED, WorkflowStatus.COMPLETED}:
            raise DeskDownstreamReplayError("source_run_not_terminal_or_foreign")
        source_template = self.workflows.get_template(source.workflow_template_id)
        design = source_template.research_design_snapshot
        brief = source_template.research_brief_snapshot
        if design is None or brief is None or design.research_subject is None:
            raise DeskDownstreamReplayError("source_design_lineage_missing")
        task_results = self.workflows.get_task_results(source.id)
        readiness = _shared_value(task_results, "research_readiness")
        if not isinstance(readiness, dict) or not readiness.get("analysis_ready"):
            raise DeskDownstreamReplayError("source_readiness_missing_or_ineligible")

        evidence = self.evidence.list_for_project(project.id, workflow_run_id=source.id)
        findings = self.findings.list_for_project(project.id, workflow_run_id=source.id)
        insights = self.insights.list_for_project(project.id, workflow_run_id=source.id)
        rq_ids = {item.id for item in design.research_questions}
        in_ids = {item.id for item in design.information_needs}
        if not evidence or not findings or not insights:
            raise DeskDownstreamReplayError("source_upstream_artifacts_incomplete")
        if any((item.project_id, item.workflow_run_id, item.research_design_id) !=
               (project.id, source.id, design.id) for item in (*evidence, *findings, *insights)):
            raise DeskDownstreamReplayError("source_artifact_lineage_mismatch")
        evidence_ids = {item.id for item in evidence}
        finding_ids = {item.id for item in findings}
        if any(not item.evidence_refs or not set(item.evidence_refs) <= evidence_ids or
               not set(item.research_question_refs) <= rq_ids or
               not set(item.information_need_refs) <= in_ids for item in findings):
            raise DeskDownstreamReplayError("source_finding_lineage_invalid")
        if any(not item.finding_refs or not set(item.finding_refs) <= finding_ids or
               not set(item.research_question_refs) <= rq_ids for item in insights):
            raise DeskDownstreamReplayError("source_insight_lineage_invalid")
        return source, source_template, design, readiness, task_results
