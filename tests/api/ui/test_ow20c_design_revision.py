from __future__ import annotations

import json
from unittest.mock import patch

from application.planner.deterministic_design_response import build_deterministic_design_response
from application.sources.expectation_aware_query_intent import render_aspect_query_terms
from domain.ai.llm_response import LLMResponse
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.research_brief import ResearchBrief
from domain.workflow_status import WorkflowStatus
from tests.api.helpers import ApiTestCase


class Ow20cDesignRevisionTests(ApiTestCase):
    def _approved_with_run(self, *, terminal: str = "completed"):
        project = self.container.project_service.create_project(
            f"OW-20C {terminal}",
            owner_principal_id=self.owner_id,
            selected_methods=("DESK",),
        )
        planning = self.container.project_planning_service
        planning.save_brief(project, ResearchBrief(
            title="Composite market",
            business_question="How is the market changing?",
            objectives=("Measure the market",),
            market="Composite market",
            geography=("Ukraine",),
            timeframe="2026",
            language="en",
        ))
        planning.generate_design(self.container.project_service.get_project(project.id))
        project = self.container.project_service.get_project(project.id)
        planning.approve_design(
            project, actor_id=self.owner_id,
            expected_design_id=project.current_research_design.id,
        )
        project = self.container.project_service.get_project(project.id)
        run = planning.activate_desk(project)
        if terminal == "completed":
            run.ready(); run.start(); run.complete()
        elif terminal == "failed":
            run.ready(); run.start(); run.fail()
        elif terminal == "cancelled":
            run.cancel()
        elif terminal == "running":
            run.ready(); run.start()
        elif terminal == "paused":
            run.ready(); run.start(); run.pause()
        elif terminal == "ready":
            run.ready()
        elif terminal == "created":
            pass
        self.container.workflow_service.save_workflow_run(
            run,
            expected_version=self.container.workflow_service.get_workflow_run_version(run.id),
        )
        return self.container.project_service.get_project(project.id), run

    @property
    def owner_id(self):
        from api.ui.principal import resolve_ui_principal
        return resolve_ui_principal(self.container).principal_id

    def test_terminal_revision_preserves_history_and_stale_repeat_is_idempotent(self):
        project, run = self._approved_with_run()
        planning = self.container.project_planning_service
        old_design = project.current_research_design
        old_template = self.container.workflow_service.get_template(run.workflow_template_id)
        before_run = self.container.workflow_service.get_workflow_run(run.id)
        before_results = self.container.workflow_service.get_task_results(run.id)
        self.container._test_llm_client.reset_mock()

        first = self.client.post(
            f"/ui/projects/{project.id}/design/regenerate",
            data={"expected_design_id": old_design.id},
            follow_redirects=False,
        )
        second = self.client.post(
            f"/ui/projects/{project.id}/design/regenerate",
            data={"expected_design_id": old_design.id},
            follow_redirects=False,
        )

        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 409)
        current = self.container.project_service.get_project(project.id)
        self.assertNotEqual(current.current_research_design.id, old_design.id)
        self.assertEqual(current.research_design_status, "DRAFT")
        self.assertIsNone(current.research_design_approved_by)
        self.assertIsNone(current.research_design_approved_at)
        self.assertEqual(self.container._test_llm_client.generate.call_count, 1)
        persisted_run = self.container.workflow_service.get_workflow_run(run.id)
        self.assertEqual(persisted_run.id, before_run.id)
        self.assertEqual(persisted_run.status, before_run.status)
        self.assertEqual(
            [(task.id, task.status) for task in persisted_run.tasks],
            [(task.id, task.status) for task in before_run.tasks],
        )
        self.assertEqual(
            self.container.workflow_service.get_task_results(run.id), before_results,
        )
        frozen = self.container.workflow_service.get_template(run.workflow_template_id)
        self.assertEqual(frozen.research_design_snapshot, old_template.research_design_snapshot)

    def test_revision_ui_and_future_run_bind_to_new_design(self):
        project, old_run = self._approved_with_run()
        old_template = self.container.workflow_service.get_template(old_run.workflow_template_id)
        page = self.client.get(f"/ui/projects/{project.id}/design")
        self.assertIn("Створити нову ревізію дизайну", page.text)
        self.assertIn(f'value="{project.current_research_design.id}"', page.text)

        self.client.post(
            f"/ui/projects/{project.id}/design/regenerate",
            data={"expected_design_id": project.current_research_design.id},
        )
        revised = self.container.project_service.get_project(project.id)
        new_design = revised.current_research_design
        planning = self.container.project_planning_service
        planning.approve_design(
            revised, actor_id=self.owner_id, expected_design_id=new_design.id,
        )
        replacement = planning.replace_terminal_desk(
            self.container.project_service.get_project(project.id)
        )
        new_template = self.container.workflow_service.get_template(
            replacement.workflow_template_id
        )
        self.assertEqual(new_template.research_design_snapshot.id, new_design.id)
        self.assertEqual(
            old_template.research_design_snapshot.id,
            project.current_research_design.id,
        )
        self.assertNotEqual(
            old_template.research_design_snapshot.id,
            new_template.research_design_snapshot.id,
        )

    def test_nonterminal_states_block_revision(self):
        for state in ("created", "ready", "running", "paused"):
            with self.subTest(state=state):
                project, _ = self._approved_with_run(terminal=state)
                self.container._test_llm_client.reset_mock()
                response = self.client.post(
                    f"/ui/projects/{project.id}/design/regenerate",
                    data={"expected_design_id": project.current_research_design.id},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 409)
                self.container._test_llm_client.generate.assert_not_called()

    def test_all_canonical_terminal_states_are_eligible(self):
        for state in ("completed", "failed", "cancelled"):
            with self.subTest(state=state):
                project, run = self._approved_with_run(terminal=state)
                eligible, reason = (
                    self.container.project_planning_service
                    .design_regeneration_eligibility(project)
                )
                self.assertTrue(eligible, reason)
                self.assertTrue(run.is_terminal)

    def test_ordinary_generation_and_replacement_semantics_remain_distinct(self):
        project, run = self._approved_with_run()
        planning = self.container.project_planning_service
        current_design = project.current_research_design
        with patch.object(planning.planner, "run", side_effect=AssertionError("Planner rerun")):
            replacement = planning.replace_terminal_desk(project)
        template = self.container.workflow_service.get_template(
            replacement.workflow_template_id
        )
        self.assertEqual(template.research_design_snapshot, current_design)
        self.assertEqual(
            self.container.workflow_service.get_template(run.workflow_template_id)
            .research_design_snapshot,
            current_design,
        )

    def test_revision_uses_current_composite_subject_semantics(self):
        project, run = self._approved_with_run()
        old_design = project.current_research_design
        old_subject = old_design.research_subject
        self.assertEqual(old_subject.supporting_relations, ())

        def current_semantics(prompt, *, options=None):
            payload = json.loads(build_deterministic_design_response(prompt))
            need = payload["information_needs"][0]
            question_id = need["research_question_id"]
            aspect = need["evidence_expectation"]["required_aspects"][0]
            relation_label = render_aspect_query_terms(aspect)
            payload["research_subject"] = {
                "canonical_label": "Planner wording that differs",
                "canonical_language": "en",
                "lexical_representations": [
                    {"language": "en", "label": "planner wording"},
                ],
                "supporting_relations": [{
                    "relation_id": "scoped-context",
                    "relation_type": "economic_context",
                    "information_need_refs": [need["id"]],
                    "research_question_refs": [question_id],
                    "required_aspect_refs": [aspect],
                    "concepts": ["scoped-context"],
                    "lexical_representations": [{
                        "representation_id": "scoped-context-en",
                        "language": "en",
                        "label": relation_label,
                        "normalized_phrases": [relation_label],
                    }],
                    "explanation": f"{relation_label} is required by the design",
                }],
                "exclusions": [],
            }
            return LLMResponse(content=json.dumps(payload))

        self.container._test_llm_client.generate.side_effect = current_semantics
        new_design = self.container.project_planning_service.regenerate_design_after_terminal_run(
            project, expected_design_id=old_design.id,
        )
        new_subject = new_design.research_subject
        self.assertEqual(new_subject.canonical_label, project.research_brief.market)
        self.assertEqual(len(new_subject.supporting_relations), 1)
        self.assertNotEqual(new_subject.subject_id, old_subject.subject_id)
        self.assertNotEqual(new_subject.semantic_fingerprint, old_subject.semantic_fingerprint)
        frozen = self.container.workflow_service.get_template(run.workflow_template_id)
        self.assertEqual(frozen.research_design_snapshot, old_design)
        self.assertEqual(frozen.research_design_snapshot.research_subject, old_subject)

    def test_revision_preserves_persisted_result_design_bindings(self):
        project, run = self._approved_with_run()
        old_design = project.current_research_design
        created_at = "2026-10-16T00:00:00+00:00"
        evidence = Evidence(
            id="ow20c-evidence", project_id=project.id, source_id="ow20c-source",
            source_content_checksum="checksum", workflow_run_id=run.id,
            research_design_id=old_design.id, statement="Historical evidence",
            source_excerpt="Historical excerpt", created_at=created_at,
            deduplication_key="ow20c-evidence",
        )
        finding = Finding(
            id="ow20c-finding", project_id=project.id, workflow_run_id=run.id,
            research_design_id=old_design.id, statement="Historical finding",
            rationale="Historical rationale", evidence_refs=(evidence.id,),
            created_at=created_at, deduplication_key="ow20c-finding",
        )
        insight = Insight(
            id="ow20c-insight", project_id=project.id, workflow_run_id=run.id,
            research_design_id=old_design.id, statement="Historical insight",
            implication="Historical implication", finding_refs=(finding.id,),
            created_at=created_at, deduplication_key="ow20c-insight",
        )
        report = Report(
            id="ow20c-report", project_id=project.id, workflow_run_id=run.id,
            research_design_id=old_design.id, title="Historical report", language="en",
            sections=(ReportSection(
                id="ow20c-section", title="Results", content="Historical result",
                finding_refs=(finding.id,), evidence_refs=(evidence.id,),
            ),),
            executive_summary="Historical summary", limitations=("Historical limit",),
            created_at=created_at, generation_method="test",
            finding_refs=(finding.id,), insight_refs=(insight.id,),
            evidence_refs=(evidence.id,), citation_registry={},
            deduplication_key="ow20c-report",
        )
        self.container.evidence_service._evidence_repository.create(evidence)
        self.container.finding_service._finding_repository.create(finding)
        self.container.insight_service._insight_repository.create(insight)
        self.container.report_query_service._report_repository.create(report)

        revised = self.container.project_planning_service.regenerate_design_after_terminal_run(
            project, expected_design_id=old_design.id,
        )

        self.assertNotEqual(revised.id, old_design.id)
        repositories = (
            self.container.evidence_service._evidence_repository,
            self.container.finding_service._finding_repository,
            self.container.insight_service._insight_repository,
            self.container.report_query_service._report_repository,
        )
        for repository in repositories:
            rows = repository.list_for_project(project.id, workflow_run_id=run.id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].workflow_run_id, run.id)
            self.assertEqual(rows[0].research_design_id, old_design.id)


if __name__ == "__main__":
    import unittest
    unittest.main()
