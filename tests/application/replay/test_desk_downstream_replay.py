from __future__ import annotations

import copy
import hashlib
import unittest
from contextlib import nullcontext
from types import SimpleNamespace

from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from api.ui.session import _POST_ACTION_SAFE_PROJECT_RETURN
from application.replay.desk_downstream_replay import (
    REPLAY_KEY,
    DeskDownstreamReplayError,
    DeskDownstreamReplayService,
    source_run_id,
    update_replay_stage,
)
from application.report.contract_selection import DESK_REPORT_CONTRACT_PIN, H3_REPORT_CONTRACT
from application.evidence.grounding import excerpt_hash
from application.authority_extension import COMPOSED_AUTHORITY_KEY, build_composition
from domain.workflow_status import WorkflowStatus


class _Projects:
    def __init__(self, project): self.project = project
    def get_project(self, project_id): return self.project


class _Workflows:
    def __init__(self, source, template):
        self.source = source
        self.template = template
        self.runs = [source]
        self.results = {source.id: {
            "research_readiness": {
                "analysis_ready": True,
                "complete_design_ready": False,
                "analysis_eligible_information_need_ids": ["in-1"],
            }
        }}

    def get_workflow_run(self, run_id):
        try:
            return next(x for x in self.runs if x.id == run_id)
        except StopIteration as exc:
            raise EntityNotFoundError(run_id) from exc
    def get_template(self, template_id): return self.template
    def get_task_results(self, run_id): return self.results.get(run_id, {})
    def list_workflow_runs_for_project(self, project_id): return list(self.runs)


class _Repository:
    def __init__(self, values): self.values = list(values)
    def list_for_project(self, project_id, *, workflow_run_id):
        return [x for x in self.values if x.project_id == project_id and x.workflow_run_id == workflow_run_id]
    def get_by_id(self, item_id):
        return next((x for x in self.values if x.id == item_id), None)


class _Durable:
    def __init__(self): self.calls = []
    def submit_research(self, project, template, *, initial_task_results=None):
        run = SimpleNamespace(
            id="replay-run", project_id=project.id,
            workflow_template_id=template.id, status=WorkflowStatus.CREATED,
            is_terminal=False,
        )
        self.calls.append((project, template, copy.deepcopy(initial_task_results), run))
        return SimpleNamespace(workflow_run=run)


class _Context:
    def __init__(self, run_id="replay-run", state=None):
        self.workflow_run = SimpleNamespace(id=run_id)
        self.shared_state = dict(state or {})
    def read_shared(self, key): return self.shared_state.get(key)
    def write_shared(self, key, value): self.shared_state[key] = value


def _fixture():
    project = SimpleNamespace(id="project-1", owner_principal_id="owner-1")
    source = SimpleNamespace(
        id="source-run", project_id=project.id, workflow_template_id="source-template",
        status=WorkflowStatus.FAILED, is_terminal=True,
    )
    design = SimpleNamespace(
        id="design-1",
        research_subject=SimpleNamespace(subject_id="subject-1"),
        research_questions=[SimpleNamespace(id="rq-1")],
        information_needs=[SimpleNamespace(id="in-1", research_question_id="rq-1")],
    )
    template = SimpleNamespace(
        research_design_snapshot=design,
        research_brief_snapshot=SimpleNamespace(language="uk", timeframe="2021-2026"),
    )
    evidence = SimpleNamespace(
        id="evidence-1", project_id=project.id, workflow_run_id=source.id,
        research_design_id=design.id, source_id="source-1",
        source_excerpt="Retail turnover increased.",
        source_content_checksum=hashlib.sha256("Retail turnover increased.".encode()).hexdigest(),
        source_locator={"normalized_start": 0, "normalized_end": 26,
                        "excerpt_hash": excerpt_hash("Retail turnover increased.")},
        information_need_refs=("in-1",),
    )
    finding = SimpleNamespace(
        id="finding-1", project_id=project.id, workflow_run_id=source.id,
        research_design_id=design.id, evidence_refs=(evidence.id,),
        research_question_refs=("rq-1",), information_need_refs=("in-1",),
    )
    insight = SimpleNamespace(
        id="insight-1", project_id=project.id, workflow_run_id=source.id,
        research_design_id=design.id, finding_refs=(finding.id,),
        research_question_refs=("rq-1",),
    )
    workflows = _Workflows(source, template)
    durable = _Durable()
    source_record = SimpleNamespace(
        id="source-1", project_id=project.id,
        content_text="Retail turnover increased.",
        content_checksum=evidence.source_content_checksum,
    )
    service = DeskDownstreamReplayService(
        projects=_Projects(project), workflows=workflows, durable_workflows=durable,
        evidence=_Repository([evidence]), findings=_Repository([finding]),
        insights=_Repository([insight]),
        sources=_Repository([source_record]),
        activation_sessions=SimpleNamespace(activation=lambda _project_id: nullcontext()),
    )
    return service, project, source, workflows, durable, evidence, finding, insight


class DeskDownstreamReplayTests(unittest.TestCase):
    def test_latest_composed_authority_is_pinned_into_new_h3_replay(self):
        service, project, source, workflows, durable, *_ = _fixture()
        service.desk_report_contract_version = H3_REPORT_CONTRACT
        older = build_composition(
            composition_id="composition-old", project_id=project.id,
            research_design_id="design-1",
            parent_source_workflow_run_id=source.id,
            member_workflow_run_ids=(source.id, "extension-old"),
            selected_information_need_ids=("in-1",),
            created_at="2026-01-01T00:00:00+00:00",
        )
        latest = build_composition(
            composition_id="composition-latest", project_id=project.id,
            research_design_id="design-1",
            parent_source_workflow_run_id=source.id,
            member_workflow_run_ids=(source.id, "extension-latest"),
            selected_information_need_ids=("in-1",),
            created_at="2026-01-02T00:00:00+00:00",
        )
        workflows.runs.append(SimpleNamespace(
            id="extension-latest", project_id=project.id,
            workflow_template_id="source-template", status=WorkflowStatus.COMPLETED,
            is_terminal=True,
        ))

        class Compositions:
            def get_latest_for_parent(self, project_id, parent_id):
                self.request = (project_id, parent_id)
                return max((older, latest), key=lambda item: item.created_at)

        service.composed_authorities = Compositions()
        service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")

        initial = durable.calls[0][2]
        self.assertEqual(initial[COMPOSED_AUTHORITY_KEY], {
            "composition_id": latest.composition_id,
            "composition_digest": latest.composition_digest,
        })

    def test_changed_composition_identity_creates_distinct_replay_attempt(self):
        service, project, source, workflows, durable, *_ = _fixture()
        first = build_composition(
            composition_id="composition-first", project_id=project.id,
            research_design_id="design-1", parent_source_workflow_run_id=source.id,
            member_workflow_run_ids=(source.id, "extension-first"),
            selected_information_need_ids=("in-1",), created_at="2026-01-01T00:00:00+00:00",
        )
        second = build_composition(
            composition_id="composition-second", project_id=project.id,
            research_design_id="design-1", parent_source_workflow_run_id=source.id,
            member_workflow_run_ids=(source.id, "extension-second"),
            selected_information_need_ids=("in-1",), created_at="2026-01-02T00:00:00+00:00",
        )
        for member_id in ("extension-first", "extension-second"):
            workflows.runs.append(SimpleNamespace(
                id=member_id, project_id=project.id, workflow_template_id="source-template",
                status=WorkflowStatus.COMPLETED, is_terminal=True,
            ))

        class Compositions:
            current = first
            def get_latest_for_parent(self, project_id, parent_id):
                return self.current

        compositions = Compositions()
        service.composed_authorities = compositions
        service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")
        first_identity = durable.calls[0][2][REPLAY_KEY]["replay_identity"]
        compositions.current = second
        service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")
        second_identity = durable.calls[1][2][REPLAY_KEY]["replay_identity"]
        self.assertNotEqual(first_identity, second_identity)
        self.assertEqual(2, len(durable.calls))

    def test_non_qualifying_composed_evidence_is_rejected_before_replay_creation(self):
        service, project, source, workflows, durable, evidence, *_ = _fixture()
        evidence.source_content_checksum = "foreign-checksum"
        composition = build_composition(
            composition_id="composition-invalid", project_id=project.id,
            research_design_id="design-1", parent_source_workflow_run_id=source.id,
            member_workflow_run_ids=(source.id,), selected_information_need_ids=("in-1",),
            created_at="2026-01-01T00:00:00+00:00",
        )
        class Compositions:
            def get_latest_for_parent(self, project_id, parent_id):
                return composition
        service.composed_authorities = Compositions()
        with self.assertRaisesRegex(DeskDownstreamReplayError, "insufficient_coverage"):
            service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")
        self.assertEqual([], durable.calls)

    def test_login_redirect_recognizes_replay_as_post_only_project_action(self):
        match = _POST_ACTION_SAFE_PROJECT_RETURN.fullmatch(
            "/ui/projects/project-1/methods/DESK/source-run/finalization-replay"
        )
        self.assertIsNotNone(match)
        self.assertEqual("project-1", match.group(1))

    def test_eligible_source_creates_distinct_downstream_only_replay(self):
        service, project, source, workflows, durable, evidence, finding, insight = _fixture()
        before = copy.deepcopy((workflows.results[source.id], evidence.__dict__, finding.__dict__, insight.__dict__))

        run = service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")

        self.assertEqual("replay-run", run.id)
        self.assertEqual(1, len(durable.calls))
        _, template, initial, _ = durable.calls[0]
        self.assertEqual(["report", "review", "finalization"],
                         [task.executor_id for task in template.task_definitions])
        self.assertNotIn("collect", [task.executor_id for task in template.task_definitions])
        self.assertNotIn("evidence", [task.executor_id for task in template.task_definitions])
        self.assertNotIn("analysis", [task.executor_id for task in template.task_definitions])
        lineage = initial[REPLAY_KEY]
        self.assertEqual(source.id, lineage["source_workflow_run_id"])
        self.assertEqual("design-1", lineage["research_design_id"])
        self.assertEqual("subject-1", lineage["research_subject_id"])
        self.assertEqual("downstream_report_review_finalization", lineage["budget_scope"])
        self.assertNotEqual(source.id, lineage["replay_attempt_id"])
        self.assertEqual(before, (workflows.results[source.id], evidence.__dict__, finding.__dict__, insight.__dict__))

    def test_h3_replay_uses_static_expanded_graph_and_persists_report_run_pin(self):
        service, project, source, _, durable, *_ = _fixture()
        service.desk_report_contract_version = H3_REPORT_CONTRACT

        service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")

        _, template, initial, _ = durable.calls[0]
        self.assertEqual(
            ["report", "review", "revision", "review", "finalization"],
            [task.executor_id for task in template.task_definitions],
        )
        by_id = {task.id: task for task in template.task_definitions}
        self.assertEqual(
            ["task-review-report-1", "task-revise-report", "task-review-report-2"],
            by_id["finalization"].depends_on,
        )
        self.assertEqual(H3_REPORT_CONTRACT, initial[DESK_REPORT_CONTRACT_PIN])

    def test_foreign_owner_is_rejected_before_replay_creation(self):
        service, project, source, _, durable, *_ = _fixture()
        with self.assertRaises(AccessDeniedError):
            service.start(project_id=project.id, source_run_id=source.id, owner_id="other")
        self.assertEqual([], durable.calls)

    def test_missing_or_foreign_upstream_lineage_fails_closed(self):
        service, project, source, workflows, durable, evidence, *_ = _fixture()
        workflows.results[source.id]["research_readiness"]["analysis_ready"] = False
        with self.assertRaisesRegex(DeskDownstreamReplayError, "readiness"):
            service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")
        workflows.results[source.id]["research_readiness"]["analysis_ready"] = True
        evidence.research_design_id = "foreign-design"
        with self.assertRaisesRegex(DeskDownstreamReplayError, "lineage"):
            service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")
        self.assertEqual([], durable.calls)

    def test_source_finding_rq_and_information_need_lineage_stays_fail_closed(self):
        service, project, source, _, durable, _, finding, _ = _fixture()
        finding.research_question_refs = ("foreign-rq",)
        with self.assertRaisesRegex(DeskDownstreamReplayError, "finding_lineage"):
            service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")

        finding.research_question_refs = ("rq-1",)
        finding.information_need_refs = ("foreign-in",)
        with self.assertRaisesRegex(DeskDownstreamReplayError, "finding_lineage"):
            service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")
        self.assertEqual([], durable.calls)

    def test_active_and_completed_attempts_are_reused(self):
        service, project, source, workflows, durable, *_ = _fixture()
        for status, terminal in ((WorkflowStatus.RUNNING, False), (WorkflowStatus.COMPLETED, True)):
            replay = SimpleNamespace(
                id=f"existing-{status.value}", project_id=project.id,
                status=status, is_terminal=terminal,
            )
            workflows.runs = [source, replay]
            workflows.results[replay.id] = {REPLAY_KEY: {"source_workflow_run_id": source.id}}
            result = service.start(project_id=project.id, source_run_id=source.id, owner_id="owner-1")
            self.assertIs(replay, result)
        self.assertEqual([], durable.calls)

    def test_failed_attempt_allows_new_bounded_attempt(self):
        service, project, source, workflows, durable, *_ = _fixture()
        failed = SimpleNamespace(
            id="failed-replay", project_id=project.id,
            status=WorkflowStatus.FAILED, is_terminal=True,
            workflow_template_id="replay-template",
        )
        workflows.runs.append(failed)
        workflows.results[failed.id] = {REPLAY_KEY: {"source_workflow_run_id": source.id}}
        self.assertEqual("replay-run", service.start(
            project_id=project.id, source_run_id=source.id, owner_id="owner-1").id)
        self.assertEqual(1, len(durable.calls))

    def test_eligibility_is_independent_of_later_failed_replay(self):
        service, project, source, workflows, durable, *_ = _fixture()
        failed = SimpleNamespace(
            id="failed-replay", project_id=project.id,
            workflow_template_id="replay-template",
            status=WorkflowStatus.FAILED, is_terminal=True,
        )
        workflows.runs.append(failed)
        workflows.results[failed.id] = {REPLAY_KEY: {"source_workflow_run_id": source.id}}

        self.assertTrue(service.can_start(
            project_id=project.id, source_run_id=source.id, owner_id="owner-1"))
        self.assertFalse(service.can_start(
            project_id=project.id, source_run_id=failed.id, owner_id="owner-1"))
        self.assertFalse(service.can_start(
            project_id=project.id, source_run_id=source.id, owner_id="other"))
        self.assertEqual([], durable.calls)

    def test_reusable_source_resolves_through_failed_replay_lineage(self):
        service, project, source, workflows, durable, *_ = _fixture()
        failed = SimpleNamespace(
            id="failed-replay", project_id=project.id,
            workflow_template_id="replay-template",
            status=WorkflowStatus.FAILED, is_terminal=True,
        )
        workflows.runs.append(failed)
        workflows.results[failed.id] = {
            REPLAY_KEY: {"source_workflow_run_id": source.id},
        }

        self.assertEqual(source.id, service.reusable_source_run_id(
            project_id=project.id, run_id=failed.id, owner_id="owner-1",
        ))
        self.assertIsNone(service.reusable_source_run_id(
            project_id=project.id, run_id=failed.id, owner_id="other",
        ))
        self.assertEqual([], durable.calls)

    def test_reusable_source_rejects_nested_or_missing_lineage(self):
        service, project, source, workflows, durable, *_ = _fixture()
        failed = SimpleNamespace(
            id="failed-replay", project_id=project.id,
            status=WorkflowStatus.FAILED, is_terminal=True,
            workflow_template_id="replay-template",
        )
        workflows.runs.append(failed)
        workflows.results[failed.id] = {REPLAY_KEY: {"source_workflow_run_id": "missing"}}
        self.assertIsNone(service.reusable_source_run_id(
            project_id=project.id, run_id=failed.id, owner_id="owner-1",
        ))
        workflows.results[failed.id] = {
            REPLAY_KEY: {"source_workflow_run_id": source.id},
        }
        workflows.results[source.id][REPLAY_KEY] = {
            "source_workflow_run_id": "older-source",
        }
        self.assertIsNone(service.reusable_source_run_id(
            project_id=project.id, run_id=failed.id, owner_id="owner-1",
        ))
        self.assertEqual([], durable.calls)

    def test_non_terminal_source_is_not_eligible(self):
        service, project, source, _, durable, *_ = _fixture()
        source.status = WorkflowStatus.RUNNING
        source.is_terminal = False
        self.assertFalse(service.can_start(
            project_id=project.id, source_run_id=source.id, owner_id="owner-1"))
        self.assertEqual([], durable.calls)

    def test_replay_source_and_bounded_stage_state(self):
        lineage = {
            "source_workflow_run_id": "source-run",
            "status": "pending",
            "downstream_stages": {"report": "pending", "review": "pending", "deliverables": "pending"},
        }
        context = _Context(state={REPLAY_KEY: lineage})
        self.assertEqual("source-run", source_run_id(context))
        update_replay_stage(context, "report", "failed", failure_code="ReportError")
        persisted = context.read_shared(REPLAY_KEY)
        self.assertEqual("failed", persisted["status"])
        self.assertEqual("failed", persisted["downstream_stages"]["report"])
        self.assertEqual("ReportError", persisted["failure_code"])


if __name__ == "__main__":
    unittest.main()
