from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import unittest

from application.quantitative.questionnaire_authority import QuantitativeQuestionnaireError, QuantitativeQuestionnaireService
from application.quantitative.state_persistence import QuantitativeStateService
from domain.quantitative.questionnaire_authority import (
    AnswerOption, DatasetOnlyQuestionnaireAuthority, ExpectedVariableBinding,
    MatrixRow, NumericComparator, QuestionnaireAuthorshipMode,
    QuestionnaireCoverageAuthorityStatus, QuestionnaireCoverageStatus,
    QuestionnaireLifecycle, QuestionnaireQuestion, QuestionnaireQuestionRole,
    QuestionnaireQuestionType, QuestionnaireRoutingRule, QuestionnaireSection,
    RequirementCoverageDeclaration, RoutingAction, RoutingActionType,
    RoutingCondition, RoutingConditionKind, ScaleDefinition, ScaleInterpretation,
)
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_questionnaire_repository import QLQuantitativeQuestionnaireRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qz_research_design_authority import PropertyQZResearchDesignAuthorityTests


class PropertyRAQuestionnaireAuthorityTests(unittest.TestCase):
    def setUp(self):
        qz = PropertyQZResearchDesignAuthorityTests(methodName="runTest")
        qz.setUp()
        self.design = qz.approve()
        self.project, self.run, self.design_service = qz.project, qz.run, qz.service
        self.digest = Sha256DigestProvider()
        self.backing = qz.backing
        self.state = QuantitativeStateService(repository=self.backing, digest_provider=self.digest)
        self.repository = QLQuantitativeQuestionnaireRepository(self.state)
        self.service = QuantitativeQuestionnaireService(repository=self.repository, research_design_service=self.design_service, digest_provider=self.digest)

    @staticmethod
    def options(prefix="brand"):
        return (
            AnswerOption(f"{prefix}-a", "Brand A", "1", 1),
            AnswerOption(f"{prefix}-b", "Brand B", "2", 2),
        )

    def questions(self):
        requirement = self.design.analytical_requirements[0].requirement_id
        screening = QuestionnaireQuestion(
            "q-age", "section-screen", QuestionnaireQuestionRole.SCREENING,
            QuestionnaireQuestionType.NUMERIC, "What is your age?", None, None, (),
            "Target-population age eligibility", True, (), None, (),
            (("minimum", "0"), ("maximum", "120")),
            (ExpectedVariableBinding("ev-age", "age"),), True, 1, "Research team",
        )
        brand = QuestionnaireQuestion(
            "q-brand", "section-main", QuestionnaireQuestionRole.SUBSTANTIVE,
            QuestionnaireQuestionType.SINGLE_CHOICE, "Which brand do you prefer?", None, None,
            (requirement,), None, True, self.options(), None, (), (),
            (ExpectedVariableBinding("ev-brand", "brand_preference"),), True, 1, "Research team",
        )
        demographic = QuestionnaireQuestion(
            "q-sex", "section-classification", QuestionnaireQuestionRole.DEMOGRAPHIC,
            QuestionnaireQuestionType.SINGLE_CHOICE, "Which classification applies?", None, None, (),
            "Weighting control and analytical cut", True,
            (AnswerOption("sex-a", "Group A", "1", 1), AnswerOption("sex-b", "Group B", "2", 2)),
            None, (), (), (ExpectedVariableBinding("ev-sex", "sex"),), False, 1, "Research team",
        )
        quality = QuestionnaireQuestion(
            "q-quality", "section-quality", QuestionnaireQuestionRole.QUALITY_CONTROL,
            QuestionnaireQuestionType.SINGLE_CHOICE, "Select the second option.", None, None, (),
            "Attention check", True, (AnswerOption("qc-a", "First", "1", 1), AnswerOption("qc-b", "Second", "2", 2)),
            None, (), (), (ExpectedVariableBinding("ev-quality", "quality_check"),), False, 1, "Research team",
        )
        technical = QuestionnaireQuestion(
            "q-route", "section-quality", QuestionnaireQuestionRole.TECHNICAL_ROUTING,
            QuestionnaireQuestionType.SINGLE_CHOICE, "Select routing group.", None, None, (),
            "Routing-only classification", False, (AnswerOption("route-a", "A", "1", 1), AnswerOption("route-b", "B", "2", 2)),
            None, (), (), (ExpectedVariableBinding("ev-route", "routing_group"),), True, 2, "Research team",
        )
        return (screening, brand, demographic, quality, technical)

    @staticmethod
    def sections():
        return (
            QuestionnaireSection("section-screen", "Screening", "Eligibility", 1),
            QuestionnaireSection("section-main", "Main", "Substantive measurement", 2),
            QuestionnaireSection("section-classification", "Classification", "Weighting and cuts", 3),
            QuestionnaireSection("section-quality", "Quality", "Quality and routing", 4),
        )

    @staticmethod
    def termination_route():
        return QuestionnaireRoutingRule(
            "route-underage", "q-age", 1,
            RoutingCondition(RoutingConditionKind.NUMERIC_COMPARE, question_id="q-age", comparator=NumericComparator.LT, numeric_value=Decimal("18")),
            RoutingAction(RoutingActionType.SCREENED_OUT, termination_code="UNDER_18"),
        )

    def create(self, *, version_id="questionnaire-v1", sections=None, questions=None, routes=None, declarations=()):
        return self.service.create_draft(
            questionnaire_id="questionnaire", version_id=version_id, project_id=self.project, run_id=self.run,
            research_design_version_id=self.design.version_id, research_design_fingerprint=self.design.fingerprint,
            title="Consumer survey", purpose="Measure brand preference.", language="en",
            sections=self.sections() if sections is None else sections,
            questions=self.questions() if questions is None else questions,
            routing_rules=(self.termination_route(),) if routes is None else routes,
            provenance="Research team", authorship_mode=QuestionnaireAuthorshipMode.INTERNAL_HUMAN,
            estimated_interview_length_minutes=12, assumptions=("Self-completion",),
            limitations=("Observational survey",), coverage_declarations=declarations,
            created_at="2026-08-26T10:00:00Z", created_by="researcher",
        )

    def approve(self, draft=None):
        draft = draft or self.create()
        review = self.service.submit_for_review(draft.version_id, project_id=self.project, run_id=self.run, new_version_id="questionnaire-v2-review", actor_id="researcher", changed_at="later")
        return self.service.approve(
            review.version_id, project_id=self.project, run_id=self.run,
            new_version_id="questionnaire-v3-approved", approval_id="questionnaire-approval",
            expected_fingerprint=review.fingerprint,
            expected_validation_fingerprint=review.validation_manifest_fingerprint,
            expected_coverage_fingerprint=review.coverage_manifest_fingerprint,
            actor_id="owner", decided_at="latest", rationale="Approved measurement authority",
        )

    def test_valid_questionnaire_schema_traceability_coverage_and_termination(self):
        value = self.create()
        schema = self.service.derive_expected_measurement_schema(value.version_id, project_id=self.project)
        coverage = self.service.derive_coverage_manifest(value.version_id, project_id=self.project)
        validation = self.service.validate(value.version_id, project_id=self.project, run_id=self.run)
        self.assertTrue(validation.valid)
        self.assertEqual({item.variable_name for item in schema.variables}, {"age", "brand_preference", "sex", "quality_check", "routing_group"})
        self.assertEqual(coverage.requirements[0].status, QuestionnaireCoverageStatus.MEASURED)
        self.assertEqual(value.routing_rules[0].action.termination_code, "UNDER_18")
        self.assertEqual(value.research_design_fingerprint, self.design.fingerprint)

    def test_unapproved_stale_wrong_project_and_dangling_design_authority_fail(self):
        draft_design = self.design_service.revise_design(self.design.version_id, project_id=self.project, run_id=self.run, version_id="design-draft-new", created_at="later", created_by="researcher")
        with self.assertRaisesRegex(QuantitativeQuestionnaireError, "current approved"):
            self.create(version_id="must-fail")
        with self.assertRaises(QuantitativeQuestionnaireError):
            self.service.create_draft(questionnaire_id="x", version_id="x-v1", project_id="other", run_id=self.run, research_design_version_id=draft_design.version_id, research_design_fingerprint=draft_design.fingerprint, title="x", purpose="x", language="en", sections=(), questions=(), provenance="x", authorship_mode=QuestionnaireAuthorshipMode.INTERNAL_HUMAN, estimated_interview_length_minutes=1, created_at="now", created_by="x")

    def test_fingerprint_determinism_immutable_revision_and_stable_ids(self):
        first = self.create()
        same = self.service.revise(first.version_id, project_id=self.project, run_id=self.run, new_version_id="questionnaire-v2", created_at="later", created_by="same")
        self.assertEqual(first.fingerprint, same.fingerprint)
        changed_questions = tuple(replace(item, wording="Which brand would you choose?") if item.question_id == "q-brand" else item for item in same.questions)
        changed = self.service.revise(same.version_id, project_id=self.project, run_id=self.run, new_version_id="questionnaire-v3", created_at="later2", created_by="editor", questions=changed_questions)
        self.assertNotEqual(changed.fingerprint, same.fingerprint)
        self.assertEqual(changed.questions[1].question_id, same.questions[1].question_id)
        self.assertEqual(self.repository.get_questionnaire(first.version_id, project_id=self.project), first)

    def test_option_code_and_routing_changes_change_fingerprint(self):
        first = self.create()
        questions = tuple(replace(item, answer_options=(replace(item.answer_options[0], dataset_value_code="10"), item.answer_options[1])) if item.question_id == "q-brand" else item for item in first.questions)
        code_changed = self.service.revise(first.version_id, project_id=self.project, run_id=self.run, new_version_id="code-changed", created_at="later", created_by="editor", questions=questions)
        self.assertNotEqual(first.fingerprint, code_changed.fingerprint)
        route_changed = self.service.revise(code_changed.version_id, project_id=self.project, run_id=self.run, new_version_id="route-changed", created_at="later2", created_by="editor", routing_rules=())
        self.assertNotEqual(code_changed.fingerprint, route_changed.fingerprint)

    def test_duplicate_ids_variable_names_and_option_codes_fail_closed(self):
        cases = []
        cases.append(dict(sections=self.sections() + (self.sections()[0],)))
        cases.append(dict(questions=self.questions() + (self.questions()[0],)))
        duplicated_name = tuple(replace(item, expected_variable_bindings=(replace(item.expected_variable_bindings[0], variable_name="age"),)) if item.question_id == "q-brand" else item for item in self.questions())
        cases.append(dict(questions=duplicated_name))
        duplicate_codes = tuple(replace(item, answer_options=(item.answer_options[0], replace(item.answer_options[1], dataset_value_code="1"))) if item.question_id == "q-brand" else item for item in self.questions())
        cases.append(dict(questions=duplicate_codes))
        for index, case in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(QuantitativeQuestionnaireError): self.create(version_id=f"invalid-{index}", **case)

    def test_question_type_scale_and_missing_value_validation(self):
        no_options = tuple(replace(item, answer_options=()) if item.question_id == "q-brand" else item for item in self.questions())
        invalid_scale = ScaleDefinition(Decimal("10"), Decimal("0"), (), ScaleInterpretation.NUMERIC)
        scaled = tuple(replace(item, question_type=QuestionnaireQuestionType.NPS, answer_options=(), scale=invalid_scale) if item.question_id == "q-brand" else item for item in self.questions())
        collision_scale = ScaleDefinition(Decimal("0"), Decimal("10"), ((Decimal("9"), "Nine"),), ScaleInterpretation.NUMERIC, missing_value_codes=((Decimal("9"), "Refused"),))
        collision = tuple(replace(item, question_type=QuestionnaireQuestionType.NPS, answer_options=(), scale=collision_scale) if item.question_id == "q-brand" else item for item in self.questions())
        for index, questions in enumerate((no_options, scaled, collision)):
            with self.subTest(index=index), self.assertRaises(QuantitativeQuestionnaireError): self.create(version_id=f"response-invalid-{index}", questions=questions)

    def test_role_exceptions_are_valid_but_fake_or_missing_purpose_fails(self):
        self.create()
        missing_purpose = tuple(replace(item, role_purpose=None) if item.question_id == "q-age" else item for item in self.questions())
        fake_link = tuple(replace(item, analytical_requirement_ids=(self.design.analytical_requirements[0].requirement_id,)) if item.question_id == "q-sex" else item for item in self.questions())
        no_requirement = tuple(replace(item, analytical_requirement_ids=()) if item.question_id == "q-brand" else item for item in self.questions())
        dangling = tuple(replace(item, analytical_requirement_ids=("missing",)) if item.question_id == "q-brand" else item for item in self.questions())
        for index, questions in enumerate((missing_purpose, fake_link, no_requirement, dangling)):
            with self.subTest(index=index), self.assertRaises(QuantitativeQuestionnaireError): self.create(version_id=f"role-invalid-{index}", questions=questions)

    def test_routing_reference_conflict_cycle_and_unreachable_fail_closed(self):
        invalid_ref = replace(self.termination_route(), action=RoutingAction(RoutingActionType.GOTO_QUESTION, target_id="missing"))
        conflict = replace(self.termination_route(), rule_id="route-conflict")
        cycle = QuestionnaireRoutingRule("cycle", "q-route", 1, RoutingCondition(RoutingConditionKind.PRESENT, question_id="q-route"), RoutingAction(RoutingActionType.GOTO_QUESTION, target_id="q-age"))
        unreachable = replace(self.termination_route(), action=RoutingAction(RoutingActionType.SKIP_QUESTION, target_id="q-brand"))
        cases = ((invalid_ref,), (self.termination_route(), conflict), (cycle,), (unreachable,))
        for index, routes in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(QuantitativeQuestionnaireError): self.create(version_id=f"route-invalid-{index}", routes=routes)

    def test_multiple_matrix_and_nps_expected_variable_mappings(self):
        requirement = self.design.analytical_requirements[0].requirement_id
        multiple = QuestionnaireQuestion("q-multi", "section-main", QuestionnaireQuestionRole.SUBSTANTIVE, QuestionnaireQuestionType.MULTIPLE_CHOICE, "Which brands?", None, None, (requirement,), None, True, self.options("multi"), None, (), (), (ExpectedVariableBinding("ev-multi-a", "brand_a", option_id="multi-a"), ExpectedVariableBinding("ev-multi-b", "brand_b", option_id="multi-b")), False, 2, "team")
        matrix = QuestionnaireQuestion("q-matrix", "section-main", QuestionnaireQuestionRole.SUBSTANTIVE, QuestionnaireQuestionType.MATRIX_SINGLE_CHOICE, "Rate attributes.", None, None, (requirement,), None, True, self.options("matrix"), None, (MatrixRow("row-quality", "Quality", 1), MatrixRow("row-value", "Value", 2)), (), (ExpectedVariableBinding("ev-quality-row", "attribute_quality", matrix_row_id="row-quality"), ExpectedVariableBinding("ev-value-row", "attribute_value", matrix_row_id="row-value")), False, 3, "team")
        nps_scale = ScaleDefinition(Decimal("0"), Decimal("10"), tuple((Decimal(index), str(index)) for index in range(11)), ScaleInterpretation.NUMERIC)
        nps = QuestionnaireQuestion("q-nps", "section-main", QuestionnaireQuestionRole.SUBSTANTIVE, QuestionnaireQuestionType.NPS, "How likely are you to recommend?", None, None, (requirement,), None, True, (), nps_scale, (), (), (ExpectedVariableBinding("ev-nps", "nps"),), False, 4, "team")
        value = self.create(questions=self.questions() + (multiple, matrix, nps))
        schema = self.service.derive_expected_measurement_schema(value.version_id, project_id=self.project)
        by_name = {item.variable_name: item for item in schema.variables}
        self.assertEqual(by_name["brand_a"].multiple_response_set_id, "q-multi")
        self.assertEqual(by_name["attribute_quality"].matrix_group_id, "q-matrix")
        self.assertEqual(by_name["nps"].semantic_hooks, ("NPS_SOURCE_0_10",))
        self.assertEqual(len([item for item in schema.variables if item.source_question_id == "q-matrix"]), 2)

    def test_coverage_not_measured_partial_and_not_applicable_are_explicit(self):
        no_substantive = tuple(item for item in self.questions() if item.question_id != "q-brand")
        value = self.create(questions=no_substantive)
        self.assertEqual(self.service.derive_coverage_manifest(value.version_id, project_id=self.project).requirements[0].status, QuestionnaireCoverageStatus.NOT_MEASURED)
        requirement = self.design.analytical_requirements[0].requirement_id
        for index, status in enumerate((QuestionnaireCoverageStatus.PARTIALLY_MEASURED, QuestionnaireCoverageStatus.NOT_APPLICABLE)):
            declaration = RequirementCoverageDeclaration(requirement, status, "Explicit human-reviewed coverage decision")
            declared = self.create(version_id=f"declared-{index}", questions=no_substantive, declarations=(declaration,))
            entry = self.service.derive_coverage_manifest(declared.version_id, project_id=self.project).requirements[0]
            self.assertEqual(entry.status, status); self.assertTrue(entry.rationale)
        invalid = RequirementCoverageDeclaration(requirement, QuestionnaireCoverageStatus.MEASURED, "Cannot override")
        with self.assertRaises(QuantitativeQuestionnaireError): self.create(version_id="invalid-declaration", declarations=(invalid,))

    def test_approval_projection_rejection_supersession_and_stale_fingerprints(self):
        approved = self.approve()
        self.assertEqual(self.service.resolve_current_approved(project_id=self.project, run_id=self.run), approved)
        projection = self.service.approved_projection(project_id=self.project, run_id=self.run)
        self.assertEqual(projection.version_id, approved.version_id)
        self.assertFalse(hasattr(projection, "respondent_rows"))
        self.service.supersede(approved.version_id, project_id=self.project, run_id=self.run, new_version_id="superseded", actor_id="owner", changed_at="later")
        with self.assertRaises(QuantitativeQuestionnaireError): self.service.resolve_current_approved(project_id=self.project, run_id=self.run)

        other = PropertyRAQuestionnaireAuthorityTests(methodName="runTest"); other.setUp()
        draft = other.create(); review = other.service.submit_for_review(draft.version_id, project_id=other.project, run_id=other.run, new_version_id="review", actor_id="r", changed_at="later")
        with self.assertRaisesRegex(QuantitativeQuestionnaireError, "fingerprint is stale"):
            other.service.approve(review.version_id, project_id=other.project, run_id=other.run, new_version_id="bad", approval_id="bad", expected_fingerprint="stale", expected_validation_fingerprint=review.validation_manifest_fingerprint, expected_coverage_fingerprint=review.coverage_manifest_fingerprint, actor_id="owner", decided_at="now", rationale="bad")
        other.service.reject(review.version_id, project_id=other.project, run_id=other.run, new_version_id="rejected", approval_id="rejected-approval", expected_fingerprint=review.fingerprint, actor_id="owner", decided_at="now", rationale="Rejected")
        with self.assertRaises(QuantitativeQuestionnaireError): other.service.resolve_current_approved(project_id=other.project, run_id=other.run)

    def test_design_revision_stales_questionnaire_for_fieldwork(self):
        self.approve()
        self.design_service.revise_design(self.design.version_id, project_id=self.project, run_id=self.run, version_id="new-design", created_at="later", created_by="owner")
        with self.assertRaisesRegex(QuantitativeQuestionnaireError, "current approved"):
            self.service.resolve_current_approved(project_id=self.project, run_id=self.run)

    def test_restart_corruption_wrong_project_and_dataset_only(self):
        approved = self.approve()
        restarted_state = QuantitativeStateService(repository=self.backing, digest_provider=self.digest)
        restarted = QuantitativeQuestionnaireService(repository=QLQuantitativeQuestionnaireRepository(restarted_state), research_design_service=self.design_service, digest_provider=self.digest)
        self.assertEqual(restarted.resolve_current_approved(project_id=self.project, run_id=self.run), approved)
        with self.assertRaises(QuantitativeQuestionnaireError): restarted.resolve_current_approved(project_id="wrong", run_id=self.run)
        dataset_only = restarted.resolve_dataset_only(authority_id="dataset-only-questionnaire", project_id=self.project, run_id=self.run)
        self.assertIsInstance(dataset_only, DatasetOnlyQuestionnaireAuthority)
        self.assertEqual(dataset_only.measurement_coverage_status, QuestionnaireCoverageAuthorityStatus.NOT_ASSESSED_NO_QUESTIONNAIRE)
        record = self.backing._records[approved.version_id]
        self.backing._records[approved.version_id] = replace(record, authority_fingerprint="corrupt")
        with self.assertRaises(QuantitativeQuestionnaireError): restarted.resolve_current_approved(project_id=self.project, run_id=self.run)

    def test_no_desk_or_provider_dependency(self):
        modules = " ".join((QuantitativeQuestionnaireService.__module__, type(self.repository).__module__))
        for forbidden in ("domain.planning", "evidence", "sufficiency", "LLMClient", "QuestionnaireSnapshot"):
            self.assertNotIn(forbidden, modules)


if __name__ == "__main__": unittest.main()
