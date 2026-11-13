"""Bounded arithmetic and authority checks used only by AnalysisService."""
from dataclasses import replace
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import re

from application.ports.analysis_ports import FindingCandidate
from application.analysis.provenance_validation import validate_finding_candidate
from application.evidence.temporal_scope import qualifying_evidence
from application.evidence.semantic_assignment import semantic_assignment
from domain.planning.derivation import InformationNeedKind


class DerivationRefused(ValueError):
    """Explicit methodological refusal, never a fabricated calculation."""


def same(a,b):
    return " ".join(str(a).replace("_"," ").casefold().split())==" ".join(str(b).replace("_"," ").casefold().split())


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
    values={}
    lineage=[]
    for evidence in inputs:
        data=evidence.metadata
        if not data.get("structured_table"):
            continue
        assignment=semantic_assignment(evidence)
        subject=design.research_subject
        if not assignment or subject is None or assignment.get("subject_fingerprint")!=subject.semantic_fingerprint or assignment.get("subject_id")!=subject.subject_id:
            raise DerivationRefused("unvalidated_numeric_semantics")
        if assignment.get("information_need_id") not in set(evidence.information_need_refs).intersection(need.depends_on_information_need_ids):
            raise DerivationRefused("numeric_semantic_dependency_mismatch")
        if not set(evidence.information_need_refs).intersection(need.depends_on_information_need_ids):
            raise DerivationRefused("numeric_input_not_owned_by_dependency")
        period=data.get("observation_period")
        if period not in spec.required_periods:
            continue
        source=source_repository.get_by_id(evidence.source_id)
        if source is None:
            raise DerivationRefused("numeric_source_missing")
        if design.id not in source.research_design_refs or evidence.workflow_run_id not in source.workflow_run_refs:
            raise DerivationRefused("numeric_source_authority_scope_mismatch")
        locator=evidence.source_locator.get("structured",{})
        if locator!=data.get("workbook_provenance") or locator.get("terminal_resource_key")!=source.terminal_resource_key or locator.get("extraction_revision")!=source.extraction_revision or locator.get("content_revision")!=source.content_revision or locator.get("raw_workbook_checksum")!=source.raw_content_checksum:
            raise DerivationRefused("numeric_source_revision_mismatch")
        rows=[r for r in source.metadata.get("structured_tables_v2",()) if r.get("sheet")==locator.get("sheet") and r.get("table_range")==locator.get("table_range") and r.get("row")==locator.get("row")]
        if len(rows)!=1 or rows[0].get("ambiguous_headers"):
            raise DerivationRefused("ambiguous_numeric_source")
        cells={c["cell"]:c for c in rows[0]["cells"]}
        cell=cells.get(locator.get("cell"),{})
        period_cell=cells.get(locator.get("period_cell"),{})
        if locator.get("header_checksum")!=rows[0].get("header_checksum") or evidence.source_excerpt!=rows[0].get("excerpt"):
            raise DerivationRefused("numeric_header_or_excerpt_mismatch")
        units=[c["value"] for c in cells.values() if c.get("header","").casefold() in {"unit","units","одиниця","одиниці"}]
        header_unit=re.search(r"\(([^)]+)\)\s*$",cell.get("header",""))
        if header_unit:
            units.append(header_unit[1])
        geographies=[c["value"] for c in cells.values() if c.get("header","").casefold() in {"geography","country","географія","країна"}]
        if not units or any(not same(u,spec.input_unit) for u in units) or not geographies or any(not same(g,spec.geography) for g in geographies):
            raise DerivationRefused("numeric_unit_or_geography_binding_invalid")
        number=Decimal(str(data.get("normalized_numeric_value","NaN")))
        header=re.sub(r"\s*\([^)]*\)\s*$","",cell.get("header",""))
        if not number.is_finite() or cell.get("formula") or period_cell.get("formula") or period_cell.get("value")!=period or cell.get("numeric_value") is None or Decimal(cell["numeric_value"])!=number or not same(header,spec.metric):
            raise DerivationRefused("numeric_cell_binding_invalid")
        if period in values and values[period]!=number:
            raise DerivationRefused("conflicting_values:"+period)
        values[period]=number
        lineage.append({"evidence_id":evidence.id,"source_id":source.id,"source_content_checksum":source.content_checksum,
            "terminal_resource_key":source.terminal_resource_key,"raw_content_checksum":source.raw_content_checksum,
            "raw_checksum_kind":source.raw_checksum_kind,"content_revision":source.content_revision,
            "extraction_revision":source.extraction_revision,"cell":locator["cell"],"period":period})
    if set(values)!=set(spec.required_periods):
        raise DerivationRefused("missing_required_observation")
    return values,lineage


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
