from __future__ import annotations

from dataclasses import replace

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_questionnaire_repository import QuantitativeQuestionnaireRepository
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.questionnaire_validation import QuestionnaireAuthorityCompiler, QuestionnaireValidationError
from application.quantitative.research_design_authority import QuantitativeResearchDesignService, QuantitativeResearchDesignError
from domain.quantitative.questionnaire_authority import (
    ApprovedQuestionnaireProjection, DatasetOnlyQuestionnaireAuthority,
    QuestionnaireApprovalDecision, QuestionnaireAuthorityPresence, QuestionnaireCoverageStatus,
    QuestionnaireAuthorshipMode, QuestionnaireCoverageAuthorityStatus,
    QuestionnaireLifecycle, QuantitativeQuestionnaireApproval,
    QuantitativeQuestionnaireVersion,
)


DATASET_ONLY_LIMITATION = "Questionnaire measurement coverage cannot be assessed because no approved Questionnaire is present."


class QuantitativeQuestionnaireError(ValueError):
    pass


class QuantitativeQuestionnaireService:
    def __init__(self, *, repository: QuantitativeQuestionnaireRepository,
                 research_design_service: QuantitativeResearchDesignService,
                 digest_provider: DeterministicDigestProvider,
                 warning_length_minutes: int = 30) -> None:
        self._repository = repository
        self._designs = research_design_service
        self._digest = digest_provider
        self._compiler = QuestionnaireAuthorityCompiler(digest_provider=digest_provider, warning_length_minutes=warning_length_minutes)

    def create_draft(self, *, questionnaire_id: str, version_id: str, project_id: str, run_id: str,
                     research_design_version_id: str, research_design_fingerprint: str,
                     title: str, purpose: str, language: str, sections, questions,
                     routing_rules=(), provenance: str, authorship_mode: QuestionnaireAuthorshipMode,
                     estimated_interview_length_minutes: int, assumptions=(), limitations=(),
                     coverage_declarations=(), created_at: str, created_by: str) -> QuantitativeQuestionnaireVersion:
        design = self._current_design(project_id, run_id, research_design_version_id, research_design_fingerprint)
        if estimated_interview_length_minutes < 1 or estimated_interview_length_minutes > 600:
            raise QuantitativeQuestionnaireError("estimated interview length is invalid")
        value = QuantitativeQuestionnaireVersion(
            questionnaire_id, version_id, 1, project_id, "QUANTITATIVE",
            design.version_id, design.fingerprint, title, purpose, language,
            tuple(sections), tuple(questions), tuple(routing_rules), "", "", provenance,
            authorship_mode, estimated_interview_length_minutes, tuple(assumptions), tuple(limitations),
            tuple(coverage_declarations), None, QuestionnaireLifecycle.DRAFT, None,
            "", "", "", "", "", created_at, created_by,
        )
        return self._compile_and_persist(value, design=design, run_id=run_id)

    def revise(self, version_id: str, *, project_id: str, run_id: str, new_version_id: str,
               created_at: str, created_by: str, **changes) -> QuantitativeQuestionnaireVersion:
        current = self._require_questionnaire(version_id, project_id)
        design = self._current_design(project_id, run_id, current.research_design_version_id, current.research_design_fingerprint)
        allowed = {"title", "purpose", "language", "sections", "questions", "routing_rules", "provenance", "authorship_mode", "estimated_interview_length_minutes", "assumptions", "limitations", "coverage_declarations"}
        if set(changes) - allowed: raise QuantitativeQuestionnaireError("unsupported Questionnaire revision field")
        if "estimated_interview_length_minutes" in changes and not 1 <= changes["estimated_interview_length_minutes"] <= 600: raise QuantitativeQuestionnaireError("estimated interview length is invalid")
        for key in {"sections", "questions", "routing_rules", "assumptions", "limitations", "coverage_declarations"} & set(changes): changes[key] = tuple(changes[key])
        value = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1,
                        parent_version_id=current.version_id, lifecycle_status=QuestionnaireLifecycle.DRAFT,
                        approval_reference=None, created_at=created_at, created_by=created_by,
                        expected_measurement_schema_id="", expected_measurement_schema_fingerprint="",
                        validation_manifest_id="", validation_manifest_fingerprint="",
                        coverage_manifest_id="", coverage_manifest_fingerprint="", fingerprint="", **changes)
        return self._compile_and_persist(value, design=design, run_id=run_id)

    def validate(self, version_id: str, *, project_id: str, run_id: str):
        value = self._require_questionnaire(version_id, project_id)
        design = self._current_design(project_id, run_id, value.research_design_version_id, value.research_design_fingerprint)
        compiled = self._compiler.compile(value, design=design)
        self._compiler.require_valid(compiled[2])
        return compiled[2]

    def derive_expected_measurement_schema(self, version_id: str, *, project_id: str):
        value = self._require_questionnaire(version_id, project_id)
        schema = self._repository.get_schema(value.expected_measurement_schema_id, project_id=project_id)
        if schema is None or schema.fingerprint != value.expected_measurement_schema_fingerprint: raise QuantitativeQuestionnaireError("Expected Measurement Schema is missing or stale")
        return schema

    def derive_coverage_manifest(self, version_id: str, *, project_id: str):
        value = self._require_questionnaire(version_id, project_id)
        coverage = self._repository.get_coverage(value.coverage_manifest_id, project_id=project_id)
        if coverage is None or coverage.fingerprint != value.coverage_manifest_fingerprint: raise QuantitativeQuestionnaireError("Questionnaire coverage is missing or stale")
        return coverage

    def submit_for_review(self, version_id: str, *, project_id: str, run_id: str,
                          new_version_id: str, actor_id: str, changed_at: str):
        return self._transition(version_id, project_id=project_id, run_id=run_id, new_version_id=new_version_id, actor_id=actor_id, changed_at=changed_at, status=QuestionnaireLifecycle.IN_REVIEW)

    def approve(self, version_id: str, *, project_id: str, run_id: str, new_version_id: str,
                approval_id: str, expected_fingerprint: str,
                expected_validation_fingerprint: str, expected_coverage_fingerprint: str,
                actor_id: str, decided_at: str, rationale: str):
        current = self._require_questionnaire(version_id, project_id)
        if current.lifecycle_status is not QuestionnaireLifecycle.IN_REVIEW: raise QuantitativeQuestionnaireError("only an in-review Questionnaire can be approved")
        design = self._current_design(project_id, run_id, current.research_design_version_id, current.research_design_fingerprint)
        validation = self._repository.get_validation(current.validation_manifest_id, project_id=project_id)
        coverage = self._repository.get_coverage(current.coverage_manifest_id, project_id=project_id)
        if current.fingerprint != expected_fingerprint: raise QuantitativeQuestionnaireError("Questionnaire approval fingerprint is stale")
        if validation is None or not validation.valid or validation.fingerprint != expected_validation_fingerprint or validation.fingerprint != current.validation_manifest_fingerprint: raise QuantitativeQuestionnaireError("Questionnaire validation authority is missing, invalid, or stale")
        if coverage is None or coverage.fingerprint != expected_coverage_fingerprint or coverage.fingerprint != current.coverage_manifest_fingerprint: raise QuantitativeQuestionnaireError("Questionnaire coverage authority is missing or stale")
        mandatory = {item.requirement_id for item in design.analytical_requirements if item.obligation.value == "MANDATORY"}
        unsupported = [item.requirement_id for item in coverage.requirements if item.requirement_id in mandatory and item.status is QuestionnaireCoverageStatus.NOT_MEASURED]
        if unsupported:
            raise QuantitativeQuestionnaireError(
                "mandatory Analytical Requirement has no expected-variable measurement path")
        approved = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1, parent_version_id=current.version_id, lifecycle_status=QuestionnaireLifecycle.APPROVED, approval_reference=approval_id, created_at=decided_at, created_by=actor_id)
        approved, schema, new_validation, new_coverage = self._compiler.compile(approved, design=design)
        self._compiler.require_valid(new_validation)
        rationale = " ".join(rationale.split())
        if not rationale: raise QuantitativeQuestionnaireError("approval rationale is required")
        payload = {"contract": "RA_APPROVAL_V1", "approval_id": approval_id, "project_id": project_id, "questionnaire_version_id": approved.version_id, "questionnaire_fingerprint": approved.fingerprint, "design_version_id": design.version_id, "design_fingerprint": design.fingerprint, "validation": new_validation.fingerprint, "coverage": new_coverage.fingerprint, "actor": actor_id, "time": decided_at, "decision": "APPROVED", "rationale": rationale}
        approval = QuantitativeQuestionnaireApproval(approval_id, project_id, "QUANTITATIVE", approved.version_id, approved.fingerprint, design.version_id, design.fingerprint, new_validation.fingerprint, new_coverage.fingerprint, actor_id, decided_at, QuestionnaireApprovalDecision.APPROVED, rationale, canonical_digest(payload, digest_provider=self._digest))
        self._persist(approved, schema, new_validation, new_coverage, run_id)
        self._repository.save_approval(approval, run_id=run_id)
        return approved

    def reject(self, version_id: str, *, project_id: str, run_id: str, new_version_id: str,
               approval_id: str, expected_fingerprint: str, actor_id: str, decided_at: str, rationale: str):
        current = self._require_questionnaire(version_id, project_id)
        if current.lifecycle_status is not QuestionnaireLifecycle.IN_REVIEW: raise QuantitativeQuestionnaireError("only an in-review Questionnaire can be rejected")
        if current.fingerprint != expected_fingerprint: raise QuantitativeQuestionnaireError("Questionnaire approval fingerprint is stale")
        rejected = self._transition(version_id, project_id=project_id, run_id=run_id, new_version_id=new_version_id, actor_id=actor_id, changed_at=decided_at, status=QuestionnaireLifecycle.REJECTED, approval_reference=approval_id)
        rationale = " ".join(rationale.split())
        payload = {"contract": "RA_APPROVAL_V1", "approval_id": approval_id, "project_id": project_id, "questionnaire_version_id": rejected.version_id, "questionnaire_fingerprint": rejected.fingerprint, "design_version_id": rejected.research_design_version_id, "design_fingerprint": rejected.research_design_fingerprint, "validation": rejected.validation_manifest_fingerprint, "coverage": rejected.coverage_manifest_fingerprint, "actor": actor_id, "time": decided_at, "decision": "REJECTED", "rationale": rationale}
        approval = QuantitativeQuestionnaireApproval(approval_id, project_id, "QUANTITATIVE", rejected.version_id, rejected.fingerprint, rejected.research_design_version_id, rejected.research_design_fingerprint, rejected.validation_manifest_fingerprint, rejected.coverage_manifest_fingerprint, actor_id, decided_at, QuestionnaireApprovalDecision.REJECTED, rationale, canonical_digest(payload, digest_provider=self._digest))
        self._repository.save_approval(approval, run_id=run_id)
        if not rationale: raise QuantitativeQuestionnaireError("rejection rationale is required")
        return rejected

    def supersede(self, version_id: str, *, project_id: str, run_id: str, new_version_id: str, actor_id: str, changed_at: str):
        current = self._require_questionnaire(version_id, project_id)
        if current.lifecycle_status is not QuestionnaireLifecycle.APPROVED: raise QuantitativeQuestionnaireError("only an approved Questionnaire can be superseded")
        return self._transition(version_id, project_id=project_id, run_id=run_id, new_version_id=new_version_id, actor_id=actor_id, changed_at=changed_at, status=QuestionnaireLifecycle.SUPERSEDED)

    def resolve_current_approved(self, *, project_id: str, run_id: str):
        values = self._repository.list_questionnaires(project_id=project_id, run_id=run_id)
        if not values or values[-1].lifecycle_status is not QuestionnaireLifecycle.APPROVED: raise QuantitativeQuestionnaireError("no current approved Quantitative Questionnaire")
        value = values[-1]
        self._current_design(project_id, run_id, value.research_design_version_id, value.research_design_fingerprint)
        approval = self._repository.get_approval(value.approval_reference or "", project_id=project_id)
        if approval is None or approval.decision is not QuestionnaireApprovalDecision.APPROVED or approval.questionnaire_version_id != value.version_id or approval.questionnaire_fingerprint != value.fingerprint or approval.research_design_version_id != value.research_design_version_id or approval.research_design_fingerprint != value.research_design_fingerprint or approval.validation_manifest_fingerprint != value.validation_manifest_fingerprint or approval.coverage_manifest_fingerprint != value.coverage_manifest_fingerprint:
            raise QuantitativeQuestionnaireError("Questionnaire approval is missing, rejected, or stale")
        return value

    def approved_projection(self, *, project_id: str, run_id: str):
        value = self.resolve_current_approved(project_id=project_id, run_id=run_id)
        schema = self.derive_expected_measurement_schema(value.version_id, project_id=project_id)
        coverage = self.derive_coverage_manifest(value.version_id, project_id=project_id)
        return ApprovedQuestionnaireProjection(value.questionnaire_id, value.version_id, value.fingerprint, value.research_design_version_id, value.research_design_fingerprint,
            tuple((item.section_id, item.title) for item in value.sections),
            tuple((item.question_id, item.role.value, item.question_type.value, item.wording) for item in value.questions),
            tuple((question.question_id, option.option_id, option.dataset_value_code, option.label) for question in value.questions for option in question.answer_options),
            tuple((item.rule_id, item.source_question_id, item.action.action_type.value) for item in value.routing_rules),
            tuple((item.expected_variable_id, item.variable_name, item.variable_type.value) for item in schema.variables),
            tuple((item.question_id, item.analytical_requirement_ids) for item in value.questions),
            tuple((item.requirement_id, item.status.value) for item in coverage.requirements), value.limitations)

    def resolve_dataset_only(self, *, authority_id: str, project_id: str, run_id: str):
        payload = {"contract": "RA_DATASET_ONLY_V1", "authority_id": authority_id, "project_id": project_id, "run_id": run_id, "status": QuestionnaireCoverageAuthorityStatus.NOT_ASSESSED_NO_QUESTIONNAIRE.value, "limitation": DATASET_ONLY_LIMITATION}
        value = DatasetOnlyQuestionnaireAuthority(authority_id, project_id, run_id, QuestionnaireAuthorityPresence.ABSENT, QuestionnaireCoverageAuthorityStatus.NOT_ASSESSED_NO_QUESTIONNAIRE, DATASET_ONLY_LIMITATION, canonical_digest(payload, digest_provider=self._digest))
        self._repository.save_dataset_only(value)
        return value

    def _transition(self, version_id, *, project_id, run_id, new_version_id, actor_id, changed_at, status, approval_reference=None):
        current = self._require_questionnaire(version_id, project_id)
        design = self._current_design(project_id, run_id, current.research_design_version_id, current.research_design_fingerprint)
        value = replace(current, version_id=new_version_id, version_sequence=current.version_sequence + 1, parent_version_id=current.version_id, lifecycle_status=status, approval_reference=approval_reference, created_at=changed_at, created_by=actor_id, expected_measurement_schema_id="", expected_measurement_schema_fingerprint="", validation_manifest_id="", validation_manifest_fingerprint="", coverage_manifest_id="", coverage_manifest_fingerprint="")
        return self._compile_and_persist(value, design=design, run_id=run_id)

    def _compile_and_persist(self, value, *, design, run_id):
        try:
            value, schema, validation, coverage = self._compiler.compile(value, design=design)
            self._compiler.require_valid(validation)
        except (QuestionnaireValidationError, QuantitativeResearchDesignError) as exc:
            raise QuantitativeQuestionnaireError(str(exc)) from exc
        self._persist(value, schema, validation, coverage, run_id)
        return value

    def _persist(self, value, schema, validation, coverage, run_id):
        self._repository.save_questionnaire(value, run_id=run_id)
        self._repository.save_schema(schema, run_id=run_id)
        self._repository.save_validation(validation, run_id=run_id)
        self._repository.save_coverage(coverage, run_id=run_id)

    def _current_design(self, project_id, run_id, version_id, fingerprint):
        try:
            design = self._designs.resolve_current_approved(project_id=project_id, run_id=run_id)
        except QuantitativeResearchDesignError as exc:
            raise QuantitativeQuestionnaireError("current approved Research Design is unavailable") from exc
        if design.version_id != version_id or design.fingerprint != fingerprint: raise QuantitativeQuestionnaireError("Research Design version or fingerprint is stale")
        return design

    def _require_questionnaire(self, version_id, project_id):
        value = self._repository.get_questionnaire(version_id, project_id=project_id)
        if value is None or value.project_id != project_id or value.methodology != "QUANTITATIVE": raise QuantitativeQuestionnaireError("Quantitative Questionnaire is unavailable for project")
        return value
