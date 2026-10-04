"""Product commands for the canonical Quant authority workflow.

This module translates bounded user intent into the accepted QZ/RA/RB/RC
services.  It does not calculate statistics or introduce a parallel authority
model.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

from application.methods.quantitative.pin import METHOD_PIN, resolve_method_pin
from application.quantitative.comparison_statistics import MEAN_METHOD, PROPORTION_METHOD
from application.quantitative.ui_service import QuantitativeUiError
from application.quantitative.workflow import CMF_QUANTITATIVE_WORKFLOW_ID
from domain.quantitative.analysis import (
    AnalysisSpecification,
    ComparisonSpecification,
    CrossTabAnalysisSpecification,
    NumericAnalysisSpecification,
)
from domain.quantitative.analysis_plan import (
    AnalysisExecutionSupport,
    AnalysisWeightingPolicy,
    CategoryEqualsFilter,
    ComparisonResultRoleSelector,
    ExactWeightSetBinding,
    PlanVariableBinding,
    PlannedAnalysis,
    PlannedComparison,
    QuantitativeAnalysisPlanVersion,
)
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, VariableType
from domain.quantitative.measurement_reconciliation import (
    ReconciliationMatchStatus,
    ReviewedMeasurementMapping,
)
from domain.quantitative.questionnaire_authority import (
    AnswerOption,
    ExpectedVariableBinding,
    QuestionnaireAuthorshipMode,
    QuestionnaireQuestion,
    QuestionnaireQuestionRole,
    QuestionnaireQuestionType,
    QuestionnaireSection,
    ScaleDefinition,
    ScaleInterpretation,
)
from domain.quantitative.research_design_authority import (
    AnalyticalRequirement,
    DeliverableRequirement,
    MethodologyIntent,
    QuantitativeResearchQuestion,
    RequirementObligation,
    ResearchObjective,
    ResearchPriority,
    TargetPopulation,
)
from domain.quantitative.weighting import WeightSet
from domain.quantitative.workflow import QuantitativeApproval, QuantitativeApprovalDecision
from application.quantitative.weighting import approve_weight_set


SUPPORTED_PROCEDURES = {
    "ONE_WAY",
    "NUMERIC_SUMMARY",
    "CROSS_TAB",
    PROPORTION_METHOD,
    MEAN_METHOD,
}


@dataclass(frozen=True)
class QuantitativeDesignIntent:
    title: str
    research_question: str
    population: str
    procedure: str
    primary_variable_id: str
    group_variable_id: str | None = None
    outcome_category: str | None = None
    group_a_category: str | None = None
    group_b_category: str | None = None
    weighting_mode: str = "UNWEIGHTED"


class QuantitativeAuthorityProductService:
    """Owner-scoped product facade over the immutable Quant authority services."""

    def __init__(self, *, ui_service, finalization_service) -> None:
        self.ui = ui_service
        self.finalization = finalization_service
        self.designs = finalization_service._designs
        self.questionnaires = finalization_service._questionnaires
        self.reconciliations = finalization_service._reconciliations
        self.plans = finalization_service._plans

    def projection(self, study_id: str, *, owner_id: str) -> dict:
        study = self.ui.get(study_id, owner_id=owner_id)
        run = self.ui.workflows.get_workflow_run(study.run_id)
        canonical = run.workflow_template_id == CMF_QUANTITATIVE_WORKFLOW_ID
        dataset, codebook = self.ui._dataset(study) if study.dataset_record_id else (None, None)
        qc = self.ui.state.load(study.qc_record_id, project_id=study.project_id) if study.qc_record_id else None
        weight = self.ui.state.load(study.weight_set_record_id, project_id=study.project_id) if study.weight_set_record_id else None
        plans = tuple(item for item in self.ui.state.list_for_run(
            study.run_id, project_id=study.project_id,
        ) if isinstance(item, QuantitativeAnalysisPlanVersion))
        plan = max(plans, key=lambda item: item.version_sequence) if plans else None
        method_pin = self.ui.workflows.get_task_results(run.id).get(METHOD_PIN)
        if canonical:
            resolve_method_pin(method_pin, project_id=study.project_id, run_id=study.run_id)
        return {
            "canonical": canonical,
            "execution_label": "Канонічне кількісне дослідження" if canonical else "Історичне кількісне дослідження",
            "dataset_version": getattr(dataset, "version_id", None),
            "dataset_identity": self._short(getattr(dataset, "dataset_fingerprint", None)),
            "dataset_checksum": self._short(getattr(dataset, "file_checksum", None)),
            "qc_approval_token": getattr(qc, "fingerprint", None),
            "weight_approval_token": getattr(weight, "reproducibility_fingerprint", None),
            "dataset_bound_version": getattr(plan, "dataset_version_id", None),
            "dataset_bound_identity": self._short(getattr(plan, "dataset_fingerprint", None)),
            "design_state": getattr(getattr(plan, "lifecycle_status", None), "value", "INCOMPLETE"),
            "design_version": getattr(plan, "version_id", None),
            "design_identity": self._short(getattr(plan, "fingerprint", None)),
            "design_approval_token": getattr(plan, "fingerprint", None),
            "variables": tuple(
                {
                    "id": item.variable_id,
                    "name": item.name,
                    "label": item.label or item.name,
                    "type": item.variable_type.value,
                    "eligible": item.analytically_eligible and (
                        item.variable_type is VariableType.NUMERIC or bool(item.value_labels)
                    ),
                    "categories": tuple((str(code), str(label)) for code, label in item.value_labels),
                }
                for item in getattr(codebook, "variables", ())
            ),
            "limits": {"bytes": 20 * 1024 * 1024, "rows": 10_000, "variables": 200, "cells": 100_000},
        }

    def configure(self, study_id: str, *, owner_id: str, intent: QuantitativeDesignIntent):
        intent = replace(
            intent,
            procedure=intent.procedure.strip().upper(),
            weighting_mode=intent.weighting_mode.strip().upper(),
        )
        study = self.ui.get(study_id, owner_id=owner_id)
        run = self.ui.workflows.get_workflow_run(study.run_id)
        if run.workflow_template_id != CMF_QUANTITATIVE_WORKFLOW_ID:
            raise QuantitativeUiError("Historical Quant studies cannot create a canonical analysis design")
        pin = self.ui.workflows.get_task_results(run.id).get(METHOD_PIN)
        resolve_method_pin(pin, project_id=study.project_id, run_id=study.run_id)
        if study.state not in {"WEIGHTING_REQUIRED", "READY_TO_ANALYZE"}:
            raise QuantitativeUiError("Approve current dataset quality before configuring analysis")
        dataset, codebook = self.ui._dataset(study)
        self._require_no_plan(study, dataset)
        clean = self._validate_intent(intent, codebook)
        if intent.weighting_mode == "WEIGHTED":
            self._approved_weight(study)
        now = datetime.now(UTC).isoformat()
        token = str(uuid5(NAMESPACE_URL, f"qnt06b:{study.run_id}:{dataset.dataset_fingerprint}:{clean}"))
        scope = {"project_id": study.project_id, "run_id": study.run_id}

        brief = self.designs.create_brief(
            brief_id=f"brief-{token}", version_id=f"brief-{token}:v1", **scope,
            title=intent.title, business_context=study.description or intent.title,
            business_problem=intent.research_question, decision_context="Підтримати кількісний аналіз",
            research_purpose=intent.research_question, intended_audience=("Дослідницька команда",),
            target_deliverables=("Звіт",), constraints=("Підтримувані процедури V1",),
            provenance="PRODUCT_AUTHORED", created_at=now, created_by=owner_id,
        )
        brief = self.designs.submit_brief_for_review(
            brief.version_id, **scope, new_version_id=f"brief-{token}:review",
            actor_id=owner_id, changed_at=now,
        )
        brief = self.designs.approve_brief(
            brief.version_id, **scope, new_version_id=f"brief-{token}:approved",
            approval_id=f"brief-{token}:approval", expected_fingerprint=brief.fingerprint,
            actor_id=owner_id, decided_at=now, rationale="Підтверджено користувачем у продукті",
        )
        requirement_type = self._requirement_type(intent.procedure)
        objective = ResearchObjective("objective-1", intent.research_question, ResearchPriority.HIGH)
        question = QuantitativeResearchQuestion(
            "rq-1", intent.research_question, (objective.objective_id,), requirement_type,
            ResearchPriority.HIGH,
        )
        requirement = AnalyticalRequirement(
            "requirement-1", requirement_type, intent.research_question,
            (objective.objective_id,), (question.question_id,), RequirementObligation.MANDATORY,
        )
        design = self.designs.create_design(
            design_id=f"design-{token}", version_id=f"design-{token}:v1", **scope,
            source_brief_version_id=brief.version_id, source_brief_fingerprint=brief.fingerprint,
            objectives=(objective,), research_questions=(question,), hypotheses=(),
            target_population=TargetPopulation((), (intent.population,), ()),
            methodology_intent=MethodologyIntent(
                "QUANTITATIVE", "IMPORTED_DATASET", "Provided dataset", intent.weighting_mode,
            ),
            analytical_requirements=(requirement,),
            deliverable_requirements=(DeliverableRequirement(
                "deliverable-1", "REPORT", "Дослідницька команда", "uk",
                RequirementObligation.MANDATORY,
            ),),
            assumptions=("Набір даних відповідає затвердженому дизайну",),
            limitations=("Аналіз обмежено підтримуваними процедурами V1",),
            created_at=now, created_by=owner_id,
        )
        design = self.designs.submit_for_review(
            design.version_id, **scope, new_version_id=f"design-{token}:review",
            actor_id=owner_id, changed_at=now,
        )
        design = self.designs.approve(
            design.version_id, **scope, new_version_id=f"design-{token}:approved",
            approval_id=f"design-{token}:approval", expected_fingerprint=design.fingerprint,
            actor_id=owner_id, decided_at=now, rationale="Дизайн перевірено у продукті",
        )

        selected = self._selected_variables(intent, codebook)
        questions = tuple(self._question(variable, requirement.requirement_id, index)
                          for index, variable in enumerate(selected, 1))
        questionnaire = self.questionnaires.create_draft(
            questionnaire_id=f"questionnaire-{token}", version_id=f"questionnaire-{token}:v1",
            **scope, research_design_version_id=design.version_id,
            research_design_fingerprint=design.fingerprint, title=intent.title,
            purpose=intent.research_question, language="uk",
            sections=(QuestionnaireSection("main", "Змінні аналізу", "Канонічне зіставлення", 1),),
            questions=questions, routing_rules=(), provenance="PRODUCT_DATASET_MAPPING",
            authorship_mode=QuestionnaireAuthorshipMode.INTERNAL_HUMAN,
            estimated_interview_length_minutes=max(1, len(questions)), assumptions=(), limitations=(),
            created_at=now, created_by=owner_id,
        )
        questionnaire = self.questionnaires.submit_for_review(
            questionnaire.version_id, **scope, new_version_id=f"questionnaire-{token}:review",
            actor_id=owner_id, changed_at=now,
        )
        questionnaire = self.questionnaires.approve(
            questionnaire.version_id, **scope, new_version_id=f"questionnaire-{token}:approved",
            approval_id=f"questionnaire-{token}:approval",
            expected_fingerprint=questionnaire.fingerprint,
            expected_validation_fingerprint=questionnaire.validation_manifest_fingerprint,
            expected_coverage_fingerprint=questionnaire.coverage_manifest_fingerprint,
            actor_id=owner_id, decided_at=now, rationale="Змінні перевірено у продукті",
        )

        reconciliation = self.reconciliations.create(
            reconciliation_id=f"reconciliation-{token}", version_id=f"reconciliation-{token}:v1",
            **scope, dataset=dataset, codebook=codebook, created_at=now, created_by=owner_id,
        )
        if reconciliation.lifecycle_status.value != "APPROVED":
            expected_schema = self.questionnaires.derive_expected_measurement_schema(
                questionnaire.version_id, project_id=study.project_id,
            )
            expected_by_id = {
                item.expected_variable_id: item for item in expected_schema.variables
            }
            actual_by_id = {item.variable_id: item for item in codebook.variables}
            reviewed_mappings = []
            for outcome in reconciliation.variable_outcomes:
                if not outcome.actual_variable_id:
                    raise QuantitativeUiError(
                        "Selected variables cannot be mapped to the current dataset"
                    )
                expected = expected_by_id[outcome.expected_variable_id]
                actual = actual_by_id[outcome.actual_variable_id]
                category_mapping = tuple(
                    (str(code), str(code)) for code, _ in expected.value_labels
                )
                missing_mapping = tuple(
                    (
                        str(rule.value if rule.value is not None else (
                            rule.low if rule.low == rule.high else f"{rule.low}:{rule.high}"
                        )),
                        str(rule.value if rule.value is not None else (
                            rule.low if rule.low == rule.high else f"{rule.low}:{rule.high}"
                        )),
                    )
                    for rule in actual.missing_rules
                )
                reviewed_mappings.append(ReviewedMeasurementMapping(
                    decision_id=f"mapping-{token}-{expected.expected_variable_id}",
                    expected_variable_id=expected.expected_variable_id,
                    expected_variable_fingerprint=expected.fingerprint,
                    actual_variable_id=actual.variable_id,
                    actual_variable_fingerprint=actual.fingerprint,
                    category_code_mapping=category_mapping,
                    missing_semantic_mapping=missing_mapping,
                    scale_mapping=category_mapping,
                    mr_matrix_mapping=(),
                    actor_id=owner_id,
                    rationale="Зіставлення змінної перевірено користувачем у продукті",
                    decided_at=now,
                    fingerprint=f"reviewed-{token}-{expected.expected_variable_id}",
                ))
            reconciliation = self.reconciliations.create(
                reconciliation_id=f"reconciliation-{token}",
                version_id=f"reconciliation-{token}:reviewed", **scope,
                dataset=dataset, codebook=codebook, created_at=now,
                created_by=owner_id, reviewed_mappings=tuple(reviewed_mappings),
                parent_version_id=reconciliation.version_id,
            )
            reconciliation = self.reconciliations.approve(
                reconciliation.version_id, **scope,
                approval_id=f"reconciliation-{token}:approval",
                expected_fingerprint=reconciliation.fingerprint,
                actor_id=owner_id, decided_at=now,
                rationale="Зіставлення змінних підтверджено у продукті",
                dataset=dataset, codebook=codebook,
            )

        bindings = {
            outcome.actual_variable_id: PlanVariableBinding(
                outcome.expected_variable_id, outcome.actual_variable_id, outcome.actual_variable_fingerprint
            )
            for outcome in reconciliation.variable_outcomes
            if (
                outcome.status in {
                    ReconciliationMatchStatus.EXACT_MATCH,
                    ReconciliationMatchStatus.COMPATIBLE_MATCH,
                }
                or (
                    outcome.status is ReconciliationMatchStatus.REQUIRES_REVIEW
                    and outcome.reviewer_decision_reference
                )
            )
            and outcome.actual_variable_id
        }
        analyses, comparisons = self._plan_items(intent, codebook, bindings, study)
        weights = self._weight_authorities(study, analyses, intent.weighting_mode)
        if intent.weighting_mode == "WEIGHTED":
            binding = self._exact_weight_binding(study)
            analyses = tuple(replace(item, weight_set_binding=binding) for item in analyses)
        plan = self.plans.create_draft(
            plan_id=f"plan-{token}", version_id=f"plan-{token}:v1", **scope,
            dataset=dataset, codebook=codebook, planned_analyses=analyses,
            planned_comparisons=comparisons, weight_sets=weights,
            assumptions=("Виконання використовує лише зафіксовані авторитети",),
            limitations=("Процедури поза V1 не підтримуються",),
            created_at=now, created_by=owner_id,
        )
        return self.plans.submit_for_review(
            plan.version_id, **scope, new_version_id=f"plan-{token}:review",
            actor_id=owner_id, changed_at=now,
        )

    def approve(self, study_id: str, *, owner_id: str, plan_version_id: str,
                expected_fingerprint: str, rationale: str):
        study = self.ui.get(study_id, owner_id=owner_id)
        run = self.ui.workflows.get_workflow_run(study.run_id)
        if run.workflow_template_id != CMF_QUANTITATIVE_WORKFLOW_ID:
            raise QuantitativeUiError("Historical Quant studies cannot approve a canonical analysis design")
        dataset, codebook = self.ui._dataset(study)
        plan = self.ui.state.load(
            plan_version_id, project_id=study.project_id,
            expected_type=QuantitativeAnalysisPlanVersion,
        )
        if (plan.dataset_version_id, plan.dataset_fingerprint) != (
            dataset.version_id, dataset.dataset_fingerprint
        ):
            raise QuantitativeUiError("Analysis design is bound to a different dataset version")
        weights = self._weight_authorities(study, plan.planned_analyses,
                                           "WEIGHTED" if any(x.weight_set_binding for x in plan.planned_analyses) else "UNWEIGHTED")
        return self.plans.approve(
            plan.version_id, project_id=study.project_id, run_id=study.run_id,
            new_version_id=f"{plan.version_id}:approved",
            approval_id=f"{plan.version_id}:approval", expected_fingerprint=expected_fingerprint,
            actor_id=owner_id, decided_at=datetime.now(UTC).isoformat(),
            rationale=rationale.strip() or "Дизайн затверджено у продукті",
            dataset=dataset, codebook=codebook, weight_sets=weights,
        )

    def _require_no_plan(self, study, dataset) -> None:
        plans = tuple(item for item in self.ui.state.list_for_run(
            study.run_id, project_id=study.project_id,
        ) if isinstance(item, QuantitativeAnalysisPlanVersion))
        if plans:
            current = max(plans, key=lambda item: item.version_sequence)
            if current.dataset_version_id != dataset.version_id or current.dataset_fingerprint != dataset.dataset_fingerprint:
                raise QuantitativeUiError("Existing analysis design is bound to another dataset version")
            raise QuantitativeUiError("An analysis design already exists for this dataset")

    @staticmethod
    def _validate_intent(intent, codebook):
        procedure = intent.procedure.strip().upper()
        if procedure not in SUPPORTED_PROCEDURES:
            raise QuantitativeUiError("Unsupported analysis procedure")
        if intent.weighting_mode not in {"WEIGHTED", "UNWEIGHTED"}:
            raise QuantitativeUiError("Weighting mode must be explicit")
        if procedure in {PROPORTION_METHOD, MEAN_METHOD} and intent.weighting_mode != "UNWEIGHTED":
            raise QuantitativeUiError("Supported significance comparisons are unweighted")
        available = {
            item.variable_id: item for item in codebook.variables
            if item.analytically_eligible and (
                item.variable_type is VariableType.NUMERIC or bool(item.value_labels)
            )
        }
        if intent.primary_variable_id not in available:
            raise QuantitativeUiError("Selected analysis variable is unavailable")
        if procedure in {"CROSS_TAB", PROPORTION_METHOD, MEAN_METHOD}:
            if not intent.group_variable_id or intent.group_variable_id not in available:
                raise QuantitativeUiError("Selected group variable is unavailable")
            if intent.group_variable_id == intent.primary_variable_id:
                raise QuantitativeUiError("Analysis and group variables must differ")
        if procedure in {PROPORTION_METHOD, MEAN_METHOD}:
            if not intent.group_a_category or not intent.group_b_category:
                raise QuantitativeUiError("Both comparison groups are required")
            if intent.group_a_category == intent.group_b_category:
                raise QuantitativeUiError("Comparison groups must differ")
            QuantitativeAuthorityProductService._require_category(
                available[intent.group_variable_id], intent.group_a_category,
            )
            QuantitativeAuthorityProductService._require_category(
                available[intent.group_variable_id], intent.group_b_category,
            )
        if procedure == PROPORTION_METHOD and not intent.outcome_category:
            raise QuantitativeUiError("Outcome category is required")
        if procedure == PROPORTION_METHOD:
            QuantitativeAuthorityProductService._require_category(
                available[intent.primary_variable_id], intent.outcome_category,
            )
        if procedure in {"NUMERIC_SUMMARY", MEAN_METHOD} and available[intent.primary_variable_id].variable_type not in {VariableType.NUMERIC, VariableType.ORDINAL_SCALE}:
            raise QuantitativeUiError("Numeric analysis requires a numeric variable")
        return "|".join((intent.title.strip(), intent.research_question.strip(), intent.population.strip(), procedure,
                         intent.primary_variable_id, intent.group_variable_id or "", intent.outcome_category or "",
                         intent.group_a_category or "", intent.group_b_category or "", intent.weighting_mode))

    @staticmethod
    def _requirement_type(procedure):
        if procedure in {"ONE_WAY"}: return "ONE_WAY"
        if procedure in {"NUMERIC_SUMMARY", MEAN_METHOD}: return "NUMERIC_SUMMARY"
        return "CROSS_TAB"

    @staticmethod
    def _selected_variables(intent, codebook):
        ids = [intent.primary_variable_id]
        if intent.group_variable_id and intent.group_variable_id not in ids:
            ids.append(intent.group_variable_id)
        variables = {item.variable_id: item for item in codebook.variables}
        return tuple(variables[item] for item in ids)

    @staticmethod
    def _question(variable, requirement_id, order):
        categorical = variable.variable_type in {VariableType.CATEGORICAL, VariableType.DEMOGRAPHIC}
        ordinal = variable.variable_type is VariableType.ORDINAL_SCALE
        options = tuple(
            AnswerOption(f"option-{order}-{index}", str(label), str(code), index)
            for index, (code, label) in enumerate(variable.value_labels, 1)
        ) if categorical else ()
        scale = None
        if ordinal:
            labels = tuple((Decimal(str(code)), str(label)) for code, label in variable.value_labels)
            scale = ScaleDefinition(
                min(code for code, _ in labels), max(code for code, _ in labels),
                labels, ScaleInterpretation.ORDINAL,
            )
        return QuestionnaireQuestion(
            f"question-{order}", "main",
            QuestionnaireQuestionRole.SUBSTANTIVE,
            QuestionnaireQuestionType.SINGLE_CHOICE if categorical else (
                QuestionnaireQuestionType.RATING_SCALE if ordinal else QuestionnaireQuestionType.NUMERIC
            ),
            variable.label or variable.name, None, None, (requirement_id,), None, True,
            options, scale, (), (),
            (ExpectedVariableBinding(f"expected-{order}", variable.name),),
            False, order, "PRODUCT_DATASET_MAPPING",
        )

    def _plan_items(self, intent, codebook, bindings, study):
        primary = codebook.variable_by_id(intent.primary_variable_id)
        group = codebook.variable_by_id(intent.group_variable_id) if intent.group_variable_id else None
        pb = bindings.get(primary.variable_id)
        gb = bindings.get(group.variable_id) if group else None
        if pb is None or (group and gb is None):
            raise QuantitativeUiError("Selected variable mapping is unavailable")
        weighted = intent.weighting_mode == "WEIGHTED"
        policy = AnalysisWeightingPolicy.WEIGHTED_EXACT_WEIGHTSET if weighted else AnalysisWeightingPolicy.UNWEIGHTED
        weighting_status = "WEIGHTED" if weighted else "UNWEIGHTED"
        common = dict(objective_ids=("objective-1",), research_question_ids=("rq-1",),
                      analytical_requirement_ids=("requirement-1",), obligation="MANDATORY",
                      weighting_policy=policy, assumptions=(), limitations=(),
                      execution_support=AnalysisExecutionSupport.SUPPORTED,
                      population_description=intent.population)
        comparisons = ()
        if intent.procedure == "ONE_WAY":
            analyses = (PlannedAnalysis("analysis-1", AnalysisSpecification("spec-1", primary.variable_id, weighting_status=weighting_status), "", variable_bindings=(pb,), expected_result_family="TOTAL_DISTRIBUTION", **common),)
        elif intent.procedure == "NUMERIC_SUMMARY":
            analyses = (PlannedAnalysis("analysis-1", NumericAnalysisSpecification("spec-1", primary.variable_id, weighting_status=weighting_status), "", variable_bindings=(pb,), expected_result_family="NUMERIC_SUMMARY", **common),)
        elif intent.procedure in {"CROSS_TAB", PROPORTION_METHOD}:
            spec = CrossTabAnalysisSpecification(specification_id="spec-1", variable_id=primary.variable_id,
                                                 column_variable_id=group.variable_id, weighting_status=weighting_status)
            analyses = (PlannedAnalysis("analysis-1", spec, "", variable_bindings=(pb, gb), expected_result_family="CROSS_TAB", **common),)
            if intent.procedure == PROPORTION_METHOD:
                comparisons = (self._comparison(intent, primary, group, ("analysis-1",),
                                                  "CROSS_TAB_COLUMN_PERCENTAGE"),)
        else:
            analyses = tuple(
                PlannedAnalysis(
                    f"analysis-{index}",
                    NumericAnalysisSpecification(
                        f"spec-{index}", primary.variable_id, weighting_status="UNWEIGHTED",
                        filter_definition="CATEGORY_EQUALS", filter_variable_id=group.variable_id,
                        filter_category_value=self._category(group, category),
                    ), "", variable_bindings=(pb, gb), expected_result_family="NUMERIC_SUMMARY",
                    category_filter=CategoryEqualsFilter(
                        group.variable_id, group.fingerprint, self._category(group, category),
                        f"{group.label or group.name}: {category}",
                    ), **common,
                )
                for index, category in enumerate((intent.group_a_category, intent.group_b_category), 1)
            )
            comparisons = (self._comparison(intent, primary, group, ("analysis-1", "analysis-2"), "NUMERIC_MEAN"),)
        return analyses, comparisons

    def _comparison(self, intent, primary, group, precursor_ids, statistic_type):
        group_a = self._category(group, intent.group_a_category)
        group_b = self._category(group, intent.group_b_category)
        outcome = self._category(primary, intent.outcome_category) if intent.outcome_category is not None else None
        selectors = tuple(
            ComparisonResultRoleSelector(
                role, precursor, statistic_type, primary.variable_id, group.variable_id,
                outcome, category, "ALL_ROWS" if statistic_type.startswith("CROSS_TAB") else "CATEGORY_EQUALS",
            )
            for role, precursor, category in zip(("GROUP_A", "GROUP_B"),
                                                 (precursor_ids[0], precursor_ids[-1]),
                                                 (group_a, group_b))
        )
        spec = ComparisonSpecification(
            "comparison-1", intent.procedure, primary.variable_id, group.variable_id,
            group_a, group_b, outcome,
        )
        return PlannedComparison(
            "comparison-1", spec, "", tuple(precursor_ids), ("rq-1",),
            ("requirement-1",), "SIGNIFICANCE", (), (), selectors,
            ("objective-1",), "MANDATORY",
        )

    @staticmethod
    def _category(variable, raw):
        if raw is None: return None
        for value, _ in variable.value_labels:
            if str(value) == str(raw): return value
        try: return Decimal(str(raw))
        except InvalidOperation: return raw

    @staticmethod
    def _require_category(variable, raw):
        if raw is None or str(raw) not in {str(value) for value, _ in variable.value_labels}:
            raise QuantitativeUiError("Selected category is unavailable")

    def _weight_authorities(self, study, analyses, mode):
        if mode == "UNWEIGHTED":
            if study.weight_set_record_id or study.weight_approval_id:
                raise QuantitativeUiError("Unweighted design cannot carry a WeightSet")
            return {}
        weight, approval = self._approved_weight(study)
        return {item.planned_analysis_id: (weight, approval) for item in analyses}

    def _approved_weight(self, study):
        if not study.weight_set_record_id or not study.weight_approval_id:
            raise QuantitativeUiError("Approve a WeightSet before using weighted analysis")
        weight = self.ui.state.load(
            study.weight_set_record_id, project_id=study.project_id,
            expected_type=WeightSet,
        )
        approval = self.ui.state.load(
            study.weight_approval_id, project_id=study.project_id,
            expected_type=QuantitativeApproval,
        )
        if (
            approval.decision is not QuantitativeApprovalDecision.APPROVED
            or not approval.current
            or approval.subject_type != "WEIGHTSET"
            or approval.subject_id != weight.weight_set_id
            or approval.subject_fingerprint != weight.reproducibility_fingerprint
        ):
            raise QuantitativeUiError("WeightSet is not approved")
        return weight, approve_weight_set(
            weight_set=weight, approver_id=approval.actor_id,
            approved_at=approval.decided_at, digest_provider=self.ui.digest,
        )

    def _exact_weight_binding(self, study):
        weight, approval = self._approved_weight(study)
        return ExactWeightSetBinding(
            weight.weight_set_id, weight.reproducibility_fingerprint, weight.dataset_version_id,
            weight.dataset_fingerprint, weight.validation_fingerprint, approval.fingerprint,
            None, tuple(weight.validation_messages),
        )

    @staticmethod
    def _short(value):
        return f"{value[:12]}…" if value else None
