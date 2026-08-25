from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import re

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.dataset import PiiClassification, VariableRole, VariableType
from domain.quantitative.questionnaire_authority import (
    AnswerOption, ExpectedMeasurementSchema, ExpectedMissingValueRule,
    ExpectedVariableDefinition, QuestionnaireCoverageStatus,
    QuestionnaireDesignCoverageManifest, QuestionnaireLifecycle,
    QuestionnaireQuestion, QuestionnaireQuestionRole, QuestionnaireQuestionType,
    QuestionnaireRoutingRule, QuestionnaireValidationManifest,
    QuantitativeQuestionnaireVersion, RequirementMeasurementCoverage,
    RoutingActionType, RoutingCondition, RoutingConditionKind, ScaleInterpretation,
)
from domain.quantitative.research_design_authority import QuantitativeResearchDesignVersion


class QuestionnaireValidationError(ValueError):
    pass


def _text(value: str, *, optional: bool = False) -> str | None:
    result = " ".join(str(value or "").split())
    if not result and optional:
        return None
    if not result or len(result) > 6000:
        raise QuestionnaireValidationError("Questionnaire text is empty or oversized")
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", result) or re.search(r"(?:\+?\d[\s().-]*){7,}", result):
        raise QuestionnaireValidationError("direct PII is forbidden in Questionnaire authority")
    return result


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        raise QuestionnaireValidationError("non-finite numeric authority")
    rendered = format(value.normalize(), "f")
    return "0" if rendered == "-0" else rendered


def _ids(values, attribute: str, label: str) -> set[str]:
    result = [getattr(item, attribute) for item in values]
    if any(not item for item in result) or len(result) != len(set(result)):
        raise QuestionnaireValidationError(f"duplicate or empty {label} ID")
    return set(result)


class QuestionnaireAuthorityCompiler:
    def __init__(self, *, digest_provider: DeterministicDigestProvider, warning_length_minutes: int = 30) -> None:
        self._digest = digest_provider
        self._warning_length = warning_length_minutes

    def compile(self, questionnaire: QuantitativeQuestionnaireVersion, *, design: QuantitativeResearchDesignVersion):
        value = self._canonical(questionnaire, design)
        variables = self._derive_variables(value)
        questionnaire_fp = canonical_digest(self._questionnaire_payload(value, variables), digest_provider=self._digest)
        value = replace(value, fingerprint=questionnaire_fp)
        schema = self._schema(value, variables)
        blockers, warnings = self._validate(value, design, schema)
        validation = self._validation(value, blockers, warnings)
        coverage = self._coverage(value, design, schema)
        value = replace(
            value,
            expected_measurement_schema_id=schema.schema_id,
            expected_measurement_schema_fingerprint=schema.fingerprint,
            validation_manifest_id=validation.manifest_id,
            validation_manifest_fingerprint=validation.fingerprint,
            coverage_manifest_id=coverage.manifest_id,
            coverage_manifest_fingerprint=coverage.fingerprint,
        )
        return value, schema, validation, coverage

    def require_valid(self, validation: QuestionnaireValidationManifest) -> None:
        if not validation.valid:
            raise QuestionnaireValidationError("; ".join(validation.blockers))

    def _canonical(self, value, design):
        if value.methodology != "QUANTITATIVE" or design.methodology != "QUANTITATIVE":
            raise QuestionnaireValidationError("wrong Questionnaire methodology")
        if value.project_id != design.project_id:
            raise QuestionnaireValidationError("Questionnaire and Research Design Project mismatch")
        if value.research_design_version_id != design.version_id or value.research_design_fingerprint != design.fingerprint:
            raise QuestionnaireValidationError("Research Design version or fingerprint is stale")
        sections = tuple(sorted((replace(item, title=_text(item.title), purpose=_text(item.purpose)) for item in value.sections), key=lambda item: (item.display_order, item.section_id)))
        _ids(sections, "section_id", "Section")
        questions = []
        for item in value.questions:
            options = tuple(sorted((replace(option, label=_text(option.label), dataset_value_code=_text(option.dataset_value_code), missing_semantic=_text(option.missing_semantic, optional=True)) for option in item.answer_options), key=lambda option: (option.display_order, option.option_id)))
            if not isinstance(item.question_type, QuestionnaireQuestionType):
                raise QuestionnaireValidationError("unsupported Questionnaire question type")
            if not isinstance(item.role, QuestionnaireQuestionRole):
                raise QuestionnaireValidationError("unsupported Questionnaire question role")
            rows = tuple(sorted((replace(row, label=_text(row.label)) for row in item.matrix_rows), key=lambda row: (row.display_order, row.row_id)))
            bindings = tuple(sorted((replace(binding, variable_name=_text(binding.variable_name)) for binding in item.expected_variable_bindings), key=lambda binding: binding.expected_variable_id))
            questions.append(replace(item, wording=_text(item.wording), respondent_instructions=_text(item.respondent_instructions, optional=True), interviewer_instructions=_text(item.interviewer_instructions, optional=True), role_purpose=_text(item.role_purpose, optional=True), provenance=_text(item.provenance), analytical_requirement_ids=tuple(sorted(item.analytical_requirement_ids)), answer_options=options, matrix_rows=rows, expected_variable_bindings=bindings, validation_constraints=tuple(sorted(item.validation_constraints))))
        section_order = {item.section_id: index for index, item in enumerate(sections)}
        questions = tuple(sorted(questions, key=lambda item: (section_order.get(item.section_id, 10**9), item.display_order, item.question_id)))
        routes = tuple(sorted(value.routing_rules, key=lambda item: (item.source_question_id, item.priority, item.rule_id)))
        declarations = tuple(sorted((replace(item, rationale=_text(item.rationale)) for item in value.coverage_declarations), key=lambda item: item.requirement_id))
        return replace(value, title=_text(value.title), purpose=_text(value.purpose), language=_text(value.language), sections=sections, questions=questions, routing_rules=routes, provenance=_text(value.provenance), assumptions=tuple(sorted(_text(item) for item in value.assumptions)), limitations=tuple(sorted(_text(item) for item in value.limitations)), coverage_declarations=declarations)

    def _derive_variables(self, value) -> tuple[ExpectedVariableDefinition, ...]:
        variables = []
        for question in value.questions:
            bindings = question.expected_variable_bindings
            option_by_id = {item.option_id: item for item in question.answer_options}
            row_by_id = {item.row_id: item for item in question.matrix_rows}
            for binding in bindings:
                option = option_by_id.get(binding.option_id) if binding.option_id else None
                row = row_by_id.get(binding.matrix_row_id) if binding.matrix_row_id else None
                variable_type, level = self._variable_type(question)
                value_labels = tuple((item.dataset_value_code, item.label) for item in question.answer_options)
                ordering = tuple(item.dataset_value_code for item in sorted(question.answer_options, key=lambda item: item.ordinal_position if item.ordinal_position is not None else item.display_order) if item.ordinal_position is not None)
                scoring = tuple((item.dataset_value_code, item.analytical_score) for item in question.answer_options if item.analytical_score is not None)
                missing = tuple(ExpectedMissingValueRule(item.dataset_value_code, item.missing_semantic) for item in question.answer_options if item.missing_semantic)
                mr_set = None
                matrix_group = question.question_id if row else None
                hooks = ()
                label = row.label if row else question.wording
                if question.question_type is QuestionnaireQuestionType.MULTIPLE_CHOICE:
                    variable_type, level = VariableType.CATEGORICAL, "nominal"
                    value_labels = (("0", "Not selected"), ("1", "Selected"))
                    ordering, scoring, missing = (), (), ()
                    mr_set = question.question_id
                    label = f"{question.wording}: {option.label if option else ''}".strip()
                elif question.question_type is QuestionnaireQuestionType.NPS:
                    hooks = ("NPS_SOURCE_0_10",)
                if question.scale:
                    value_labels = tuple((_decimal(code) or "", text) for code, text in question.scale.ordered_labels)
                    ordering = tuple(code for code, _ in value_labels)
                    scoring = tuple((_decimal(code) or "", score) for code, score in question.scale.analytical_scores)
                    missing = tuple(ExpectedMissingValueRule(_decimal(code) or "", semantic) for code, semantic in question.scale.missing_value_codes)
                role = VariableRole.DEMOGRAPHIC if question.role is QuestionnaireQuestionRole.DEMOGRAPHIC else VariableRole.RESPONSE
                if question.role in {QuestionnaireQuestionRole.QUALITY_CONTROL, QuestionnaireQuestionRole.TECHNICAL_ROUTING}:
                    role = VariableRole.OTHER
                pii = PiiClassification.REVIEW_REQUIRED if question.question_type is QuestionnaireQuestionType.OPEN_TEXT else PiiClassification.NONE
                payload = {"id": binding.expected_variable_id, "name": binding.variable_name.casefold(), "question": question.question_id, "option": binding.option_id, "row": binding.matrix_row_id, "label": label, "type": variable_type.value, "role": role.value, "level": level, "labels": list(value_labels), "ordering": list(ordering), "scores": [(key, _decimal(score)) for key, score in scoring], "missing": [(item.code, item.semantic) for item in missing], "mr": mr_set, "matrix": matrix_group, "hooks": list(hooks), "weighting": question.role is QuestionnaireQuestionRole.DEMOGRAPHIC, "pii": pii.value}
                variables.append(ExpectedVariableDefinition(binding.expected_variable_id, binding.variable_name, question.question_id, binding.option_id, binding.matrix_row_id, label, variable_type, role, level, value_labels, ordering, scoring, missing, mr_set, matrix_group, hooks, question.role is QuestionnaireQuestionRole.DEMOGRAPHIC, pii, canonical_digest(payload, digest_provider=self._digest)))
        return tuple(sorted(variables, key=lambda item: item.expected_variable_id))

    @staticmethod
    def _variable_type(question):
        if question.question_type in {QuestionnaireQuestionType.SINGLE_CHOICE, QuestionnaireQuestionType.MULTIPLE_CHOICE, QuestionnaireQuestionType.MATRIX_SINGLE_CHOICE}:
            return VariableType.CATEGORICAL, "nominal"
        if question.question_type is QuestionnaireQuestionType.OPEN_TEXT:
            return VariableType.OPEN_TEXT, "text"
        if question.question_type is QuestionnaireQuestionType.NUMERIC:
            return VariableType.NUMERIC, "scale"
        if question.scale and question.scale.interpretation is ScaleInterpretation.NUMERIC:
            return VariableType.NUMERIC, "scale"
        return VariableType.ORDINAL_SCALE, "ordinal"

    def _validate(self, value, design, schema):
        blockers = []
        try:
            section_ids = _ids(value.sections, "section_id", "Section")
            question_ids = _ids(value.questions, "question_id", "Question")
            rule_ids = _ids(value.routing_rules, "rule_id", "Routing Rule")
            variable_ids = _ids(schema.variables, "expected_variable_id", "Expected Variable")
        except QuestionnaireValidationError as exc:
            return (str(exc),), ()
        variable_names = [item.variable_name.strip().casefold() for item in schema.variables]
        if any(not item for item in variable_names) or len(variable_names) != len(set(variable_names)):
            blockers.append("duplicate or empty expected variable name")
        design_requirements = {item.requirement_id for item in design.analytical_requirements}
        question_by_id = {item.question_id: item for item in value.questions}
        section_questions = {section_id: [] for section_id in section_ids}
        for question in value.questions:
            if question.section_id not in section_ids:
                blockers.append(f"Question {question.question_id} has invalid Section reference")
            else:
                section_questions[question.section_id].append(question.question_id)
            option_ids = [item.option_id for item in question.answer_options]
            row_ids = [item.row_id for item in question.matrix_rows]
            binding_ids = [item.expected_variable_id for item in question.expected_variable_bindings]
            if len(option_ids) != len(set(option_ids)): blockers.append(f"Question {question.question_id} has duplicate option ID")
            if len(row_ids) != len(set(row_ids)): blockers.append(f"Question {question.question_id} has duplicate matrix row ID")
            if len(binding_ids) != len(set(binding_ids)): blockers.append(f"Question {question.question_id} has duplicate expected variable binding")
            codes = [item.dataset_value_code for item in question.answer_options]
            if len(codes) != len(set(codes)): blockers.append(f"Question {question.question_id} has duplicate option code")
            if any(item.exclusive and (item.other_specify or item.missing_semantic) for item in question.answer_options): blockers.append(f"Question {question.question_id} has incompatible exclusive option")
            if question.role is QuestionnaireQuestionRole.SUBSTANTIVE:
                if not question.analytical_requirement_ids: blockers.append(f"Substantive Question {question.question_id} has no Analytical Requirement")
                if not set(question.analytical_requirement_ids) <= design_requirements: blockers.append(f"Question {question.question_id} has dangling Analytical Requirement")
                if question.role_purpose is not None: blockers.append(f"Substantive Question {question.question_id} must not use exception purpose")
            else:
                if question.analytical_requirement_ids: blockers.append(f"Non-substantive Question {question.question_id} has fake Analytical Requirement linkage")
                if not question.role_purpose: blockers.append(f"Exception-role Question {question.question_id} requires explicit purpose")
            blockers.extend(self._response_blockers(question))
        if set(variable_ids) != {item.expected_variable_id for question in value.questions for item in question.expected_variable_bindings}:
            blockers.append("expected variable derivation mismatch")
        blockers.extend(self._routing_blockers(value, question_by_id, section_ids, section_questions, rule_ids))
        warnings = () if value.estimated_interview_length_minutes <= self._warning_length else (f"estimated interview length exceeds configured {self._warning_length} minute review threshold",)
        return tuple(sorted(set(blockers))), warnings

    def _response_blockers(self, question):
        blockers = []
        categorical = {QuestionnaireQuestionType.SINGLE_CHOICE, QuestionnaireQuestionType.MULTIPLE_CHOICE, QuestionnaireQuestionType.MATRIX_SINGLE_CHOICE}
        scale_types = {QuestionnaireQuestionType.RATING_SCALE, QuestionnaireQuestionType.LIKERT, QuestionnaireQuestionType.NPS, QuestionnaireQuestionType.MATRIX_RATING}
        matrix_types = {QuestionnaireQuestionType.MATRIX_SINGLE_CHOICE, QuestionnaireQuestionType.MATRIX_RATING}
        if question.question_type in categorical and len(question.answer_options) < 2: blockers.append(f"Question {question.question_id} requires answer options")
        if question.question_type not in categorical and question.question_type not in matrix_types and question.answer_options: blockers.append(f"Question {question.question_id} has incompatible answer options")
        if question.question_type in scale_types and question.scale is None: blockers.append(f"Question {question.question_id} requires a scale")
        if question.question_type not in scale_types and question.scale is not None: blockers.append(f"Question {question.question_id} has incompatible scale")
        if question.question_type in matrix_types and not question.matrix_rows: blockers.append(f"Question {question.question_id} requires matrix rows")
        if question.question_type not in matrix_types and question.question_type is not QuestionnaireQuestionType.LIKERT and question.matrix_rows: blockers.append(f"Question {question.question_id} has incompatible matrix rows")
        if question.scale:
            if not question.scale.minimum.is_finite() or not question.scale.maximum.is_finite() or question.scale.minimum >= question.scale.maximum: blockers.append(f"Question {question.question_id} has invalid scale bounds")
            label_codes = [code for code, _ in question.scale.ordered_labels]
            missing_codes = [code for code, _ in question.scale.missing_value_codes]
            if len(label_codes) != len(set(label_codes)) or len(missing_codes) != len(set(missing_codes)) or set(label_codes) & set(missing_codes): blockers.append(f"Question {question.question_id} has invalid or colliding scale codes")
            if any(code < question.scale.minimum or code > question.scale.maximum for code in label_codes): blockers.append(f"Question {question.question_id} has scale label outside bounds")
        if question.question_type is QuestionnaireQuestionType.NPS and (question.scale is None or question.scale.minimum != 0 or question.scale.maximum != 10): blockers.append(f"Question {question.question_id} must use NPS 0-10 scale")
        expected = len(question.expected_variable_bindings)
        if question.question_type is QuestionnaireQuestionType.MULTIPLE_CHOICE:
            if {item.option_id for item in question.expected_variable_bindings} != {item.option_id for item in question.answer_options}: blockers.append(f"Question {question.question_id} requires one expected variable per option")
        elif question.question_type in matrix_types or (question.question_type is QuestionnaireQuestionType.LIKERT and question.matrix_rows):
            if {item.matrix_row_id for item in question.expected_variable_bindings} != {item.row_id for item in question.matrix_rows}: blockers.append(f"Question {question.question_id} requires one expected variable per matrix row")
        elif expected != 1 or question.expected_variable_bindings[0].option_id is not None or question.expected_variable_bindings[0].matrix_row_id is not None:
            blockers.append(f"Question {question.question_id} requires exactly one expected variable")
        return blockers

    def _condition_blockers(self, condition: RoutingCondition, question_by_id):
        blockers = []
        compound = condition.kind in {RoutingConditionKind.AND, RoutingConditionKind.OR, RoutingConditionKind.NOT}
        if compound:
            required = 1 if condition.kind is RoutingConditionKind.NOT else 2
            if len(condition.children) < required or (condition.kind is RoutingConditionKind.NOT and len(condition.children) != 1): blockers.append("invalid compound routing condition")
            for child in condition.children: blockers.extend(self._condition_blockers(child, question_by_id))
            return blockers
        question = question_by_id.get(condition.question_id or "")
        if question is None: return ("routing condition has invalid Question reference",)
        option_ids = {item.option_id for item in question.answer_options}
        if not set(condition.option_ids) <= option_ids: blockers.append("routing condition has invalid Answer Option reference")
        option_kinds = {RoutingConditionKind.EQUALS_OPTION, RoutingConditionKind.IN_OPTION_SET, RoutingConditionKind.SELECTED, RoutingConditionKind.NOT_SELECTED}
        if condition.kind in option_kinds and not condition.option_ids: blockers.append("option routing condition requires option reference")
        if condition.kind in {RoutingConditionKind.SELECTED, RoutingConditionKind.NOT_SELECTED} and question.question_type is not QuestionnaireQuestionType.MULTIPLE_CHOICE: blockers.append("selected predicate requires multiple-choice Question")
        if condition.kind is RoutingConditionKind.NUMERIC_COMPARE and (question.question_type not in {QuestionnaireQuestionType.NUMERIC, QuestionnaireQuestionType.RATING_SCALE, QuestionnaireQuestionType.NPS} or condition.comparator is None or condition.numeric_value is None): blockers.append("numeric routing predicate is incompatible")
        return blockers

    def _routing_blockers(self, value, question_by_id, section_ids, section_questions, rule_ids):
        blockers, keys, edges = [], set(), {item.question_id: set() for item in value.questions}
        for first, second in zip(value.questions, value.questions[1:]): edges[first.question_id].add(second.question_id)
        for rule in value.routing_rules:
            if rule.source_question_id not in question_by_id: blockers.append(f"Routing Rule {rule.rule_id} has invalid source")
            key = (rule.source_question_id, rule.priority)
            if key in keys: blockers.append(f"Routing Rule {rule.rule_id} conflicts at same priority")
            keys.add(key)
            blockers.extend(self._condition_blockers(rule.condition, question_by_id))
            action = rule.action
            if action.action_type in {RoutingActionType.GOTO_QUESTION, RoutingActionType.SKIP_QUESTION}:
                if action.target_id not in question_by_id: blockers.append(f"Routing Rule {rule.rule_id} has invalid Question target")
                elif action.action_type is RoutingActionType.GOTO_QUESTION: edges.setdefault(rule.source_question_id, set()).add(action.target_id)
                elif question_by_id[action.target_id].response_required: blockers.append(f"Routing Rule {rule.rule_id} makes required Question unreachable")
            elif action.action_type in {RoutingActionType.GOTO_SECTION, RoutingActionType.SKIP_SECTION}:
                if action.target_id not in section_ids: blockers.append(f"Routing Rule {rule.rule_id} has invalid Section target")
                elif action.action_type is RoutingActionType.GOTO_SECTION and section_questions[action.target_id]: edges.setdefault(rule.source_question_id, set()).add(section_questions[action.target_id][0])
                elif action.action_type is RoutingActionType.SKIP_SECTION and any(question_by_id[item].response_required for item in section_questions[action.target_id]): blockers.append(f"Routing Rule {rule.rule_id} makes required Section unreachable")
            elif action.action_type in {RoutingActionType.TERMINATE, RoutingActionType.SCREENED_OUT}:
                if not action.termination_code: blockers.append(f"Routing Rule {rule.rule_id} requires explicit termination code")
            elif action.action_type is RoutingActionType.DEFAULT_CONTINUE and action.target_id is not None: blockers.append(f"Routing Rule {rule.rule_id} default continuation cannot have target")
        visiting, visited = set(), set()
        def visit(node):
            if node in visiting: return True
            if node in visited: return False
            visiting.add(node)
            for target in edges.get(node, ()):
                if visit(target): return True
            visiting.remove(node); visited.add(node); return False
        if any(visit(node) for node in edges if node not in visited): blockers.append("routing graph contains a cycle")
        return blockers

    def _questionnaire_payload(self, value, variables):
        def condition(item): return {"kind": item.kind.value, "question": item.question_id, "options": list(item.option_ids), "comparator": item.comparator.value if item.comparator else None, "value": _decimal(item.numeric_value), "children": [condition(child) for child in item.children]}
        return {"contract": "RA_QUESTIONNAIRE_V1", "questionnaire_id": value.questionnaire_id, "project_id": value.project_id, "methodology": value.methodology, "design_version": value.research_design_version_id, "design_fingerprint": value.research_design_fingerprint, "title": value.title, "purpose": value.purpose, "language": value.language, "sections": [{"id": item.section_id, "title": item.title, "purpose": item.purpose, "order": item.display_order} for item in value.sections], "questions": [{"id": item.question_id, "section": item.section_id, "role": item.role.value, "type": item.question_type.value, "wording": item.wording, "respondent": item.respondent_instructions, "interviewer": item.interviewer_instructions, "requirements": list(item.analytical_requirement_ids), "purpose": item.role_purpose, "required": item.response_required, "options": [{"id": option.option_id, "label": option.label, "code": option.dataset_value_code, "order": option.display_order, "ordinal": option.ordinal_position, "score": _decimal(option.analytical_score), "exclusive": option.exclusive, "other": option.other_specify, "missing": option.missing_semantic} for option in item.answer_options], "scale": None if item.scale is None else {"min": _decimal(item.scale.minimum), "max": _decimal(item.scale.maximum), "labels": [(_decimal(code), text) for code, text in item.scale.ordered_labels], "interpretation": item.scale.interpretation.value, "scores": [(_decimal(code), _decimal(score)) for code, score in item.scale.analytical_scores], "missing": [(_decimal(code), text) for code, text in item.scale.missing_value_codes]}, "rows": [{"id": row.row_id, "label": row.label, "order": row.display_order} for row in item.matrix_rows], "constraints": list(item.validation_constraints), "bindings": [{"id": binding.expected_variable_id, "name": binding.variable_name.casefold(), "option": binding.option_id, "row": binding.matrix_row_id} for binding in item.expected_variable_bindings], "routing": item.routing_participation, "order": item.display_order, "provenance": item.provenance} for item in value.questions], "routes": [{"id": item.rule_id, "source": item.source_question_id, "priority": item.priority, "condition": condition(item.condition), "action": item.action.action_type.value, "target": item.action.target_id, "termination": item.action.termination_code} for item in value.routing_rules], "expected_variables": [{"id": item.expected_variable_id, "fingerprint": item.fingerprint} for item in variables], "provenance": value.provenance, "authorship": value.authorship_mode.value, "length": value.estimated_interview_length_minutes, "assumptions": list(value.assumptions), "limitations": list(value.limitations), "coverage_declarations": [{"requirement": item.requirement_id, "status": item.status.value, "rationale": item.rationale} for item in value.coverage_declarations]}

    def _schema(self, value, variables):
        payload = {"contract": "RA_EXPECTED_SCHEMA_V1", "questionnaire": value.version_id, "questionnaire_fingerprint": value.fingerprint, "variables": [(item.expected_variable_id, item.fingerprint) for item in variables]}
        return ExpectedMeasurementSchema(f"{value.version_id}:expected-schema", value.project_id, value.version_id, value.fingerprint, variables, canonical_digest(payload, digest_provider=self._digest))

    def _validation(self, value, blockers, warnings):
        payload = {"contract": "RA_VALIDATION_V1", "questionnaire": value.version_id, "fingerprint": value.fingerprint, "valid": not blockers, "blockers": list(blockers), "warnings": list(warnings)}
        return QuestionnaireValidationManifest(f"{value.version_id}:validation", value.project_id, value.version_id, value.fingerprint, not blockers, blockers, warnings, canonical_digest(payload, digest_provider=self._digest))

    def _coverage(self, value, design, schema):
        declaration_by_id = {item.requirement_id: item for item in value.coverage_declarations}
        known = {item.requirement_id for item in design.analytical_requirements}
        if not set(declaration_by_id) <= known: raise QuestionnaireValidationError("coverage declaration has dangling Analytical Requirement")
        question_variables = {question.question_id: tuple(item.expected_variable_id for item in schema.variables if item.source_question_id == question.question_id) for question in value.questions}
        entries = []
        for requirement in design.analytical_requirements:
            questions = tuple(item.question_id for item in value.questions if requirement.requirement_id in item.analytical_requirement_ids)
            variables = tuple(variable for question in questions for variable in question_variables[question])
            declaration = declaration_by_id.get(requirement.requirement_id)
            if declaration:
                if declaration.status not in {QuestionnaireCoverageStatus.PARTIALLY_MEASURED, QuestionnaireCoverageStatus.NOT_APPLICABLE}: raise QuestionnaireValidationError("coverage declaration supports PARTIAL or NOT_APPLICABLE only")
                status, rationale = declaration.status, declaration.rationale
            elif questions and variables:
                status, rationale = QuestionnaireCoverageStatus.MEASURED, None
            else:
                status, rationale = QuestionnaireCoverageStatus.NOT_MEASURED, None
            entries.append(RequirementMeasurementCoverage(requirement.requirement_id, status, questions, variables, rationale))
        payload = {"contract": "RA_COVERAGE_V1", "design": design.version_id, "design_fingerprint": design.fingerprint, "questionnaire": value.version_id, "questionnaire_fingerprint": value.fingerprint, "schema": schema.fingerprint, "requirements": [(item.requirement_id, item.status.value, list(item.supporting_question_ids), list(item.expected_variable_ids), item.rationale) for item in entries]}
        return QuestionnaireDesignCoverageManifest(f"{value.version_id}:coverage", value.project_id, design.version_id, design.fingerprint, value.version_id, value.fingerprint, schema.fingerprint, tuple(entries), canonical_digest(payload, digest_provider=self._digest))
