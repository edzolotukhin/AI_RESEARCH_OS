from __future__ import annotations

from dataclasses import replace
import unittest

from application.quantitative.research_design_authority import (
    QuantitativeResearchDesignError, QuantitativeResearchDesignService,
    resolve_study_weighting_mode,
)
from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from domain.quantitative.research_design_authority import (
    AnalyticalRequirement, DeliverableRequirement, Hypothesis,
    HypothesisDirection, MethodologyIntent, ObjectiveCoverageAuthority,
    ObjectiveCoverageStatus, QuantitativeResearchQuestion,
    RequirementObligation, ResearchDesignLifecycle, ResearchObjective,
    ResearchPriority, StudyWeightingMode, TargetPopulation,
)
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_research_design_repository import QLQuantitativeResearchDesignRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


class PropertyQZResearchDesignAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.backing = InMemoryQuantitativeStateRepository()
        self.digest = Sha256DigestProvider()
        self.state = QuantitativeStateService(repository=self.backing, digest_provider=self.digest)
        self.repository = QLQuantitativeResearchDesignRepository(self.state)
        self.service = QuantitativeResearchDesignService(repository=self.repository, digest_provider=self.digest)
        self.project = "project-qz"
        self.run = "run-qz"

    def brief(self):
        return self.service.create_brief(
            brief_id="brief", version_id="brief-v1", project_id=self.project, run_id=self.run,
            title="Consumer brand study", business_context="The category is changing.",
            business_problem="The client needs to prioritize investment.",
            decision_context="Select the strongest brand strategy.",
            research_purpose="Measure brand preference and advocacy.",
            intended_audience=("Marketing leadership",), target_deliverables=("Analytical report",),
            constraints=("Synthetic acceptance only",), provenance="Client-authored brief",
            created_at="2026-08-25T10:00:00Z", created_by="owner",
        )

    @staticmethod
    def entities():
        objective = ResearchObjective("objective-brand", "Understand brand preference.", ResearchPriority.HIGH)
        question = QuantitativeResearchQuestion("question-preference", "Which brand is preferred?", (objective.objective_id,), "TOTAL_DISTRIBUTION", ResearchPriority.HIGH)
        hypothesis = Hypothesis("hypothesis-preference", "Preference differs by region.", (objective.objective_id,), (question.question_id,), HypothesisDirection.NON_DIRECTIONAL, "UNWEIGHTED_SIGNIFICANCE")
        requirement = AnalyticalRequirement("requirement-preference", "CROSS_TAB", "Compare preference by region.", (objective.objective_id,), (question.question_id,), RequirementObligation.MANDATORY)
        deliverable = DeliverableRequirement("deliverable-report", "REPORT", "Marketing leadership", "en", RequirementObligation.MANDATORY)
        return (objective,), (question,), (hypothesis,), (requirement,), (deliverable,)

    def design(self, brief=None, **overrides):
        brief = brief or self.brief()
        objectives, questions, hypotheses, requirements, deliverables = self.entities()
        values = dict(
            design_id="design", version_id="design-v1", project_id=self.project, run_id=self.run,
            source_brief_version_id=brief.version_id, source_brief_fingerprint=brief.fingerprint,
            objectives=objectives, research_questions=questions, hypotheses=hypotheses,
            target_population=TargetPopulation(("Germany",), ("Adults 18+",), ("Category rejectors",)),
            methodology_intent=MethodologyIntent("QUANTITATIVE", "ONLINE_SURVEY", "Consumer sample", "UNWEIGHTED", "95% confidence where applicable"),
            analytical_requirements=requirements, deliverable_requirements=deliverables,
            assumptions=("Self-reported survey data",), limitations=("Observational design",),
            created_at="2026-08-25T10:01:00Z", created_by="researcher",
        )
        values.update(overrides)
        return self.service.create_design(**values)

    def approve_brief(self, brief=None, suffix=""):
        brief = brief or self.brief()
        review = self.service.submit_brief_for_review(
            brief.version_id, project_id=self.project, run_id=self.run,
            new_version_id=f"brief-v2-review{suffix}", actor_id="researcher",
            changed_at="2026-08-25T10:00:30Z",
        )
        return self.service.approve_brief(
            review.version_id, project_id=self.project, run_id=self.run,
            new_version_id=f"brief-v3-approved{suffix}", approval_id=f"brief-approval{suffix}",
            expected_fingerprint=review.fingerprint, actor_id="owner",
            decided_at="2026-08-25T10:00:45Z", rationale="Approved source Brief",
        )

    def approve(self, design=None):
        design = design or self.design(self.approve_brief())
        review = self.service.submit_for_review(design.version_id, project_id=self.project, run_id=self.run, new_version_id="design-v2-review", actor_id="researcher", changed_at="2026-08-25T10:02:00Z")
        return self.service.approve(review.version_id, project_id=self.project, run_id=self.run, new_version_id="design-v3-approved", approval_id="approval-v3", expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="2026-08-25T10:03:00Z", rationale="Approved for downstream use")

    def test_brief_creation_fingerprint_and_immutable_revision(self):
        first = self.brief()
        self.assertEqual(first.lifecycle_status, ResearchDesignLifecycle.DRAFT)
        second = self.service.revise_brief(first.version_id, project_id=self.project, run_id=self.run, version_id="brief-v2", created_at="2026-08-25T11:00:00Z", created_by="owner", business_problem="The client must choose a launch strategy.")
        self.assertEqual(self.repository.get_brief("brief-v1", project_id=self.project), first)
        self.assertEqual(second.parent_version_id, first.version_id)
        self.assertNotEqual(second.fingerprint, first.fingerprint)

    def test_same_authoritative_brief_content_has_same_fingerprint(self):
        first = self.brief()
        second = self.service.revise_brief(first.version_id, project_id=self.project, run_id=self.run, version_id="brief-v2", created_at="later", created_by="other")
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_design_structure_fingerprint_and_manifest_are_deterministic(self):
        design = self.design()
        manifest = self.repository.get_manifest("design-v1:traceability", project_id=self.project)
        self.assertEqual(manifest.design_fingerprint, design.fingerprint)
        self.assertEqual(manifest.objective_ids, ("objective-brand",))
        self.assertEqual(manifest.question_to_objectives, (("question-preference", ("objective-brand",)),))
        self.assertEqual(manifest, self.repository.get_manifest(manifest.manifest_id, project_id=self.project))

    def test_stale_brief_wrong_project_and_wrong_methodology_fail_closed(self):
        brief = self.brief()
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "stale"):
            self.design(brief, source_brief_fingerprint="altered")
        with self.assertRaises(QuantitativeResearchDesignError):
            self.service.create_design(design_id="x", version_id="x-v1", project_id="other", run_id=self.run, source_brief_version_id=brief.version_id, source_brief_fingerprint=brief.fingerprint, objectives=(), research_questions=(), hypotheses=(), target_population=TargetPopulation((), (), ()), methodology_intent=MethodologyIntent("QUANTITATIVE", "ONLINE", "sample", "NONE"), analytical_requirements=(), deliverable_requirements=(), assumptions=(), limitations=(), created_at="now", created_by="owner")
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "methodology"):
            self.design(brief, methodology_intent=MethodologyIntent("DESK", "ONLINE", "sample", "NONE"))

    def test_duplicate_and_dangling_entities_fail_closed(self):
        brief = self.brief(); objectives, questions, hypotheses, requirements, deliverables = self.entities()
        duplicate = objectives + (objectives[0],)
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "duplicate"):
            self.design(brief, objectives=duplicate)
        dangling = (replace(questions[0], objective_ids=("missing",)),)
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "dangling"):
            self.design(brief, research_questions=dangling)
        unlinked = (replace(requirements[0], objective_ids=(), research_question_ids=()),)
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "requires"):
            self.design(brief, analytical_requirements=unlinked)

    def test_approval_exact_current_authority_and_bounded_projection(self):
        approved = self.approve()
        self.assertEqual(self.service.resolve_current_approved(project_id=self.project, run_id=self.run), approved)
        projection = self.service.approved_projection(project_id=self.project, run_id=self.run)
        self.assertEqual(projection.version_id, approved.version_id)
        self.assertEqual(projection.objectives, (("objective-brand", "Understand brand preference."),))
        self.assertFalse(hasattr(projection, "respondent_rows"))

    def test_revision_invalidates_previous_current_approval_and_preserves_ids(self):
        approved = self.approve()
        objectives = (replace(approved.objectives[0], statement="Understand preference and consideration."),)
        revision = self.service.revise_design(approved.version_id, project_id=self.project, run_id=self.run, version_id="design-v4", created_at="later", created_by="researcher", objectives=objectives)
        self.assertEqual(revision.objectives[0].objective_id, approved.objectives[0].objective_id)
        self.assertNotEqual(revision.fingerprint, approved.fingerprint)
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "no current approved"):
            self.service.resolve_current_approved(project_id=self.project, run_id=self.run)

    def test_rejected_and_superseded_designs_are_not_current(self):
        design = self.design()
        review = self.service.submit_for_review(design.version_id, project_id=self.project, run_id=self.run, new_version_id="review", actor_id="r", changed_at="now")
        self.service.reject(review.version_id, project_id=self.project, run_id=self.run, new_version_id="rejected", approval_id="reject-approval", expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="later", rationale="Not aligned")
        with self.assertRaises(QuantitativeResearchDesignError): self.service.resolve_current_approved(project_id=self.project, run_id=self.run)

        other = PropertyQZResearchDesignAuthorityTests(methodName="runTest"); other.setUp()
        approved = other.approve()
        other.service.supersede(approved.version_id, project_id=other.project, run_id=other.run, new_version_id="superseded", actor_id="owner", changed_at="later")
        with self.assertRaises(QuantitativeResearchDesignError): other.service.resolve_current_approved(project_id=other.project, run_id=other.run)

    def test_restart_round_trip_and_corruption_detection(self):
        approved = self.approve()
        restarted_state = QuantitativeStateService(repository=self.backing, digest_provider=self.digest)
        restarted = QuantitativeResearchDesignService(repository=QLQuantitativeResearchDesignRepository(restarted_state), digest_provider=self.digest)
        self.assertEqual(restarted.resolve_current_approved(project_id=self.project, run_id=self.run), approved)
        self.backing._records[approved.version_id] = replace(self.backing._records[approved.version_id], authority_fingerprint="corrupt")
        with self.assertRaises((QuantitativePersistenceError, QuantitativeResearchDesignError)):
            restarted.resolve_current_approved(project_id=self.project, run_id=self.run)

    def test_dataset_only_mode_explicitly_has_no_objective_coverage(self):
        value = self.service.resolve_dataset_only(authority_id="dataset-only", project_id=self.project, run_id=self.run)
        self.assertEqual(value.objective_coverage_authority, ObjectiveCoverageAuthority.ABSENT)
        self.assertEqual(value.objective_coverage_status, ObjectiveCoverageStatus.NOT_ASSESSED_NO_RESEARCH_DESIGN)
        self.assertEqual(self.repository.get_dataset_only("dataset-only", project_id=self.project), value)

    def test_direct_pii_is_rejected_and_desk_is_not_a_dependency(self):
        with self.assertRaisesRegex(QuantitativeResearchDesignError, "PII"):
            self.service.create_brief(brief_id="pii", version_id="pii-v1", project_id=self.project, run_id=self.run, title="Call +49 123 456 789", business_context="context", business_problem="problem", decision_context="decision", research_purpose="purpose", intended_audience=("audience",), target_deliverables=("report",), constraints=("none",), provenance="owner", created_at="now", created_by="owner")
        modules = " ".join((QuantitativeResearchDesignService.__module__, type(self.repository).__module__))
        for forbidden in ("domain.research_brief", "domain.planning", "evidence", "sufficiency", "LLMClient"):
            self.assertNotIn(forbidden, modules)

    def test_approved_design_is_the_closed_weighting_authority(self):
        unweighted = self.approve()
        self.assertEqual(
            resolve_study_weighting_mode(unweighted), StudyWeightingMode.UNWEIGHTED
        )
        self.assertEqual(
            resolve_study_weighting_mode(
                replace(
                    unweighted,
                    methodology_intent=replace(
                        unweighted.methodology_intent,
                        weighting_intent="TARGET_MARGINS",
                    ),
                )
            ),
            StudyWeightingMode.WEIGHTED,
        )
        self.assertEqual(
            resolve_study_weighting_mode(
                replace(
                    unweighted,
                    methodology_intent=replace(
                        unweighted.methodology_intent,
                        weighting_intent="NONE",
                    ),
                )
            ),
            StudyWeightingMode.UNRESOLVED,
        )


if __name__ == "__main__": unittest.main()
