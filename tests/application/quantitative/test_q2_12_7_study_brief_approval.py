import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock

from application.config import ApplicationConfig, ApplicationOverrides
from application.composition_root import create_application_container
from application.quantitative.research_design_authority import QuantitativeResearchDesignError
from domain.quantitative.research_design_authority import (
    AnalyticalRequirement, DeliverableRequirement, Hypothesis, HypothesisDirection,
    MethodologyIntent, QuantitativeResearchQuestion, RequirementObligation,
    ResearchDesignLifecycle, ResearchObjective, ResearchPriority, TargetPopulation,
)
from infrastructure.persistence.memory.in_memory_project_repository import InMemoryProjectRepository
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.memory.in_memory_workflow_run_repository import InMemoryWorkflowRunRepository


class Q2127StudyBriefApprovalTests(unittest.TestCase):
    def _container(self, root, projects, runs, quantitative):
        return create_application_container(
            config=ApplicationConfig(projects_root=root, persistence_backend="memory",
                                     deterministic_stage_executors=True, search_provider="deterministic"),
            overrides=ApplicationOverrides(llm_client=Mock(), project_repository=projects,
                workflow_run_repository=runs, quantitative_state_repository=quantitative),
        )

    def _brief(self, service):
        return service.create_brief(brief_id="brief", version_id="brief-v1", project_id="p", run_id="r",
            title="Consumer study", business_context="Category context.", business_problem="Investment choice.",
            decision_context="Choose strategy.", research_purpose="Measure preference.",
            intended_audience=("Leadership",), target_deliverables=("Report",), constraints=("Offline",),
            provenance="TEST_AUTHORED", created_at="t1", created_by="author")

    def _approve_brief(self, service, brief, suffix=""):
        review = service.submit_brief_for_review(brief.version_id, project_id="p", run_id="r",
            new_version_id=f"brief-review{suffix}", actor_id="reviewer", changed_at="t2")
        return service.approve_brief(review.version_id, project_id="p", run_id="r",
            new_version_id=f"brief-approved{suffix}", approval_id=f"brief-approval{suffix}",
            expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="t3", rationale="Approved")

    def _design(self, service, brief, version="design-v1"):
        objective = ResearchObjective("objective", "Understand preference.", ResearchPriority.HIGH)
        question = QuantitativeResearchQuestion("question", "Which brand is preferred?", (objective.objective_id,), "TOTAL_DISTRIBUTION", ResearchPriority.HIGH)
        hypothesis = Hypothesis("hypothesis", "Preference differs.", (objective.objective_id,), (question.question_id,), HypothesisDirection.NON_DIRECTIONAL, "DESCRIPTIVE")
        requirement = AnalyticalRequirement("requirement", "ONE_WAY", "Measure preference.", (objective.objective_id,), (question.question_id,), RequirementObligation.MANDATORY)
        deliverable = DeliverableRequirement("deliverable", "REPORT", "Leadership", "en", RequirementObligation.MANDATORY)
        objectives, questions, hypotheses, requirements, deliverables = (objective,), (question,), (hypothesis,), (requirement,), (deliverable,)
        return service.create_design(design_id="design", version_id=version, project_id="p", run_id="r",
            source_brief_version_id=brief.version_id, source_brief_fingerprint=brief.fingerprint,
            objectives=objectives, research_questions=questions, hypotheses=hypotheses,
            target_population=TargetPopulation(("Germany",), ("Adults",), ("Ineligible",)),
            methodology_intent=MethodologyIntent("QUANTITATIVE", "ONLINE", "Consumers", "NONE"),
            analytical_requirements=requirements, deliverable_requirements=deliverables,
            assumptions=(), limitations=(), created_at="t4", created_by="researcher")

    def test_production_brief_approval_gates_design_and_survives_restart(self):
        projects, runs, quantitative = InMemoryProjectRepository(), InMemoryWorkflowRunRepository(), InMemoryQuantitativeStateRepository()
        with tempfile.TemporaryDirectory() as root:
            first = self._container(root, projects, runs, quantitative)
            service = first.quantitative_authority_finalization_service._designs
            draft = self._brief(service)
            self.assertEqual(ResearchDesignLifecycle.DRAFT, draft.lifecycle_status)
            draft_design = self._design(service, draft, "draft-design")
            review_design = service.submit_for_review(draft_design.version_id, project_id="p", run_id="r",
                new_version_id="draft-design-review", actor_id="reviewer", changed_at="t5")
            with self.assertRaisesRegex(QuantitativeResearchDesignError, "approval"):
                service.approve(review_design.version_id, project_id="p", run_id="r", new_version_id="bad",
                    approval_id="bad", expected_fingerprint=review_design.fingerprint, actor_id="owner",
                    decided_at="t6", rationale="Must fail")

            approved_brief = self._approve_brief(service, draft)
            self.assertEqual(approved_brief, service.resolve_current_approved_brief(project_id="p", run_id="r"))
            design = self._design(service, approved_brief)
            review = service.submit_for_review(design.version_id, project_id="p", run_id="r",
                new_version_id="design-review", actor_id="reviewer", changed_at="t5")
            approved_design = service.approve(review.version_id, project_id="p", run_id="r",
                new_version_id="design-approved", approval_id="design-approval",
                expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="t6", rationale="Approved")
            first.shutdown()

            second = self._container(root, projects, runs, quantitative)
            restarted = second.quantitative_authority_finalization_service._designs
            self.assertEqual(approved_brief, restarted.resolve_current_approved_brief(project_id="p", run_id="r"))
            self.assertEqual(approved_design, restarted.resolve_current_approved(project_id="p", run_id="r"))
            self.assertEqual((approved_brief.version_id, approved_brief.fingerprint),
                (approved_design.source_brief_version_id, approved_design.source_brief_fingerprint))
            second.shutdown()

    def test_revision_rejection_wrong_scope_and_fingerprint_fail_closed(self):
        projects, runs, quantitative = InMemoryProjectRepository(), InMemoryWorkflowRunRepository(), InMemoryQuantitativeStateRepository()
        with tempfile.TemporaryDirectory() as root:
            container = self._container(root, projects, runs, quantitative)
            service = container.quantitative_authority_finalization_service._designs
            approved = self._approve_brief(service, self._brief(service))
            revision = service.revise_brief(approved.version_id, project_id="p", run_id="r",
                version_id="brief-v2", created_at="t4", created_by="author", research_purpose="Measure advocacy.")
            self.assertEqual(ResearchDesignLifecycle.DRAFT, revision.lifecycle_status)
            self.assertIsNone(revision.approval_reference)
            with self.assertRaises(QuantitativeResearchDesignError):
                service.resolve_current_approved_brief(project_id="p", run_id="r")
            review = service.submit_brief_for_review(revision.version_id, project_id="p", run_id="r",
                new_version_id="brief-v2-review", actor_id="reviewer", changed_at="t5")
            with self.assertRaisesRegex(QuantitativeResearchDesignError, "fingerprint"):
                service.approve_brief(review.version_id, project_id="p", run_id="r", new_version_id="bad-fp",
                    approval_id="bad-fp", expected_fingerprint="stale", actor_id="owner", decided_at="t6", rationale="No")
            rejected = service.reject_brief(review.version_id, project_id="p", run_id="r",
                new_version_id="brief-v2-rejected", approval_id="brief-rejection",
                expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="t6", rationale="Rejected")
            with self.assertRaises(QuantitativeResearchDesignError):
                service.resolve_approved_brief(rejected.version_id, project_id="p")
            with self.assertRaises(QuantitativeResearchDesignError):
                service.approve_brief(review.version_id, project_id="wrong", run_id="r", new_version_id="wrong",
                    approval_id="wrong", expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="t6", rationale="No")
            self.assertEqual(approved, service.resolve_approved_brief(approved.version_id, project_id="p"))
            container.shutdown()

    def test_new_approved_brief_becomes_current_old_remains_historical_and_corruption_fails(self):
        projects, runs, quantitative = InMemoryProjectRepository(), InMemoryWorkflowRunRepository(), InMemoryQuantitativeStateRepository()
        with tempfile.TemporaryDirectory() as root:
            container = self._container(root, projects, runs, quantitative)
            service = container.quantitative_authority_finalization_service._designs
            first = self._approve_brief(service, self._brief(service))
            revision = service.revise_brief(first.version_id, project_id="p", run_id="r",
                version_id="brief-v2", created_at="t4", created_by="author", research_purpose="Measure advocacy.")
            review = service.submit_brief_for_review(revision.version_id, project_id="p", run_id="r",
                new_version_id="brief-v2-review", actor_id="reviewer", changed_at="t5")
            second = service.approve_brief(review.version_id, project_id="p", run_id="r",
                new_version_id="brief-v2-approved", approval_id="brief-v2-approval",
                expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="t6", rationale="Approved v2")
            with self.assertRaisesRegex(ValueError, "immutable"):
                service.approve_brief(review.version_id, project_id="p", run_id="r",
                    new_version_id="brief-v2-approved", approval_id="brief-v2-approval",
                    expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="t6", rationale="Approved v2")
            self.assertEqual(second, service.resolve_current_approved_brief(project_id="p", run_id="r"))
            self.assertEqual(first, service.resolve_approved_brief(first.version_id, project_id="p"))
            record = quantitative._records[second.approval_reference]
            quantitative._records[second.approval_reference] = replace(record, payload_checksum="corrupt")
            with self.assertRaises(Exception):
                service.resolve_current_approved_brief(project_id="p", run_id="r")
            container.shutdown()

    def test_current_design_tracks_current_approved_brief_across_restart(self):
        projects, runs, quantitative = InMemoryProjectRepository(), InMemoryWorkflowRunRepository(), InMemoryQuantitativeStateRepository()
        with tempfile.TemporaryDirectory() as root:
            first = self._container(root, projects, runs, quantitative)
            service = first.quantitative_authority_finalization_service._designs
            brief_v1 = self._approve_brief(service, self._brief(service))
            draft_v1 = self._design(service, brief_v1)
            review_v1 = service.submit_for_review(draft_v1.version_id, project_id="p", run_id="r", new_version_id="design-v1-review", actor_id="reviewer", changed_at="t5")
            design_v1 = service.approve(review_v1.version_id, project_id="p", run_id="r", new_version_id="design-v1-approved", approval_id="design-v1-approval", expected_fingerprint=review_v1.fingerprint, actor_id="owner", decided_at="t6", rationale="Approved")
            self.assertEqual(design_v1, service.resolve_current_approved(project_id="p", run_id="r"))
            brief_v2_draft = service.revise_brief(brief_v1.version_id, project_id="p", run_id="r", version_id="brief-v2", created_at="t7", created_by="author", research_purpose="Measure advocacy.")
            with self.assertRaises(QuantitativeResearchDesignError):
                service.resolve_current_approved(project_id="p", run_id="r")
            brief_v2_review = service.submit_brief_for_review(brief_v2_draft.version_id, project_id="p", run_id="r", new_version_id="brief-v2-review", actor_id="reviewer", changed_at="t8")
            brief_v2 = service.approve_brief(brief_v2_review.version_id, project_id="p", run_id="r", new_version_id="brief-v2-approved", approval_id="brief-v2-approval", expected_fingerprint=brief_v2_review.fingerprint, actor_id="owner", decided_at="t9", rationale="Approved v2")
            self.assertEqual(brief_v2, service.resolve_current_approved_brief(project_id="p", run_id="r"))
            self.assertEqual(design_v1, service._repository.get_design(design_v1.version_id, project_id="p"))
            with self.assertRaises(QuantitativeResearchDesignError):
                service.resolve_current_approved(project_id="p", run_id="r")
            first.shutdown()
            second = self._container(root, projects, runs, quantitative)
            restarted = second.quantitative_authority_finalization_service._designs
            self.assertEqual(brief_v2, restarted.resolve_current_approved_brief(project_id="p", run_id="r"))
            self.assertEqual(design_v1, restarted._repository.get_design(design_v1.version_id, project_id="p"))
            with self.assertRaises(QuantitativeResearchDesignError):
                restarted.resolve_current_approved(project_id="p", run_id="r")
            draft_v2 = self._design(restarted, brief_v2, "design-v2")
            with self.assertRaises(QuantitativeResearchDesignError):
                restarted.resolve_current_approved(project_id="p", run_id="r")
            review_v2 = restarted.submit_for_review(draft_v2.version_id, project_id="p", run_id="r", new_version_id="design-v2-review", actor_id="reviewer", changed_at="t10")
            design_v2 = restarted.approve(review_v2.version_id, project_id="p", run_id="r", new_version_id="design-v2-approved", approval_id="design-v2-approval", expected_fingerprint=review_v2.fingerprint, actor_id="owner", decided_at="t11", rationale="Approved v2")
            self.assertEqual(design_v2, restarted.resolve_current_approved(project_id="p", run_id="r"))
            self.assertEqual((brief_v1.version_id, brief_v1.fingerprint), (design_v1.source_brief_version_id, design_v1.source_brief_fingerprint))
            with self.assertRaises(QuantitativeResearchDesignError):
                restarted.resolve_current_approved(project_id="wrong", run_id="r")
            second.shutdown()
    def test_ambiguous_approved_design_candidates_fail_closed(self):
        projects, runs, quantitative = InMemoryProjectRepository(), InMemoryWorkflowRunRepository(), InMemoryQuantitativeStateRepository()
        with tempfile.TemporaryDirectory() as root:
            container = self._container(root, projects, runs, quantitative)
            service = container.quantitative_authority_finalization_service._designs
            brief = self._approve_brief(service, self._brief(service))
            for suffix in ("a", "b"):
                draft = self._design(service, brief, f"design-{suffix}")
                review = service.submit_for_review(draft.version_id, project_id="p", run_id="r", new_version_id=f"design-{suffix}-review", actor_id="reviewer", changed_at="t5")
                service.approve(review.version_id, project_id="p", run_id="r", new_version_id=f"design-{suffix}-approved", approval_id=f"design-{suffix}-approval", expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="t6", rationale="Approved")
            with self.assertRaisesRegex(QuantitativeResearchDesignError, "ambiguous"):
                service.resolve_current_approved(project_id="p", run_id="r")
            container.shutdown()
if __name__ == "__main__":
    unittest.main()
