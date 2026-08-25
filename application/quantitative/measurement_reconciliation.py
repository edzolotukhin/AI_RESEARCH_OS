from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, replace
from decimal import Decimal, InvalidOperation

from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.dataset import PiiClassification, VariableRole, VariableType
from domain.quantitative.measurement_reconciliation import *
from domain.quantitative.questionnaire_authority import RoutingActionType, RoutingConditionKind
from domain.quantitative.quality import QuestionnaireSnapshot, RoutingConsequence, RoutingRule

METHOD = "RB_EXACT_V1"
DATASET_ONLY_LIMITATION = "No approved Questionnaire-Codebook reconciliation authority is present."
_BLOCKED = {ReconciliationMatchStatus.MISSING_IN_DATA, ReconciliationMatchStatus.INCOMPATIBLE_IN_DATA, ReconciliationMatchStatus.TRANSFORMATION_REQUIRED}

class QuantitativeMeasurementReconciliationError(ValueError): pass

def _text(value): return " ".join(unicodedata.normalize("NFKC", str(value)).strip().split()).casefold()
def _code(value):
    text=str(value).strip()
    if re.fullmatch(r"[+-]?(?:0|[1-9]\\d*)(?:\\.\\d+)?",text):
        try:
            number=Decimal(text)
            if number.is_finite():
                rendered=format(number.normalize(),"f")
                return "0" if rendered == "-0" else rendered
        except InvalidOperation:
            pass
    return text

class QuantitativeMeasurementReconciliationService:
    def __init__(self, *, repository, questionnaire_service, digest_provider):
        self._repository, self._questionnaires, self._digest = repository, questionnaire_service, digest_provider

    def create(self, *, reconciliation_id, version_id, project_id, run_id, dataset, codebook,
               created_at, created_by, reviewed_mappings=(), parent_version_id=None):
        questionnaire = self._questionnaires.resolve_current_approved(project_id=project_id, run_id=run_id)
        schema = self._questionnaires.derive_expected_measurement_schema(questionnaire.version_id, project_id=project_id)
        if dataset.project_id != project_id or dataset.run_id != run_id or dataset.codebook_version_id != codebook.codebook_version_id:
            raise QuantitativeMeasurementReconciliationError("Dataset/Codebook is unavailable for project/run")
        if (dataset.codebook_fingerprint != codebook.fingerprint or questionnaire.expected_measurement_schema_fingerprint != schema.fingerprint):
            raise QuantitativeMeasurementReconciliationError("Questionnaire, Dataset, or Codebook authority is stale")
        decisions = {item.expected_variable_id: item for item in reviewed_mappings}
        if len(decisions) != len(tuple(reviewed_mappings)): raise QuantitativeMeasurementReconciliationError("duplicate reviewed mapping decision")
        actual_by_name = {}
        for item in codebook.variables: actual_by_name.setdefault(_text(item.name), []).append(item)
        outcomes, used = [], set()
        for expected in sorted(schema.variables, key=lambda item: item.expected_variable_id):
            decision = decisions.get(expected.expected_variable_id)
            candidates = actual_by_name.get(_text(expected.variable_name), [])
            actual = None
            if decision:
                actual = next((item for item in codebook.variables if item.variable_id == decision.actual_variable_id), None)
                self._validate_decision(decision, expected, actual)
            elif len(candidates) == 1: actual = candidates[0]
            elif len(candidates) > 1: raise QuantitativeMeasurementReconciliationError("ambiguous variable mapping")
            outcome = self._match(expected, actual, decision)
            if actual:
                if actual.variable_id in used: raise QuantitativeMeasurementReconciliationError("duplicate actual target mapping")
                used.add(actual.variable_id)
            outcomes.append(outcome)
        extras = tuple(self._extra(item) for item in sorted(codebook.variables, key=lambda x: x.variable_id) if item.variable_id not in used)
        blocked = any(item.status in _BLOCKED for item in outcomes)
        review = any(item.status in {ReconciliationMatchStatus.REQUIRES_REVIEW, ReconciliationMatchStatus.COMPATIBLE_MATCH} for item in outcomes)
        status = ReconciliationOverallStatus.BLOCKED if blocked else (ReconciliationOverallStatus.REVIEW_REQUIRED if review else ReconciliationOverallStatus.DETERMINISTICALLY_ACCEPTED)
        lifecycle = ReconciliationLifecycle.DRAFT if review or blocked else ReconciliationLifecycle.APPROVED
        sequence = 1
        if parent_version_id:
            parent = self._require(parent_version_id, project_id)
            sequence = parent.version_sequence + 1
        base = dict(reconciliation_id=reconciliation_id, version_id=version_id, version_sequence=sequence, project_id=project_id, methodology="QUANTITATIVE",
            questionnaire_id=questionnaire.questionnaire_id, questionnaire_version_id=questionnaire.version_id, questionnaire_fingerprint=questionnaire.fingerprint,
            expected_measurement_schema_fingerprint=schema.fingerprint, dataset_version_id=dataset.version_id, dataset_fingerprint=dataset.dataset_fingerprint,
            data_fingerprint=dataset.data_fingerprint, schema_fingerprint=dataset.schema_fingerprint, codebook_version_id=codebook.codebook_version_id,
            codebook_fingerprint=codebook.fingerprint, reconciliation_method_version=METHOD, variable_outcomes=tuple(outcomes), imported_extras=extras,
            reviewed_mapping_decision_ids=tuple(sorted(item.decision_id for item in reviewed_mappings)), required_transformation_references=tuple(sorted(filter(None, (item.transformation_reference for item in outcomes)))),
            data_availability_manifest_id=f"{version_id}:availability", data_availability_manifest_fingerprint="", questionnaire_snapshot_id=None,
            questionnaire_snapshot_fingerprint=None, overall_status=status, lifecycle_status=lifecycle, parent_version_id=parent_version_id,
            approval_reference=None, fingerprint="", created_at=created_at, created_by=created_by)
        fingerprint_payload = {**base, "variable_outcomes": tuple(asdict(item) for item in outcomes), "imported_extras": tuple(asdict(item) for item in extras)}
        fingerprint = canonical_digest({"contract":"RB_RECONCILIATION_V1", **fingerprint_payload}, digest_provider=self._digest)
        value = QuantitativeMeasurementReconciliationVersion(**{**base, "fingerprint":fingerprint})
        availability = self._availability(value, questionnaire)
        value = replace(value, data_availability_manifest_fingerprint=availability.fingerprint)
        if value.lifecycle_status is ReconciliationLifecycle.APPROVED:
            snapshot = self._snapshot(value, questionnaire, codebook)
            if snapshot: value = replace(value, questionnaire_snapshot_id=snapshot.snapshot_id, questionnaire_snapshot_fingerprint=snapshot.fingerprint)
        for item in reviewed_mappings: self._repository.save_mapping_decision(item, project_id=project_id, run_id=run_id)
        self._repository.save_reconciliation(value, run_id=run_id); self._repository.save_availability(availability, run_id=run_id)
        if value.questionnaire_snapshot_id: self._repository.save_snapshot(snapshot, project_id=project_id, run_id=run_id, parent_id=value.version_id)
        return value

    def approve(self, version_id, *, project_id, run_id, approval_id, expected_fingerprint, actor_id, decided_at, rationale, new_version_id=None, dataset=None, codebook=None):
        current = self._require(version_id, project_id)
        if current.fingerprint != expected_fingerprint: raise QuantitativeMeasurementReconciliationError("reconciliation approval fingerprint is stale")
        if current.overall_status is ReconciliationOverallStatus.BLOCKED: raise QuantitativeMeasurementReconciliationError("blocked reconciliation cannot be approved")
        if not current.reviewed_mapping_decision_ids: return current
        for outcome in current.variable_outcomes:
            if outcome.status is ReconciliationMatchStatus.REQUIRES_REVIEW and not outcome.reviewer_decision_reference: raise QuantitativeMeasurementReconciliationError("reviewed mapping is missing approval authority")
        rationale = " ".join(rationale.split())
        if not rationale: raise QuantitativeMeasurementReconciliationError("approval rationale is required")
        approved = replace(current, version_id=new_version_id or f"{version_id}:approved", version_sequence=current.version_sequence+1, parent_version_id=current.version_id, data_availability_manifest_id=(new_version_id or (version_id + ":approved")) + ":availability", data_availability_manifest_fingerprint="", questionnaire_snapshot_id=None, questionnaire_snapshot_fingerprint=None, overall_status=ReconciliationOverallStatus.APPROVED_WITH_MAPPINGS, lifecycle_status=ReconciliationLifecycle.APPROVED, approval_reference=approval_id, created_at=decided_at, created_by=actor_id)
        approved_payload={**approved.__dict__, "fingerprint":"", "variable_outcomes":tuple(asdict(item) for item in approved.variable_outcomes), "imported_extras":tuple(asdict(item) for item in approved.imported_extras)}
        approved=replace(approved,fingerprint=canonical_digest({"contract":"RB_RECONCILIATION_APPROVED_V1",**approved_payload},digest_provider=self._digest))
        payload={"contract":"RB_APPROVAL_V1","version":approved.version_id,"fingerprint":approved.fingerprint,"questionnaire":current.questionnaire_fingerprint,"expected":current.expected_measurement_schema_fingerprint,"dataset":current.dataset_fingerprint,"data":current.data_fingerprint,"schema":current.schema_fingerprint,"codebook":current.codebook_fingerprint,"actor":actor_id,"time":decided_at,"rationale":rationale}
        approval=QuantitativeMeasurementReconciliationApproval(approval_id,project_id,"QUANTITATIVE",approved.version_id,approved.fingerprint,current.questionnaire_fingerprint,current.expected_measurement_schema_fingerprint,current.dataset_fingerprint,current.data_fingerprint,current.schema_fingerprint,current.codebook_fingerprint,actor_id,decided_at,ReconciliationApprovalDecision.APPROVED,rationale,canonical_digest(payload,digest_provider=self._digest))
        if dataset is not None or codebook is not None:
            if dataset is None or codebook is None or (approved.dataset_version_id, approved.dataset_fingerprint, approved.codebook_version_id, approved.codebook_fingerprint) != (dataset.version_id, dataset.dataset_fingerprint, codebook.codebook_version_id, codebook.fingerprint): raise QuantitativeMeasurementReconciliationError("approved reconciliation Dataset/Codebook is stale")
            questionnaire=self._questionnaires.resolve_current_approved(project_id=project_id,run_id=run_id)
            availability=self._availability(approved,questionnaire); approved=replace(approved,data_availability_manifest_fingerprint=availability.fingerprint)
            snapshot=self._snapshot(approved,questionnaire,codebook)
            if snapshot: approved=replace(approved,questionnaire_snapshot_id=snapshot.snapshot_id,questionnaire_snapshot_fingerprint=snapshot.fingerprint)
            self._repository.save_availability(availability,run_id=run_id)
            if snapshot: self._repository.save_snapshot(snapshot,project_id=project_id,run_id=run_id,parent_id=approved.version_id)
        self._repository.save_reconciliation(approved, run_id=run_id); self._repository.save_approval(approval, run_id=run_id)
        return approved

    def resolve_current_accepted(self, *, project_id, run_id, dataset, codebook):
        values=self._repository.list_reconciliations(project_id=project_id, run_id=run_id)
        if not values: raise QuantitativeMeasurementReconciliationError("no current accepted reconciliation")
        value=values[-1]
        questionnaire=self._questionnaires.resolve_current_approved(project_id=project_id, run_id=run_id)
        if questionnaire.version_id != value.questionnaire_version_id or questionnaire.fingerprint != value.questionnaire_fingerprint: raise QuantitativeMeasurementReconciliationError("reconciliation is stale")
        if value.lifecycle_status is not ReconciliationLifecycle.APPROVED: raise QuantitativeMeasurementReconciliationError("reconciliation is not approved")
        if (value.dataset_version_id,value.dataset_fingerprint,value.data_fingerprint,value.schema_fingerprint,value.codebook_version_id,value.codebook_fingerprint)!=(dataset.version_id,dataset.dataset_fingerprint,dataset.data_fingerprint,dataset.schema_fingerprint,codebook.codebook_version_id,codebook.fingerprint): raise QuantitativeMeasurementReconciliationError("reconciliation is stale")
        if value.approval_reference:
            approval=self._repository.get_approval(value.approval_reference,project_id=project_id)
            if approval is None or approval.reconciliation_fingerprint != value.fingerprint: raise QuantitativeMeasurementReconciliationError("reconciliation approval is stale")
        return value

    def accepted_projection(self, *, project_id, run_id, dataset, codebook):
        value=self.resolve_current_accepted(project_id=project_id,run_id=run_id,dataset=dataset,codebook=codebook)
        availability=self._repository.get_availability(value.data_availability_manifest_id,project_id=project_id)
        if availability is None or availability.fingerprint != value.data_availability_manifest_fingerprint: raise QuantitativeMeasurementReconciliationError("data availability authority is missing or stale")
        usable={ReconciliationMatchStatus.EXACT_MATCH,ReconciliationMatchStatus.COMPATIBLE_MATCH}
        return ApprovedMeasurementReconciliationProjection(value.version_id,value.fingerprint,value.questionnaire_version_id,value.questionnaire_fingerprint,value.expected_measurement_schema_fingerprint,value.dataset_version_id,value.dataset_fingerprint,value.codebook_version_id,value.codebook_fingerprint,tuple((x.expected_variable_id,x.actual_variable_id or "",x.actual_variable_fingerprint or "",x.status.value) for x in value.variable_outcomes if x.status in usable),tuple((x.requirement_id,x.status.value) for x in availability.requirements),value.questionnaire_snapshot_id,value.questionnaire_snapshot_fingerprint,tuple(r for x in value.variable_outcomes for r in x.reasons if x.status not in usable))

    def resolve_dataset_only(self, *, authority_id, project_id, run_id):
        payload={"contract":"RB_DATASET_ONLY_V1","authority_id":authority_id,"project_id":project_id,"run_id":run_id,"status":"NO_QUESTIONNAIRE_RECONCILIATION_AUTHORITY"}
        value=DatasetOnlyReconciliationAuthority(authority_id,project_id,run_id,"NO_QUESTIONNAIRE_RECONCILIATION_AUTHORITY",DATASET_ONLY_LIMITATION,canonical_digest(payload,digest_provider=self._digest)); self._repository.save_dataset_only(value); return value

    def _validate_decision(self, decision, expected, actual):
        if actual is None or decision.expected_variable_fingerprint != expected.fingerprint or decision.actual_variable_fingerprint != actual.fingerprint: raise QuantitativeMeasurementReconciliationError("reviewed mapping is stale or references unknown variable")
        if not " ".join(decision.rationale.split()): raise QuantitativeMeasurementReconciliationError("reviewed mapping rationale is required")

    def _match(self, expected, actual, decision):
        status=ReconciliationMatchStatus.EXACT_MATCH; reasons=[]
        if actual is None: status=ReconciliationMatchStatus.MISSING_IN_DATA; reasons=["expected variable is absent"]
        elif expected.pii_expectation is PiiClassification.NONE and actual.pii_classification is not PiiClassification.NONE: status=ReconciliationMatchStatus.INCOMPATIBLE_IN_DATA; reasons=["PII classification cannot be downgraded"]
        elif actual.variable_type != expected.variable_type: status=ReconciliationMatchStatus.INCOMPATIBLE_IN_DATA; reasons=["variable type differs"]
        elif actual.role != expected.analytical_role: status=ReconciliationMatchStatus.COMPATIBLE_MATCH if decision else ReconciliationMatchStatus.REQUIRES_REVIEW; reasons=["variable role requires reviewed authority"]
        elif _text(actual.measurement_level) != _text(expected.measurement_level): status=ReconciliationMatchStatus.INCOMPATIBLE_IN_DATA; reasons=["measurement level differs"]
        else:
            expected_codes={_code(k):_text(v) for k,v in expected.value_labels}; actual_codes={_code(k):_text(v) for k,v in actual.value_labels}
            if expected_codes != actual_codes:
                reversed_scale = expected.ordinal_ordering and set(expected_codes)==set(actual_codes) and [actual_codes.get(x) for x in expected.ordinal_ordering] == list(reversed([expected_codes.get(x) for x in expected.ordinal_ordering]))
                status=ReconciliationMatchStatus.TRANSFORMATION_REQUIRED if reversed_scale else (ReconciliationMatchStatus.COMPATIBLE_MATCH if decision and decision.category_code_mapping else ReconciliationMatchStatus.REQUIRES_REVIEW); reasons=["category/code semantics differ"]
            expected_missing={_code(x.code):_text(x.semantic) for x in expected.missing_value_rules}; actual_missing={_code(x.value if x.value is not None else (x.low if x.low == x.high else f"{x.low}:{x.high}")):_text(x.kind) for x in actual.missing_rules}
            if expected_missing != actual_missing: status=ReconciliationMatchStatus.COMPATIBLE_MATCH if decision and decision.missing_semantic_mapping else ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("missing-value semantics differ")
            if expected.multiple_response_set_id and actual.multiple_response_set != expected.multiple_response_set_id: status=ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("multiple-response identity unavailable")
            if expected.matrix_group_id and not decision: status=ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("matrix identity unavailable")
            if expected.semantic_hooks and tuple(sorted(expected.semantic_hooks)) != tuple(sorted(actual.semantic_hooks)): status=ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("semantic hook differs")
            if _text(actual.name) != _text(expected.variable_name): status=ReconciliationMatchStatus.COMPATIBLE_MATCH if decision else ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("variable rename requires review")
            provenance=dict(actual.metadata_provenance)
            if provenance.get("role") == "HEURISTIC_INFERRED" or provenance.get("pii") == "HEURISTIC_INFERRED": status=ReconciliationMatchStatus.COMPATIBLE_MATCH if decision else ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("identity-critical metadata is heuristic")
            if expected.weighting_control_eligible and provenance.get("role") not in {"SOURCE_DECLARED", "EXPLICITLY_RESOLVED"}: status=ReconciliationMatchStatus.COMPATIBLE_MATCH if decision else ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("weighting eligibility is unproven")
            if (expected.ordinal_ordering or expected.analytical_scoring) and not (decision and decision.scale_mapping): status=ReconciliationMatchStatus.REQUIRES_REVIEW; reasons.append("ordinal order or analytical scoring is unproven")
        payload={"contract":"RB_MAPPING_V1","expected":expected.fingerprint,"actual":getattr(actual,"fingerprint",None),"status":status.value,"decision":getattr(decision,"fingerprint",None),"reasons":sorted(set(reasons))}
        return MeasurementVariableReconciliation(f"map:{expected.expected_variable_id}",expected.expected_variable_id,expected.fingerprint,expected.source_question_id,expected.source_option_id,expected.matrix_row_id,getattr(actual,"variable_id",None),getattr(actual,"fingerprint",None),status,getattr(decision,"category_code_mapping",()),getattr(decision,"missing_semantic_mapping",()),getattr(decision,"scale_mapping",()),getattr(decision,"mr_matrix_mapping",()),None,getattr(decision,"decision_id",None),tuple(sorted(set(reasons))),canonical_digest(payload,digest_provider=self._digest))

    def _extra(self, actual):
        if actual.pii_classification is not PiiClassification.NONE or actual.role is VariableRole.PII: status=ImportedExtraStatus.EXTRA_PII_RESTRICTED
        elif actual.role is VariableRole.TECHNICAL_ID: status=ImportedExtraStatus.EXTRA_TECHNICAL
        elif actual.analytically_eligible: status=ImportedExtraStatus.EXTRA_ANALYTICAL_REVIEW_REQUIRED
        else: status=ImportedExtraStatus.EXTRA_SAFE_UNMAPPED
        return ImportedVariableClassification(actual.variable_id,actual.fingerprint,status,"not consumed by expected schema",canonical_digest({"contract":"RB_EXTRA_V1","actual":actual.fingerprint,"status":status.value},digest_provider=self._digest))

    def _availability(self, value, questionnaire):
        by_expected={x.expected_variable_id:x for x in value.variable_outcomes}; entries=[]
        for question in questionnaire.questions:
            if not question.analytical_requirement_ids: continue
            ids=tuple(x.expected_variable_id for x in question.expected_variable_bindings); mapped=[by_expected[x] for x in ids if x in by_expected]
            if mapped and all(x.status in {ReconciliationMatchStatus.EXACT_MATCH,ReconciliationMatchStatus.COMPATIBLE_MATCH} for x in mapped): status=DataAvailabilityStatus.DATA_MEASUREMENT_AVAILABLE
            elif any(x.status is ReconciliationMatchStatus.TRANSFORMATION_REQUIRED for x in mapped): status=DataAvailabilityStatus.TRANSFORMATION_REQUIRED
            elif any(x.status is ReconciliationMatchStatus.INCOMPATIBLE_IN_DATA for x in mapped): status=DataAvailabilityStatus.INCOMPATIBLE_IN_DATA
            elif mapped and any(x.actual_variable_id for x in mapped): status=DataAvailabilityStatus.PARTIALLY_AVAILABLE
            else: status=DataAvailabilityStatus.MISSING_IN_DATA
            for req in question.analytical_requirement_ids: entries.append(RequirementDataAvailability(req,status,ids,tuple(x.actual_variable_id for x in mapped if x.actual_variable_id),tuple(r for x in mapped for r in x.reasons)))
        payload={"contract":"RB_AVAILABILITY_V1","reconciliation":value.fingerprint,"requirements":[asdict(x) for x in entries]}
        return MeasurementDataAvailabilityManifest(value.data_availability_manifest_id,value.project_id,value.questionnaire_version_id,value.questionnaire_fingerprint,value.expected_measurement_schema_fingerprint,value.dataset_version_id,value.dataset_fingerprint,value.codebook_version_id,value.codebook_fingerprint,value.fingerprint,tuple(entries),canonical_digest(payload,digest_provider=self._digest))

    def _snapshot(self, value, questionnaire, codebook):
        actual={x.actual_variable_id:codebook.variable_by_id(x.actual_variable_id) for x in value.variable_outcomes if x.actual_variable_id and x.status in {ReconciliationMatchStatus.EXACT_MATCH, ReconciliationMatchStatus.COMPATIBLE_MATCH}}
        bindings=tuple(sorted((x.source_question_id,x.actual_variable_id) for x in value.variable_outcomes if x.actual_variable_id in actual))
        domains=tuple(sorted((x.variable_id,tuple(k for k,_ in x.value_labels)) for x in actual.values() if x.value_labels))
        required_questions={q.question_id for q in questionnaire.questions if q.response_required}; required=tuple(sorted(actual_id for qid,actual_id in bindings if qid in required_questions))
        question_actual={question:variable for question,variable in bindings}
        outcome_by_question={item.source_question_id:item for item in value.variable_outcomes if item.actual_variable_id in actual}
        option_codes={}
        for question in questionnaire.questions:
            outcome=outcome_by_question.get(question.question_id)
            if not outcome: continue
            reviewed_codes=dict(outcome.category_code_mapping)
            actual_codes={_code(code):code for code,_ in actual[outcome.actual_variable_id].value_labels}
            for option in question.answer_options:
                mapped=reviewed_codes.get(_code(option.dataset_value_code),option.dataset_value_code)
                option_codes[(question.question_id,option.option_id)]=actual_codes.get(_code(mapped),mapped)
        routing=[]
        for rule in questionnaire.routing_rules:
            if rule.condition.kind not in {RoutingConditionKind.EQUALS_OPTION,RoutingConditionKind.IN_OPTION_SET,RoutingConditionKind.SELECTED} or rule.action.action_type is not RoutingActionType.SKIP_QUESTION or not rule.action.target_id: return None
            antecedent=question_actual.get(rule.source_question_id); target=question_actual.get(rule.action.target_id)
            values=tuple(option_codes.get((rule.source_question_id,item)) for item in rule.condition.option_ids)
            if not antecedent or not target or not values or any(item is None for item in values): return None
            rule_payload={"id":rule.rule_id,"source":antecedent,"values":values,"target":target,"consequence":"SKIPPED","reconciliation":value.fingerprint}
            routing.append(RoutingRule(rule.rule_id,"rb-1",antecedent,values,target,RoutingConsequence.SKIPPED,canonical_digest(rule_payload,digest_provider=self._digest)))
        payload={"contract":"RB_QC_SNAPSHOT_V1","questionnaire":value.questionnaire_fingerprint,"reconciliation":value.fingerprint,"codebook":codebook.fingerprint,"bindings":bindings,"domains":domains,"required":required,"routing":tuple(x.fingerprint for x in routing)}
        fp=canonical_digest(payload,digest_provider=self._digest)
        return QuestionnaireSnapshot(f"{value.version_id}:questionnaire-snapshot","rb-1",codebook.codebook_version_id,bindings,domains,required,tuple(routing),None,next((x.variable_id for x in codebook.variables if x.role is VariableRole.TECHNICAL_ID),None),fp)

    def _require(self, version_id, project_id):
        value=self._repository.get_reconciliation(version_id,project_id=project_id)
        if value is None or value.project_id != project_id or value.methodology != "QUANTITATIVE": raise QuantitativeMeasurementReconciliationError("reconciliation unavailable for project")
        return value
