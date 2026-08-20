from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_dataset_ports import DatasetStorage
from application.quantitative.fingerprints import (
    canonical_digest,
    canonical_scalar,
    fingerprint_data,
)
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, DatasetVersionKind
from domain.quantitative.quality import (
    ApprovalState,
    CleaningAction,
    CleaningDecision,
    CleaningDecisionSet,
    DataQualityIssue,
    DatasetQualityAssessment,
    DatasetQualityState,
    InterviewState,
    IssueClass,
    IssueReconciliation,
    IssueType,
    QualityControlRun,
    QuestionnaireSnapshot,
    ReconciliationState,
    RoutingConsequence,
)

ENGINE_VERSION = "qb-1"


class QuantitativeQualityError(ValueError):
    pass


def _digest(payload: Any, provider: DeterministicDigestProvider) -> str:
    return canonical_digest(payload, digest_provider=provider)


def build_questionnaire_snapshot(
    *,
    snapshot_id: str,
    version: str,
    codebook_version_id: str,
    question_variable_bindings: tuple[tuple[str, str], ...],
    answer_domains: tuple[tuple[str, tuple[Any, ...]], ...] = (),
    required_variable_ids: tuple[str, ...] = (),
    routing_rules: tuple[Any, ...] = (),
    interview_state_variable_id: str | None = None,
    technical_id_variable_id: str | None = None,
    digest_provider: DeterministicDigestProvider,
) -> QuestionnaireSnapshot:
    payload = {
        "snapshot_id": snapshot_id,
        "version": version,
        "codebook_version_id": codebook_version_id,
        "bindings": question_variable_bindings,
        "domains": [(key, [canonical_scalar(v) for v in values]) for key, values in answer_domains],
        "required": required_variable_ids,
        "routing": [rule.fingerprint for rule in routing_rules],
        "interview_state": interview_state_variable_id,
        "technical_id": technical_id_variable_id,
    }
    return QuestionnaireSnapshot(
        snapshot_id, version, codebook_version_id, question_variable_bindings,
        answer_domains, required_variable_ids, routing_rules,
        interview_state_variable_id, technical_id_variable_id,
        _digest(payload, digest_provider),
    )


class DataQualityService:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider

    def detect(
        self,
        *,
        dataset: DatasetVersion,
        codebook: CodebookVersion,
        questionnaire: QuestionnaireSnapshot,
        detection_run_id: str,
    ) -> QualityControlRun:
        if questionnaire.codebook_version_id != codebook.codebook_version_id:
            raise QuantitativeQualityError("questionnaire/codebook binding mismatch")
        rows = self._storage.get_parsed_rows(dataset.version_id)
        refs = self._storage.get_respondent_lineage(dataset.version_id)
        if len(rows) != len(refs):
            raise QuantitativeQualityError("row/lineage cardinality mismatch")
        index = {variable.variable_id: i for i, variable in enumerate(codebook.variables)}
        domains = dict(questionnaire.answer_domains)
        issues: list[DataQualityIssue] = []
        not_evaluated: list[str] = []

        for variable_id, allowed in domains.items():
            if variable_id not in index:
                not_evaluated.append(f"domain:{variable_id}")
                continue
            affected = [refs[i] for i, row in enumerate(rows) if not _missing(row[index[variable_id]]) and row[index[variable_id]] not in allowed]
            if affected:
                issues.append(self._issue(dataset, detection_run_id, IssueType.OUT_OF_DOMAIN_VALUE, f"domain:{variable_id}", "1", (variable_id,), affected))

        state_index = index.get(questionnaire.interview_state_variable_id or "")
        for variable_id in questionnaire.required_variable_ids:
            if variable_id not in index:
                not_evaluated.append(f"required:{variable_id}")
                continue
            affected = []
            for i, row in enumerate(rows):
                state = row[state_index] if state_index is not None else InterviewState.COMPLETED.value
                if state == InterviewState.SCREENED_OUT.value:
                    continue
                if _missing(row[index[variable_id]]):
                    affected.append(refs[i])
            if affected:
                issues.append(self._issue(dataset, detection_run_id, IssueType.REQUIRED_ANSWER_MISSING, f"required:{variable_id}", "1", (variable_id,), affected))

        if state_index is not None:
            partial = [refs[i] for i, row in enumerate(rows) if row[state_index] == InterviewState.PARTIAL.value]
            if partial:
                issues.append(self._issue(dataset, detection_run_id, IssueType.PARTIAL_INTERVIEW, "interview-state", "1", (questionnaire.interview_state_variable_id or "",), partial, issue_class=IssueClass.METHODOLOGICAL_REVIEW_FLAG))

        for rule in questionnaire.routing_rules:
            if rule.antecedent_variable_id not in index or rule.target_variable_id not in index:
                not_evaluated.append(rule.rule_id)
                continue
            affected = []
            for i, row in enumerate(rows):
                if row[index[rule.antecedent_variable_id]] not in rule.antecedent_values:
                    continue
                target = row[index[rule.target_variable_id]]
                violates = (
                    rule.consequence is RoutingConsequence.REQUIRED and _missing(target)
                ) or (
                    rule.consequence in {RoutingConsequence.SKIPPED, RoutingConsequence.TERMINATED}
                    and not _missing(target)
                )
                if violates:
                    affected.append(refs[i])
            if affected:
                issues.append(self._issue(dataset, detection_run_id, IssueType.ROUTING_VIOLATION, rule.rule_id, rule.version, (rule.antecedent_variable_id, rule.target_variable_id), affected, rule_fingerprint=rule.fingerprint))

        tech_id = questionnaire.technical_id_variable_id
        if tech_id and tech_id in index:
            groups: dict[tuple[str, str], list[str]] = {}
            for i, row in enumerate(rows):
                key = canonical_scalar(row[index[tech_id]])
                groups.setdefault((key["type"], key["value"]), []).append(refs[i])
            duplicate_refs = sorted({ref for group in groups.values() if len(group) > 1 for ref in group})
            if duplicate_refs:
                issues.append(self._issue(dataset, detection_run_id, IssueType.DUPLICATE_RESPONDENT_ID, f"duplicate:{tech_id}", "1", (tech_id,), duplicate_refs, severity="BLOCKING"))
        elif tech_id:
            not_evaluated.append(f"duplicate:{tech_id}")

        issues_tuple = tuple(sorted(issues, key=lambda item: item.issue_id))
        fp = _digest({"dataset": dataset.dataset_fingerprint, "questionnaire": questionnaire.fingerprint, "issues": [i.reproducibility_fingerprint for i in issues_tuple], "not_evaluated": sorted(set(not_evaluated))}, self._digest)
        return QualityControlRun(detection_run_id, dataset.version_id, dataset.dataset_fingerprint, questionnaire.fingerprint, issues_tuple, tuple(sorted(set(not_evaluated))), fp)

    def _issue(self, dataset: DatasetVersion, run_id: str, issue_type: IssueType, rule_id: str, rule_version: str, variables: tuple[str, ...], refs: list[str], *, issue_class: IssueClass = IssueClass.DETERMINISTIC_VIOLATION, rule_fingerprint: str = "", severity: str = "REVIEW") -> DataQualityIssue:
        affected = tuple(sorted(set(refs)))
        affected_fp = _digest(affected, self._digest)
        rule_fp = rule_fingerprint or _digest({"id": rule_id, "version": rule_version}, self._digest)
        payload = {"dataset": dataset.dataset_fingerprint, "type": issue_type.value, "class": issue_class.value, "rule": rule_fp, "affected": affected_fp, "variables": variables}
        reproducibility = _digest(payload, self._digest)
        issue_id = str(uuid5(NAMESPACE_URL, f"qb-issue:{reproducibility}"))
        share = str((Decimal(len(affected)) / Decimal(dataset.row_count)) if dataset.row_count else Decimal(0))
        return DataQualityIssue(issue_id, dataset.version_id, dataset.dataset_fingerprint, run_id, issue_type, issue_class, rule_id, rule_version, rule_fp, affected, affected_fp, len(affected), share, variables, severity, (("affected_count", str(len(affected))),), reproducibility)


def build_cleaning_decision(*, parent: DatasetVersion, action: CleaningAction, affected_refs: tuple[str, ...], variable_ids: tuple[str, ...] = (), transformation: tuple[tuple[str, Any], ...] = (), rationale: str = "", actor_id: str, issue_ids: tuple[str, ...] = (), digest_provider: DeterministicDigestProvider) -> CleaningDecision:
    affected = tuple(sorted(set(affected_refs)))
    material = action in {CleaningAction.EXCLUDE_RESPONDENTS, CleaningAction.SET_MISSING, CleaningAction.RECODE}
    if material and not rationale.strip():
        raise QuantitativeQualityError("material cleaning requires rationale")
    payload = {"parent": parent.dataset_fingerprint, "action": action.value, "refs": affected, "variables": variable_ids, "transformation": [(k, canonical_scalar(v)) for k, v in transformation], "rationale": rationale.strip(), "actor": actor_id, "issues": issue_ids}
    fingerprint = _digest(payload, digest_provider)
    return CleaningDecision(str(uuid5(NAMESPACE_URL, f"qb-decision:{fingerprint}")), parent.dataset_fingerprint, issue_ids, action, affected, variable_ids, transformation, rationale.strip(), actor_id, len(affected), _digest({"action": action.value, "refs": affected, "variables": variable_ids, "transformation": transformation}, digest_provider), fingerprint)


def build_cleaning_decision_set(*, parent: DatasetVersion, decisions: tuple[CleaningDecision, ...], approval_state: ApprovalState, approver_id: str | None, approved_at: str | None, digest_provider: DeterministicDigestProvider) -> CleaningDecisionSet:
    if any(item.parent_dataset_fingerprint != parent.dataset_fingerprint for item in decisions):
        raise QuantitativeQualityError("decision parent fingerprint mismatch")
    _validate_conflicts(decisions)
    preview_count = len({ref for item in decisions if item.material for ref in item.affected_respondent_refs})
    preview_fp = _digest({"parent": parent.dataset_fingerprint, "decisions": [d.expected_transformation_fingerprint for d in decisions], "count": preview_count}, digest_provider)
    payload = {"parent_id": parent.version_id, "parent": parent.dataset_fingerprint, "decisions": [d.fingerprint for d in decisions], "preview": preview_fp, "count": preview_count}
    fingerprint = _digest(payload, digest_provider)
    if approval_state is ApprovalState.APPROVED and (not approver_id or not approved_at):
        raise QuantitativeQualityError("approved set requires approval metadata")
    return CleaningDecisionSet(str(uuid5(NAMESPACE_URL, f"qb-decision-set:{fingerprint}")), parent.version_id, parent.dataset_fingerprint, decisions, preview_fp, preview_count, approval_state, approver_id, approved_at, fingerprint)


def _validate_conflicts(decisions: tuple[CleaningDecision, ...]) -> None:
    excluded: set[str] = set()
    cells: set[tuple[str, str]] = set()
    for decision in decisions:
        if decision.action is CleaningAction.EXCLUDE_RESPONDENTS:
            overlap = excluded.intersection(decision.affected_respondent_refs)
            if overlap:
                raise QuantitativeQualityError("repeated exclusion")
            excluded.update(decision.affected_respondent_refs)
        if decision.action in {CleaningAction.SET_MISSING, CleaningAction.RECODE}:
            targets = {(ref, var) for ref in decision.affected_respondent_refs for var in decision.affected_variable_ids}
            if cells.intersection(targets):
                raise QuantitativeQualityError("conflicting cell transformations")
            cells.update(targets)


class CleaningEngine:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider

    def execute(self, *, parent: DatasetVersion, codebook: CodebookVersion, decision_set: CleaningDecisionSet) -> DatasetVersion | None:
        material = tuple(d for d in decision_set.decisions if d.material)
        if not material:
            return None
        if decision_set.approval_state is not ApprovalState.APPROVED:
            raise QuantitativeQualityError("material cleaning decision set is not approved")
        if decision_set.parent_version_id != parent.version_id or decision_set.parent_dataset_fingerprint != parent.dataset_fingerprint:
            raise QuantitativeQualityError("approved decision set is stale")
        rows = list(self._storage.get_parsed_rows(parent.version_id))
        refs = list(self._storage.get_respondent_lineage(parent.version_id))
        known_refs = set(refs)
        requested_refs = {
            ref for decision in material for ref in decision.affected_respondent_refs
        }
        unknown_refs = requested_refs - known_refs
        if unknown_refs:
            raise QuantitativeQualityError("cleaning references unknown respondents")
        index = {variable.variable_id: i for i, variable in enumerate(codebook.variables)}
        original_rows = tuple(rows)
        excluded: set[str] = set()
        for decision in material:
            if decision.action is CleaningAction.EXCLUDE_RESPONDENTS:
                excluded.update(decision.affected_respondent_refs)
                continue
            mapping = dict(decision.transformation)
            for row_i, ref in enumerate(refs):
                if ref not in decision.affected_respondent_refs:
                    continue
                mutable = list(rows[row_i])
                for variable_id in decision.affected_variable_ids:
                    if variable_id not in index:
                        raise QuantitativeQualityError("unknown cleaning variable")
                    if decision.action is CleaningAction.SET_MISSING:
                        mutable[index[variable_id]] = None
                    else:
                        old = mutable[index[variable_id]]
                        if "from" in mapping and old != mapping["from"]:
                            raise QuantitativeQualityError("material recode is a no-op")
                        mutable[index[variable_id]] = mapping.get("to")
                    rows[row_i] = tuple(mutable)
        retained = [(row, ref) for row, ref in zip(rows, refs) if ref not in excluded]
        new_rows = tuple(row for row, _ in retained)
        new_refs = tuple(ref for _, ref in retained)
        if new_rows == original_rows and not excluded:
            raise QuantitativeQualityError("material cleaning produced no change")
        data_fp = fingerprint_data(new_rows, digest_provider=self._digest)
        retained_fp = _digest(tuple(sorted(new_refs)), self._digest)
        excluded_fp = _digest(tuple(sorted(excluded)), self._digest)
        dataset_fp = _digest({"parent": parent.dataset_fingerprint, "decision_set": decision_set.fingerprint, "engine": ENGINE_VERSION, "schema": parent.schema_fingerprint, "codebook": parent.codebook_fingerprint, "data": data_fp, "retained": retained_fp, "excluded": excluded_fp}, self._digest)
        version_id = str(uuid5(NAMESPACE_URL, f"qb-cleaned:{dataset_fp}"))
        self._storage.put_parsed_rows(version_id, new_rows)
        self._storage.put_respondent_lineage(version_id, new_refs)
        self._storage.put_protected_respondent_bindings(
            version_id,
            self._storage.get_protected_respondent_bindings(parent.version_id),
        )
        child = replace(parent, version_id=version_id, version_kind=DatasetVersionKind.CLEANED, row_count=len(new_rows), data_fingerprint=data_fp, dataset_fingerprint=dataset_fp, storage_locator=f"memory-dataset://parsed/{version_id}", parent_version_id=parent.version_id, parent_dataset_fingerprint=parent.dataset_fingerprint, cleaning_decision_set_id=decision_set.decision_set_id, cleaning_decision_set_fingerprint=decision_set.fingerprint, cleaning_engine_version=ENGINE_VERSION, retained_respondent_set_fingerprint=retained_fp, excluded_respondent_set_fingerprint=excluded_fp)
        self._storage.put_manifest(child)
        return child


def reconcile_quality_runs(parent: QualityControlRun, current: QualityControlRun) -> tuple[IssueReconciliation, ...]:
    previous_by_rule = {item.rule_fingerprint: item for item in parent.issues}
    current_by_rule = {item.rule_fingerprint: item for item in current.issues}
    result: list[IssueReconciliation] = []
    for rule, old in previous_by_rule.items():
        if old.rule_id in current.not_evaluated_rule_ids:
            result.append(IssueReconciliation(old.issue_id, ReconciliationState.NOT_EVALUATED))
        elif rule not in current_by_rule:
            result.append(IssueReconciliation(old.issue_id, ReconciliationState.RESOLVED))
        elif old.affected_set_fingerprint == current_by_rule[rule].affected_set_fingerprint:
            result.append(IssueReconciliation(current_by_rule[rule].issue_id, ReconciliationState.REMAINS, old.issue_id))
        else:
            result.append(IssueReconciliation(old.issue_id, ReconciliationState.SUPERSEDED, current_by_rule[rule].issue_id))
            result.append(IssueReconciliation(current_by_rule[rule].issue_id, ReconciliationState.NEW, old.issue_id))
    for rule, issue in current_by_rule.items():
        if rule not in previous_by_rule:
            result.append(IssueReconciliation(issue.issue_id, ReconciliationState.NEW))
    return tuple(result)


def assess_dataset_quality(*, dataset: DatasetVersion, qc_run: QualityControlRun | None, manager_approved: bool, approval_fingerprint: str | None, digest_provider: DeterministicDigestProvider) -> DatasetQualityAssessment:
    if qc_run is None:
        state = DatasetQualityState.QC_PENDING
        current = False
    elif qc_run.dataset_fingerprint != dataset.dataset_fingerprint:
        state = DatasetQualityState.QC_PENDING
        current = False
    elif any(issue.severity == "BLOCKING" for issue in qc_run.issues):
        state = DatasetQualityState.QC_BLOCKED
        current = True
    elif qc_run.issues or qc_run.not_evaluated_rule_ids or not manager_approved:
        state = DatasetQualityState.QC_REVIEW_REQUIRED
        current = True
    else:
        if not approval_fingerprint:
            raise QuantitativeQualityError("QC approval requires fingerprint")
        state = DatasetQualityState.QC_APPROVED
        current = True
    fingerprint = _digest({"dataset": dataset.dataset_fingerprint, "qc": qc_run.fingerprint if qc_run else None, "state": state.value, "approval": approval_fingerprint, "current": current}, digest_provider)
    return DatasetQualityAssessment(dataset.version_id, dataset.dataset_fingerprint, qc_run.fingerprint if qc_run else None, state, approval_fingerprint, current, fingerprint)


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and value != value)
