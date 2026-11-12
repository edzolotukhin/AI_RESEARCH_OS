"""Kind-aware projection around existing sufficiency; never generates Findings."""
from dataclasses import replace
from domain.planning.derivation import InformationNeedKind as Kind, validate_dependency_graph
from domain.research_quality.information_need_assessment import InformationNeedAssessment
from domain.research_quality.sufficiency_status import SufficiencyStatus as Status
from domain.research_quality.gap_type import GapType
from application.analysis.derivations import observed_series, DerivationRefused, same
from application.research_quality.readiness_aggregation import build_research_readiness_assessment, build_research_readiness_result


def classified(design):
    return any(n.kind!=Kind.ACQUIRED for n in design.information_needs)


def acquired_view(design):
    return replace(design,information_needs=tuple(n for n in design.information_needs if n.kind==Kind.ACQUIRED)) if classified(design) else design


def output_obligations(design):
    return tuple({"version":"output-obligation-v1","information_need_id":n.id,"research_question_id":n.research_question_id,
        "description":n.description,"dependency_information_need_ids":list(n.depends_on_information_need_ids),
        "status":"deferred","verification_stage":"report_finalization","satisfied":False}
        for n in design.information_needs if n.kind==Kind.OUTPUT)


def align_readiness(design,evidence,result,source_repository):
    if not classified(design):
        return result
    order=validate_dependency_graph(design)
    previous={n.information_need_id:n for rq in result.research_question_assessments for n in rq.information_need_assessments}
    current={}
    leaf_ids={}
    for need in order:
        if need.kind==Kind.ACQUIRED:
            assessment=previous[need.id]
            items=[e for e in evidence if need.id in e.information_need_refs and e.research_design_id==design.id]
            issues=[]
            if not items:
                issues.append("missing_qualifying_evidence")
            if not assessment.assessment_current:
                issues.append("assessment_not_current")
            if assessment.contradictions:
                issues.append("conflicting_evidence")
            coverage=need.evidence_coverage
            geography=need.geography or (coverage.geography if coverage else "")
            if geography and (not items or any(not same(e.metadata.get("geography",""),geography) for e in items)):
                issues.append("geography_unresolved_or_conflicting")
            if coverage:
                if coverage.required_periods and not set(coverage.required_periods)<={e.metadata.get("observation_period") for e in items}:
                    issues.append("unavailable_required_observations")
                if coverage.required_metric and (not items or any(not same(e.metadata.get("metric",""),coverage.required_metric) for e in items)):
                    issues.append("metric_unresolved_or_conflicting")
                if need.geography and coverage.geography and not same(need.geography,coverage.geography):
                    issues.append("conflicting_geography_contract")
                if coverage.minimum_independent_sources>assessment.independent_source_count:
                    issues.append("insufficient_source_diversity")
                if coverage.required_observations:
                    observations={str(v) for e in items for v in e.metadata.get("observation_keys",())}
                    if not set(coverage.required_observations)<=observations:
                        issues.append("unavailable_required_observations")
            if need.evidence_expectation and not set(need.evidence_expectation.required_aspects)<=set(assessment.supported_aspects):
                issues.append("missing_required_aspects")
            diagnostics={"version":"analysis-kind-readiness-v1","status":"ready" if not issues and assessment.status==Status.SUFFICIENT and assessment.assessment_current else "not_ready",
                "qualifying_evidence_ids":sorted(e.id for e in items),"reasons":sorted(set(issues))}
            if issues and assessment.evidence_count:
                assessment=replace(assessment,status=Status.INSUFFICIENT,reason=";".join(diagnostics["reasons"]),
                    gap_types=tuple(dict.fromkeys((*assessment.gap_types,GapType.INSUFFICIENT_DEPTH))))
            current[need.id]=replace(assessment,prerequisite_diagnostics=diagnostics)
            leaf_ids[need.id]={need.id}
            continue
        if need.kind==Kind.OUTPUT:
            obligation=next(o for o in output_obligations(design) if o["information_need_id"]==need.id)
            current[need.id]=InformationNeedAssessment(need.id,need.research_question_id,Status.SUFFICIENT,
                reason="Output obligation deferred to Report/Finalization; no external Evidence required.",
                information_need_kind="OUTPUT",qualification_basis="output_deferred",prerequisite_diagnostics=obligation,
                evidence_status="not_applicable",search_status="not_applicable",analysis_eligible=False)
            leaf_ids[need.id]=set()
            continue
        missing=[ref for ref in need.depends_on_information_need_ids if current[ref].status!=Status.SUFFICIENT or not current[ref].assessment_current]
        leaves=set().union(*(leaf_ids[ref] for ref in need.depends_on_information_need_ids))
        leaf_ids[need.id]=leaves
        inputs=tuple(e for e in evidence if e.research_design_id==design.id and set(e.information_need_refs).intersection(leaves))
        diagnostics={"version":"analysis-kind-readiness-v1","status":"ready","dependency_information_need_ids":list(need.depends_on_information_need_ids),
            "missing_dependencies":missing,"input_evidence_ids":sorted(e.id for e in inputs),"contract":need.derivation.to_dict(),"reasons":[]}
        try:
            if missing:
                raise DerivationRefused("dependencies_not_ready")
            if not inputs or len(inputs)>need.derivation.max_inputs:
                raise DerivationRefused("missing_or_bounded_input_authority")
            for item in inputs:
                if item.metadata.get("structured_table"):
                    for field,expected in (("metric",need.derivation.metric),("unit",need.derivation.input_unit),("geography",need.derivation.geography)):
                        if not same(item.metadata.get(field,""),expected):
                            raise DerivationRefused(field+"_mismatch")
            if need.derivation.operation_type.deterministic:
                if source_repository is None:
                    raise DerivationRefused("source_repository_unavailable")
                if any(next(n for n in design.information_needs if n.id==ref).kind!=Kind.ACQUIRED for ref in need.depends_on_information_need_ids):
                    raise DerivationRefused("calculation_requires_acquired_observation_series")
                values,_=observed_series(need,inputs,design=design,source_repository=source_repository)
                starts=need.derivation.required_periods[:-1] if need.derivation.operation_type.value.startswith("YEAR_OVER_YEAR") else need.derivation.required_periods[:1]
                if need.derivation.operation_type.value.endswith("PERCENT_CHANGE") and any(values[p]==0 for p in starts):
                    raise DerivationRefused("zero_denominator")
            elif need.derivation.required_periods and not set(need.derivation.required_periods)<={e.metadata.get("observation_period") for e in inputs}:
                raise DerivationRefused("unavailable_required_observations")
            if need.derivation.operation_type.value=="CROSS_SOURCE_COMPARISON":
                if source_repository is None or len({source_repository.get_by_id(e.source_id).terminal_resource_key for e in inputs})<2 or len({source_repository.get_by_id(e.source_id).raw_content_checksum for e in inputs})<2:
                    raise DerivationRefused("cross_source_requires_distinct_resources")
        except (DerivationRefused,ArithmeticError) as exc:
            diagnostics.update(status="not_ready",reasons=[str(exc)])
        ready=diagnostics["status"]=="ready"
        current[need.id]=InformationNeedAssessment(need.id,need.research_question_id,Status.SUFFICIENT if ready else Status.BLOCKED,
            reason="Dependencies and operation prerequisites ready." if ready else ";".join(diagnostics["reasons"]),
            information_need_kind="DERIVED",qualification_basis="dependency_prerequisites",prerequisite_diagnostics=diagnostics,
            evidence_status="not_applicable",search_status="not_applicable",analysis_eligible=ready)
    rqs=[build_research_readiness_assessment(research_question_id=q.id,need_assessments=[current[n.id] for n in design.information_needs if n.research_question_id==q.id]) for q in design.research_questions]
    aligned=build_research_readiness_result(rqs)
    return replace(aligned,termination_reason=result.termination_reason)


class ClassifiedReadinessEvaluator:
    def __init__(self,inner,source_repository):
        self.inner=inner
        self.sources=source_repository

    def evaluate(self,*,design,evidence):
        result=self.inner.evaluate(design=acquired_view(design),evidence=evidence)
        return align_readiness(design,evidence,result,self.sources)


def wrap_evaluator(evaluator,source_repository):
    return evaluator if isinstance(evaluator,ClassifiedReadinessEvaluator) else ClassifiedReadinessEvaluator(evaluator,source_repository)
