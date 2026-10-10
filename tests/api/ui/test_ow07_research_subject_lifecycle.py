from __future__ import annotations

from dataclasses import replace
import json
from unittest.mock import patch

from application.planner.deterministic_design_response import build_deterministic_design_response
from domain.ai.llm_response import LLMResponse
from domain.planning.research_design import ResearchDesign
from domain.planning.research_subject import SubjectResolutionStatus
from domain.research_brief import ResearchBrief
from domain.workflow_status import WorkflowStatus
from tests.api.helpers import ApiTestCase


class Ow07ResearchSubjectLifecycleTests(ApiTestCase):
    def test_ukrainian_market_subject_persists_and_renders_when_planner_wording_differs(self):
        project = self.container.project_service.create_project(
            "Обручальні кільця — Україна",
            owner_principal_id=self.owner_id,
            selected_methods=("DESK", "QUANTITATIVE"),
        )
        brief = ResearchBrief(
            title="Обручальні кільця — Україна",
            business_question="Як запустити новий бренд на українському ринку?",
            objectives=("Оцінити гравців, асортимент, ціни та вподобання",),
            geography=("Україна",),
            market="Ринок обручальних кілець в Україні",
            language="uk",
            context="Аналіз ключових гравців, матеріалів, дизайну й каналів продажу.",
        )
        self.container.project_planning_service.save_brief(project, brief)

        def planner_response(prompt, *, options=None):
            payload = json.loads(build_deterministic_design_response(prompt))
            payload["research_subject"]["canonical_label"] = (
                "Український ринок обручальних кілець"
            )
            payload["research_subject"]["lexical_representations"] = [{
                "language": "uk", "label": "обручальні кільця в Україні",
            }]
            return LLMResponse(content=json.dumps(payload, ensure_ascii=False))

        self.container._test_llm_client.generate.side_effect = planner_response
        self.container.project_planning_service.generate_design(
            self.container.project_service.get_project(project.id),
        )

        reloaded = self.container.project_service.get_project(project.id)
        subject = reloaded.current_research_design.research_subject
        self.assertEqual(subject.canonical_label, brief.market)
        self.assertEqual(subject.resolution_status, SubjectResolutionStatus.RESOLVED)
        self.assertEqual(
            ResearchDesign.from_dict(reloaded.current_research_design.to_dict())
            .research_subject.to_dict(),
            subject.to_dict(),
        )
        page = self.client.get(f"/ui/projects/{project.id}/design")
        self.assertEqual(page.status_code, 200)
        self.assertIn(brief.market, page.text)
        self.assertNotIn("Предмет дослідження не вдалося визначити", page.text)

    def _draft_project(self):
        project = self.container.project_service.create_project(
            "OW-07 lifecycle",
            owner_principal_id=self.owner_id,
            selected_methods=("DESK",),
        )
        self.container.project_planning_service.save_brief(
            project,
            ResearchBrief(
                title="Ринок преміального корму для собак",
                business_question="Які чинники визначають вибір покупця?",
                objectives=("Оцінити позиціонування",),
                geography=("Україна",),
                market="Преміальний корм для собак",
                timeframe="2026",
                language="uk",
            ),
        )
        self.container.project_planning_service.generate_design(
            self.container.project_service.get_project(project.id),
        )
        return self.container.project_service.get_project(project.id)

    @property
    def owner_id(self):
        from api.ui.principal import resolve_ui_principal

        return resolve_ui_principal(self.container).principal_id

    def _approve(self, project):
        return self.client.post(
            f"/ui/projects/{project.id}/design/approve",
            data={"design_id": project.current_research_design.id},
            follow_redirects=False,
        )

    def test_resolved_subject_renders_approves_activates_and_retries_without_regeneration(self):
        project = self._draft_project()
        proposed = project.current_research_design.research_subject
        page = self.client.get(f"/ui/projects/{project.id}/design")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Предмет дослідження", page.text)
        self.assertIn(proposed.canonical_label, page.text)

        self.assertEqual(self._approve(project).status_code, 303)
        approved_project = self.container.project_service.get_project(project.id)
        approved = approved_project.current_research_design.research_subject
        self.assertEqual(approved.subject_id, proposed.subject_id)
        self.assertTrue(approved.executable)

        planner = self.container.project_planning_service
        with patch.object(planner.planner, "run", side_effect=AssertionError("Planner rerun")):
            response = self.client.post(
                f"/ui/projects/{project.id}/methods/DESK/activate",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        run = planner._desk_run(project.id)
        template = self.container.workflow_service.get_template(run.workflow_template_id)
        frozen = template.research_design_snapshot.research_subject
        self.assertEqual((frozen.subject_id, frozen.semantic_fingerprint),
                         (approved.subject_id, approved.semantic_fingerprint))
        self.assertEqual(frozen.lexical_representations, approved.lexical_representations)

        run.ready(); run.start(); run.fail()
        self.container.workflow_service.save_workflow_run(
            run,
            expected_version=self.container.workflow_service.get_workflow_run_version(run.id),
        )
        with patch.object(planner.planner, "run", side_effect=AssertionError("Planner rerun")):
            replacement = planner.retry_failed_desk(
                self.container.project_service.get_project(project.id),
            )
        self.assertNotEqual(replacement.id, run.id)
        self.assertEqual(
            self.container.workflow_service.get_workflow_run(run.id).status,
            WorkflowStatus.FAILED,
        )
        replacement_template = self.container.workflow_service.get_template(
            replacement.workflow_template_id,
        )
        retried = replacement_template.research_design_snapshot.research_subject
        self.assertEqual((retried.subject_id, retried.semantic_fingerprint),
                         (approved.subject_id, approved.semantic_fingerprint))
        self.assertEqual(retried.lexical_representations, approved.lexical_representations)

    def test_safe_partially_resolved_subject_can_be_approved(self):
        project = self._draft_project()
        design = project.current_research_design
        project.current_research_design = replace(
            design,
            research_subject=replace(
                design.research_subject,
                resolution_status=SubjectResolutionStatus.PARTIALLY_RESOLVED,
                semantic_fingerprint="",
            ),
        )
        self.container.project_service.save_project(project)
        self.assertEqual(self._approve(project).status_code, 303)

    def test_unresolved_subject_is_visible_but_approval_is_blocked(self):
        project = self._draft_project()
        design = project.current_research_design
        project.current_research_design = replace(
            design,
            research_subject=replace(
                design.research_subject,
                resolution_status=SubjectResolutionStatus.UNRESOLVED,
                semantic_fingerprint="",
            ),
        )
        self.container.project_service.save_project(project)
        page = self.client.get(f"/ui/projects/{project.id}/design")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Предмет дослідження не вдалося визначити", page.text)
        self.assertIn("Сформувати дизайн знову", page.text)
        self.assertEqual(self._approve(project).status_code, 409)

    def test_unresolved_design_can_be_regenerated_without_brief_mutation(self):
        project = self._draft_project()
        original_design = project.current_research_design
        project.current_research_design = replace(
            original_design,
            research_subject=replace(
                original_design.research_subject,
                canonical_label="",
                core_concepts=(),
                lexical_representations=(),
                resolution_status=SubjectResolutionStatus.UNRESOLVED,
                semantic_fingerprint="",
            ),
        )
        self.container.project_service.save_project(project)
        self.container._test_llm_client.reset_mock()

        response = self.client.post(
            f"/ui/projects/{project.id}/design/generate",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        reloaded = self.container.project_service.get_project(project.id)
        self.assertNotEqual(reloaded.current_research_design.id, original_design.id)
        self.assertEqual(
            reloaded.current_research_design.research_subject.resolution_status,
            SubjectResolutionStatus.RESOLVED,
        )
        self.container._test_llm_client.generate.assert_called()

    def test_legacy_subjectless_design_remains_viewable_but_cannot_activate_desk(self):
        project = self._draft_project()
        project.current_research_design = replace(
            project.current_research_design,
            research_subject=None,
        )
        project.research_design_status = "APPROVED"
        self.container.project_service.save_project(project)
        page = self.client.get(f"/ui/projects/{project.id}/design")
        self.assertEqual(page.status_code, 200)
        self.assertIn("застарілий дизайн без зафіксованого предмета", page.text)
        response = self.client.post(
            f"/ui/projects/{project.id}/methods/DESK/activate",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.container.workflow_service.list_workflow_runs_for_project(project.id),
            [],
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
