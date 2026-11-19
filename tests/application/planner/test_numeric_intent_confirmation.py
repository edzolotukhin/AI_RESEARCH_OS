from dataclasses import replace
import unittest
from unittest.mock import Mock

from application.factories.research_design_factory import ResearchDesignFactory
from application.parsers.research_design_parser import ResearchDesignParser
from application.services.project_planning_service import (
    NumericIntentConfirmationEntry,
    ProjectPlanningError,
    ProjectPlanningService,
)
from domain.planning.evidence_expectation import EvidenceExpectation
from domain.planning.evidence_nature import EvidenceNature
from domain.planning.research_design import (
    EvidenceCoverageContract,
    InformationNeed,
    ResearchDesign,
    ResearchQuestion,
)
from domain.project import Project
from infrastructure.persistence.postgresql.mappers.project_mapper import (
    project_from_model,
    project_to_model,
)


def design() -> ResearchDesign:
    return ResearchDesign(
        id="design-source",
        research_questions=(ResearchQuestion("rq", "What should be measured?"),),
        information_needs=(
            InformationNeed(
                "numeric", "rq", "Measured outcome",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.MIXED,
                    required_aspects=("measurement",),
                    requires_quantitative_evidence=False,
                ),
                geography="Ukraine",
            ),
            InformationNeed(
                "context", "rq", "Methodological context",
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUALITATIVE,
                    required_aspects=("methodology",),
                ),
            ),
        ),
        source_strategy=("Authoritative sources",),
        analysis_plan=("Analyze confirmed evidence",),
        deliverable_plan=("Research report",),
    )


def coverage() -> EvidenceCoverageContract:
    return EvidenceCoverageContract(
        required_metric="Population",
        required_unit="persons",
        required_periods=("2019", "2020", "2021"),
        geography="Ukraine",
    )


class NumericIntentConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.projects = Mock()
        self.service = ProjectPlanningService(
            project_service=self.projects,
            workflow_service=Mock(),
            planner_agent=None,
            workflow_mapper=None,
            agency=None,
            quantitative_ui_service=None,
        )
        self.project = Project(
            "project", "Numeric confirmation",
            owner_principal_id="owner",
            selected_methods=("QUANTITATIVE",),
        )
        self.project.current_research_design = design()
        self.project.research_design_status = "DRAFT"
        self.project.research_design_input_fingerprint = self.service.input_fingerprint(
            None, ("QUANTITATIVE",),
        )

    def entries(self):
        return {
            "numeric": NumericIntentConfirmationEntry(True, coverage()),
            "context": NumericIntentConfirmationEntry(False),
        }

    def test_planner_boolean_is_ignored_and_legacy_payload_remains_exact(self):
        payload = design().to_dict()
        payload["information_needs"][0]["numeric_observation_required"] = False
        payload["numeric_intent_confirmation"] = {
            "version": "numeric-intent-confirmation-v1",
            "source_design_id": "old",
            "confirmed_design_id": payload["id"],
            "confirmed_by": "planner",
            "confirmed_at": "2026-01-01T00:00:00+00:00",
            "integrity_digest": "f" * 64,
        }
        parsed = ResearchDesignFactory().create(ResearchDesignParser().parse(payload))
        self.assertIsNone(parsed.information_needs[0].numeric_observation_required)
        self.assertIsNone(parsed.numeric_intent_confirmation)

        legacy = design().to_dict()
        loaded = ResearchDesign.from_dict(legacy)
        self.assertEqual(loaded.to_dict(), legacy)
        self.assertIsNone(loaded.numeric_intent_confirmation)

    def test_unresolved_quantitative_design_fails_closed(self):
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_unresolved"):
            self.service.approve_design(
                self.project, actor_id="owner", expected_design_id="design-source",
            )

    def test_confirmation_creates_immutable_revision_and_durable_provenance(self):
        source = self.project.current_research_design
        confirmed = self.service.confirm_numeric_intent(
            self.project,
            actor_id="owner",
            expected_design_id=source.id,
            entries=self.entries(),
        )
        self.assertIsNot(confirmed, source)
        self.assertEqual(source.id, "design-source")
        self.assertIsNone(source.numeric_intent_confirmation)
        self.assertNotEqual(confirmed.id, source.id)
        self.assertEqual(confirmed.previous_design_id, source.id)
        self.assertEqual(confirmed.numeric_intent_confirmation.confirmed_design_id, confirmed.id)
        self.assertEqual(confirmed.numeric_intent_confirmation.confirmed_by, "owner")
        self.assertTrue(confirmed.information_needs[0].numeric_observation_required)
        self.assertFalse(confirmed.information_needs[1].numeric_observation_required)

        reloaded = ResearchDesign.from_dict(confirmed.to_dict())
        self.assertEqual(reloaded, confirmed)
        self.assertEqual(
            reloaded.numeric_intent_confirmation.integrity_digest,
            confirmed.numeric_intent_confirmation.integrity_digest,
        )
        model = project_to_model(self.project, version=1)
        persisted = project_from_model(model)
        self.assertEqual(persisted.current_research_design, confirmed)
        self.assertEqual(
            persisted.current_research_design.numeric_intent_confirmation.confirmed_by,
            "owner",
        )
        approved = self.service.approve_design(
            self.project, actor_id="owner", expected_design_id=confirmed.id,
        )
        self.assertEqual(approved.research_design_status, "APPROVED")

    def test_reconfirming_current_design_is_rejected_without_new_revision(self):
        first = self.service.confirm_numeric_intent(
            self.project,
            actor_id="owner",
            expected_design_id="design-source",
            entries=self.entries(),
        )
        with self.assertRaisesRegex(
            ProjectPlanningError, "numeric_intent_already_confirmed",
        ):
            self.service.confirm_numeric_intent(
                self.project,
                actor_id="owner",
                expected_design_id=first.id,
                entries=self.entries(),
            )
        self.assertIs(self.project.current_research_design, first)
        self.assertEqual(self.project.current_research_design.id, first.id)

    def test_approval_rejects_confirmation_copied_to_another_revision(self):
        confirmed = self.service.confirm_numeric_intent(
            self.project, actor_id="owner", expected_design_id="design-source",
            entries=self.entries(),
        )
        self.project.current_research_design = replace(confirmed, id="tampered-revision")
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_unresolved"):
            self.service.approve_design(
                self.project, actor_id="owner", expected_design_id="tampered-revision",
            )

    def test_owner_authorization_fails_closed_for_empty_and_mismatched_ids(self):
        for owner_id, actor_id in (
            (None, "owner"),
            ("", "owner"),
            (" ", "owner"),
            ("owner", ""),
            ("owner", " "),
            ("owner", "foreign"),
        ):
            with self.subTest(owner_id=owner_id, actor_id=actor_id):
                self.project.owner_principal_id = owner_id
                with self.assertRaisesRegex(ProjectPlanningError, "Лише власник"):
                    self.service.confirm_numeric_intent(
                        self.project,
                        actor_id=actor_id,
                        expected_design_id="design-source",
                        entries=self.entries(),
                    )

    def test_full_design_digest_rejects_semantic_mutation(self):
        confirmed = self.service.confirm_numeric_intent(
            self.project, actor_id="owner", expected_design_id="design-source",
            entries=self.entries(),
        )
        numeric_need = confirmed.information_needs[0]
        mutations = (
            replace(confirmed, source_strategy=("Changed authority",)),
            replace(confirmed, analysis_plan=("Changed analysis",)),
            replace(confirmed, research_questions=(
                replace(confirmed.research_questions[0], question="Changed question"),
            )),
            replace(confirmed, information_needs=(
                replace(
                    numeric_need,
                    evidence_coverage=replace(
                        numeric_need.evidence_coverage,
                        required_periods=("2020",),
                    ),
                ),
                confirmed.information_needs[1],
            )),
        )
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                self.project.current_research_design = mutated
                with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_unresolved"):
                    self.service.approve_design(
                        self.project, actor_id="owner", expected_design_id=mutated.id,
                    )

    def test_approval_checks_current_owner_revision_ids_and_timestamp(self):
        confirmed = self.service.confirm_numeric_intent(
            self.project, actor_id="owner", expected_design_id="design-source",
            entries=self.entries(),
        )
        confirmation = confirmed.numeric_intent_confirmation
        invalid_confirmations = (
            replace(confirmation, confirmed_by="former-owner"),
            replace(confirmation, source_design_id="wrong-source"),
            replace(confirmation, confirmed_at="2026-01-01T00:00:00"),
            replace(confirmation, confirmed_at="not-a-timestamp"),
            replace(confirmation, confirmed_at="2027-01-01T00:00:00+00:00"),
        )
        for invalid in invalid_confirmations:
            with self.subTest(invalid=invalid):
                self.project.current_research_design = replace(
                    confirmed, numeric_intent_confirmation=invalid,
                )
                with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_unresolved"):
                    self.service.approve_design(
                        self.project, actor_id="owner", expected_design_id=confirmed.id,
                    )
        self.project.current_research_design = confirmed
        self.project.owner_principal_id = "new-owner"
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_unresolved"):
            self.service.approve_design(
                self.project, actor_id="new-owner", expected_design_id=confirmed.id,
            )

    def test_approved_status_does_not_bypass_new_revision_integrity(self):
        # Historical non-quantitative approval remains idempotent.
        self.project.selected_methods = ("DESK",)
        self.project.research_design_input_fingerprint = self.service.input_fingerprint(
            None, ("DESK",),
        )
        self.project.research_design_status = "APPROVED"
        self.assertIs(
            self.service.approve_design(
                self.project, actor_id="owner", expected_design_id="design-source",
            ),
            self.project,
        )
        # New/unconfirmed quantitative state cannot use APPROVED as a bypass.
        self.project.selected_methods = ("QUANTITATIVE",)
        self.project.research_design_input_fingerprint = self.service.input_fingerprint(
            None, ("QUANTITATIVE",),
        )
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_unresolved"):
            self.service.approve_design(
                self.project, actor_id="owner", expected_design_id="design-source",
            )
        # Historical approved snapshots remain loadable through read paths.
        historical = project_from_model(project_to_model(self.project, version=1))
        self.assertEqual(historical.research_design_status, "APPROVED")
        self.assertEqual(historical.current_research_design.id, "design-source")

        # Confirmed revisions are idempotent only while integrity remains valid.
        self.project.research_design_status = "DRAFT"
        confirmed = self.service.confirm_numeric_intent(
            self.project, actor_id="owner", expected_design_id="design-source",
            entries=self.entries(),
        )
        self.service.approve_design(
            self.project, actor_id="owner", expected_design_id=confirmed.id,
        )
        self.project.current_research_design = replace(
            confirmed, deliverable_plan=("Changed after approval",),
        )
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_unresolved"):
            self.service.approve_design(
                self.project, actor_id="owner", expected_design_id=confirmed.id,
            )

    def test_partial_foreign_stale_and_non_owner_confirmation_fail(self):
        cases = (
            ("design-source", {"numeric": self.entries()["numeric"]}, "map_invalid"),
            ("design-source", {**self.entries(), "foreign": self.entries()["context"]}, "map_invalid"),
            ("stale", self.entries(), "Дизайн змінився"),
        )
        for expected_id, entries, message in cases:
            with self.subTest(expected_id=expected_id, entries=tuple(entries)):
                with self.assertRaisesRegex(ProjectPlanningError, message):
                    self.service.confirm_numeric_intent(
                        self.project, actor_id="owner",
                        expected_design_id=expected_id, entries=entries,
                    )
        with self.assertRaisesRegex(ProjectPlanningError, "Лише власник"):
            self.service.confirm_numeric_intent(
                self.project, actor_id="foreign",
                expected_design_id="design-source", entries=self.entries(),
            )

    def test_numeric_missing_coverage_and_classification_conflict_fail(self):
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_requirements_unavailable"):
            self.service.confirm_numeric_intent(
                self.project, actor_id="owner", expected_design_id="design-source",
                entries={
                    "numeric": NumericIntentConfirmationEntry(True),
                    "context": NumericIntentConfirmationEntry(False),
                },
            )
        conflicting = replace(
            design(),
            information_needs=(replace(
                design().information_needs[0],
                evidence_expectation=EvidenceExpectation(
                    EvidenceNature.QUANTITATIVE,
                    required_aspects=("measurement",),
                    requires_quantitative_evidence=True,
                ),
            ), design().information_needs[1]),
        )
        self.project.current_research_design = conflicting
        with self.assertRaisesRegex(ProjectPlanningError, "numeric_intent_conflict"):
            self.service.confirm_numeric_intent(
                self.project, actor_id="owner", expected_design_id=conflicting.id,
                entries={
                    "numeric": NumericIntentConfirmationEntry(False),
                    "context": NumericIntentConfirmationEntry(False),
                },
            )

    def test_confirmation_is_quantitative_only(self):
        self.project.selected_methods = ("DESK",)
        with self.assertRaisesRegex(ProjectPlanningError, "Кількісний метод"):
            self.service.confirm_numeric_intent(
                self.project, actor_id="owner", expected_design_id="design-source",
                entries=self.entries(),
            )

    def test_quantitative_approval_requires_at_least_one_numeric_acquired_need(self):
        all_non_numeric = {
            "numeric": NumericIntentConfirmationEntry(False),
            "context": NumericIntentConfirmationEntry(False),
        }
        for methods in (("QUANTITATIVE",), ("DESK", "QUANTITATIVE")):
            with self.subTest(methods=methods):
                project = Project(
                    "project-" + "-".join(methods),
                    "Quantitative minimum",
                    owner_principal_id="owner",
                    selected_methods=methods,
                )
                model = design()
                if "DESK" in methods:
                    from tests.application.evidence.test_structured_production import (
                        design as subject_design,
                    )
                    model = replace(
                        model, research_subject=subject_design().research_subject,
                    )
                project.current_research_design = model
                project.research_design_status = "DRAFT"
                project.research_design_input_fingerprint = self.service.input_fingerprint(
                    None, methods,
                )
                confirmed = self.service.confirm_numeric_intent(
                    project,
                    actor_id="owner",
                    expected_design_id=model.id,
                    entries=all_non_numeric,
                )
                with self.assertRaisesRegex(
                    ProjectPlanningError, "quantitative_observation_required",
                ):
                    self.service.approve_design(
                        project,
                        actor_id="owner",
                        expected_design_id=confirmed.id,
                    )

    def test_desk_plus_quantitative_uses_confirmation_and_subject_gates(self):
        from tests.application.evidence.test_structured_production import (
            design as subject_design,
        )

        self.project.selected_methods = ("DESK", "QUANTITATIVE")
        self.project.current_research_design = replace(
            design(), research_subject=subject_design().research_subject,
        )
        self.project.research_design_input_fingerprint = self.service.input_fingerprint(
            None, ("DESK", "QUANTITATIVE"),
        )
        confirmed = self.service.confirm_numeric_intent(
            self.project, actor_id="owner", expected_design_id="design-source",
            entries=self.entries(),
        )
        approved = self.service.approve_design(
            self.project, actor_id="owner", expected_design_id=confirmed.id,
        )
        self.assertEqual(approved.research_design_status, "APPROVED")
        self.assertEqual(
            approved.current_research_design.research_subject.resolution_status.value,
            "resolved",
        )


if __name__ == "__main__":
    unittest.main()
