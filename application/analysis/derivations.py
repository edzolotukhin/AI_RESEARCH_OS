"""Bounded arithmetic and authority checks used only by AnalysisService."""
from dataclasses import replace
from decimal import Decimal, localcontext, ROUND_HALF_EVEN

from application.ports.analysis_ports import FindingCandidate
from application.analysis.provenance_validation import validate_finding_candidate
from application.evidence.temporal_scope import qualifying_evidence
from application.analysis.numeric_integrity import (
    NumericIntegrityError,
    NumericObservationRequirements,
    evaluate_numeric_series,
    same,
    validate_numeric_observation,
)
from domain.planning.derivation import InformationNeedKind


class DerivationRefused(ValueError):
    """Explicit methodological refusal, never a fabricated calculation."""


def dependency_authority(need, findings, evidence, *, design, project_id, workflow_run_id, allowed_runs, brief, source_repository):
    qualifying={e.id:e for e in qualifying_evidence(design=design,evidence=evidence,brief=brief,source_repository=source_repository)
                if e.project_id==project_id and e.research_design_id==design.id and e.workflow_run_id in allowed_runs}
    selected=[]
    for ref in need.depends_on_information_need_ids:
        members=[f for f in findings if ref in f.information_need_refs and f.project_id==project_id
            and f.workflow_run_id==workflow_run_id and f.research_design_id==design.id
            and f.metadata.get("validation_status")=="validated" and f.evidence_refs]
        if not members:
            raise DerivationRefused("missing_validated_dependency_finding:"+ref)
        for finding in members:
            if any(eid not in qualifying for eid in finding.evidence_refs):
                raise DerivationRefused("invalid_dependency_evidence_authority")
            selected.append(finding)
    evidence_ids={eid for f in selected for eid in f.evidence_refs}
    inputs=tuple(qualifying[eid] for eid in sorted(evidence_ids))
    if not inputs or len(inputs)>need.derivation.max_inputs or len(selected)>need.derivation.max_inputs:
        raise DerivationRefused("dependency_input_bound_or_empty")
    for item in inputs:
        if item.metadata.get("structured_table"):
            for field,expected in (("metric",need.derivation.metric),("unit",need.derivation.input_unit),("geography",need.derivation.geography)):
                if not same(item.metadata.get(field,""),expected):
                    raise DerivationRefused(field+"_mismatch")
    return tuple(sorted({f.id:f for f in selected}.values(),key=lambda f:f.id)),inputs


def observed_series(need, inputs, *, design, source_repository):
    spec=need.derivation
    subject=design.research_subject
    if subject is None:
        raise DerivationRefused("unvalidated_numeric_semantics")
    requirements=NumericObservationRequirements(
        allowed_information_need_ids=tuple(need.depends_on_information_need_ids),
        subject_id=subject.subject_id,
        subject_fingerprint=subject.semantic_fingerprint,
        research_design_id=design.id,
        allowed_workflow_run_ids=tuple(sorted({e.workflow_run_id for e in inputs})),
        metric=spec.metric,
        unit=spec.input_unit,
        geography=spec.geography,
        required_periods=tuple(spec.required_periods),
    )
    observations=[]
    for evidence in inputs:
        if not evidence.metadata.get("structured_table"):
            continue
        if evidence.metadata.get("observation_period") not in spec.required_periods:
            continue
        source=source_repository.get_by_id(evidence.source_id)
        try:
            observations.append(validate_numeric_observation(
                evidence,source,requirements,temporal_eligible=True,
            ))
        except NumericIntegrityError as exc:
            raise DerivationRefused(exc.code) from exc
    series=evaluate_numeric_series(observations)
    if series.conflicting_periods:
        raise DerivationRefused("conflicting_values:"+series.conflicting_periods[0])
    if set(series.values)!=set(spec.required_periods):
        raise DerivationRefused("missing_required_observation")
    lineage=[{"evidence_id":item.evidence_id,"source_id":item.source_id,
        "source_content_checksum":item.source_content_checksum,
        "terminal_resource_key":item.terminal_resource_key,
        "raw_content_checksum":item.raw_content_checksum,
        "raw_checksum_kind":item.raw_checksum_kind,"content_revision":item.content_revision,
        "extraction_revision":item.extraction_revision,"cell":item.cell,"period":item.period}
        for period in spec.required_periods for item in series.observations_by_period[period]]
    return dict(series.values),lineage


def calculate_candidates(need, inputs, dependencies, *, design, project_id, workflow_run_id, allowed_runs, source_repository):
    spec=need.derivation
    if any(next(n for n in design.information_needs if n.id==ref).kind!=InformationNeedKind.ACQUIRED for ref in need.depends_on_information_need_ids):
        raise DerivationRefused("calculation_requires_acquired_observation_series")
    values,lineage=observed_series(need,inputs,design=design,source_repository=source_repository)
    periods=spec.required_periods
    pairs=list(zip(periods,periods[1:])) if spec.operation_type.value.startswith("YEAR_OVER_YEAR") else [(periods[0],periods[-1])]
    result=[]
    for start,end in pairs:
        percentage=spec.operation_type.value.endswith("PERCENT_CHANGE")
        with localcontext() as ctx:
            ctx.prec=34
            if percentage and values[start]==0:
                raise DerivationRefused("zero_denominator")
            raw=(values[end]-values[start])/values[start]*100 if percentage else values[end]-values[start]
            rounded=raw.quantize(Decimal(1).scaleb(-spec.decimal_places),rounding=ROUND_HALF_EVEN)
        unit="percent" if percentage else spec.input_unit
        formula="(end - start) / start * 100" if percentage else "end - start"
        metadata={"version":spec.version,"operation_type":spec.operation_type.value,"contract":spec.to_dict(),
            "dependency_information_need_ids":list(need.depends_on_information_need_ids),
            "dependency_finding_ids":[f.id for f in dependencies],"input_evidence_ids":[e.id for e in inputs],
            "parameters":{"from_period":start,"to_period":end},"input_values":{p:str(values[p]) for p in periods},
            "preconditions":{"qualified_authority":True,"compatible_metric":True,"compatible_unit":True,"compatible_geography":True,"complete_periods":True,"no_conflicting_values":True},
            "formula":formula,"raw_result":str(raw),"rounded_result":str(rounded),"unit":unit,
            "metric":spec.metric,"geography":spec.geography,"rounding":{"decimal_places":spec.decimal_places,"mode":"ROUND_HALF_EVEN","precision":34},
            "source_revision_lineage":lineage,"validation_method":"deterministic-recompute-v1","validation_status":"validated"}
        candidate=FindingCandidate(statement=f"{spec.metric}: {end} versus {start}, {spec.operation_type.value.lower()} = {rounded} {unit} ({spec.geography}).",
            rationale=f"Reproduced from qualified observations using {formula}.",evidence_refs=tuple(e.id for e in inputs),
            research_question_refs=(need.research_question_id,),information_need_refs=(need.id,),finding_type="trend",metadata={"derivation":metadata})
        result.append(validate_finding_candidate(candidate,evidence_by_id={e.id:e for e in inputs},project_id=project_id,
            workflow_run_id=workflow_run_id,research_design_id=design.id,design=design,allowed_workflow_run_ids=allowed_runs))
    return result


def validate_deterministic_derivation(candidate, need, inputs, dependencies, **scope):
    brief=scope.pop("brief")
    checked_dependencies,checked_inputs=dependency_authority(need,dependencies,inputs,brief=brief,**scope)
    reproduced=calculate_candidates(need,checked_inputs,checked_dependencies,**scope)
    if not any(candidate==expected for expected in reproduced):
        raise DerivationRefused("deterministic_reproduction_failed")
    return candidate
