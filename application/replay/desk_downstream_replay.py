from __future__ import annotations

import os
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4

from application.methods.desk.profile import PIN
from application.persistence.exceptions import AccessDeniedError
from domain.task_definition import TaskDefinition
from domain.workflow_status import WorkflowStatus
from domain.workflow_template import WorkflowTemplate


REPLAY_KEY = "desk_downstream_replay_v1"
REPLAY_TEMPLATE_PREFIX = "desk-downstream-replay-v1:"


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
        "finalization_pending" if stage == "deliverables" and status in {"pptx_queued", "pptx_running"} else
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
                 findings, insights, activation_sessions=None) -> None:
        self.projects = projects
        self.workflows = workflows
        self.durable_workflows = durable_workflows
        self.evidence = evidence
        self.findings = findings
        self.insights = insights
        self.activation_sessions = activation_sessions

    def start(self, *, project_id: str, source_run_id: str, owner_id: str):
        project = self.projects.get_project(project_id)
        if project.owner_principal_id != owner_id:
            raise AccessDeniedError("Проєкт не знайдено")
        boundary = (self.activation_sessions.activation(project_id)
                    if self.activation_sessions is not None else nullcontext())
        with boundary:
            return self._start_locked(project, source_run_id)

    def _start_locked(self, project, source_id):
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

        for run in self.workflows.list_workflow_runs_for_project(project.id):
            state = self.workflows.get_task_results(run.id).get(REPLAY_KEY)
            if isinstance(state, dict) and state.get("source_workflow_run_id") == source.id:
                if not run.is_terminal:
                    return run
                if run.status == WorkflowStatus.COMPLETED:
                    return run

        attempt_id = str(uuid4())
        template = WorkflowTemplate(
            id=f"{REPLAY_TEMPLATE_PREFIX}{attempt_id}",
            name="Desk downstream finalization replay",
            task_definitions=[
                TaskDefinition("report", "Replay: Write research report", "report"),
                TaskDefinition("review", "Replay: Review and finalize", "review", depends_on=["report"]),
            ],
            research_brief_snapshot=brief,
            research_design_snapshot=design,
        )
        lineage = {
            "version": 1,
            "project_id": project.id,
            "source_workflow_run_id": source.id,
            "replay_attempt_id": attempt_id,
            "research_design_id": design.id,
            "research_subject_id": design.research_subject.subject_id,
            "runtime_sha": os.environ.get("APP_SHA"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "budget_scope": "downstream_report_review_only",
            "allowed_provider_stages": ["report", "review"],
            "status": "pending",
            "downstream_stages": {"report": "pending", "review": "pending", "deliverables": "pending"},
        }
        initial = {REPLAY_KEY: lineage, "research_readiness": readiness}
        if PIN in task_results:
            initial[PIN] = task_results[PIN]
        return self.durable_workflows.submit_research(
            project, template, initial_task_results=initial).workflow_run
