from __future__ import annotations

from dataclasses import asdict, replace
from uuid import NAMESPACE_URL, uuid5

from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.objective_coverage import (
    RI_METHOD_VERSION, DatasetOnlyObjectiveCoverageAbsence,
    ObjectiveAssessmentStatus, ObjectiveCoverageDecision, ObjectiveCoverageLifecycle,
    ObjectivePolicyDecision, ObjectiveResearchQuestionAssessmentReference,
    ObjectiveResearchQuestionObligation, ObjectiveResearchQuestionPolicyEdge,
    QuantitativeObjectiveCoverageApproval, QuantitativeObjectiveCoverageAssessmentVersion,
    QuantitativeObjectiveCoverageRunManifest,
    QuantitativeObjectiveResearchQuestionPolicyApproval,
    QuantitativeObjectiveResearchQuestionPolicyVersion,
)
from domain.quantitative.research_question_coverage import ResearchQuestionCoverageDecision

QUANTITATIVE = "QUANTITATIVE"

class QuantitativeObjectiveCoverageError(ValueError):
    pass

def _text(value, *, required=True):
    result = " ".join(str(value).split())
    if required and not result: raise QuantitativeObjectiveCoverageError("required RI text is empty")
    if len(result) > 4000: raise QuantitativeObjectiveCoverageError("RI text is oversized")
    return result

class QuantitativeObjectiveCoverageService:
    """Provider-free post-workflow Objective sufficiency authority."""

    def __init__(self, *, repository, digest_provider, research_design_service=None, research_question_coverage_service=None):
        self.repository = repository
        self._digest = digest_provider
        self._designs = research_design_service
        self._questions = research_question_coverage_service

    def create_policy(self, *, policy_id, version_id, project_id, run_id, design,
                      edges, created_at, created_by, version_sequence=1,
                      parent_version_id=None, policy_semantics="ALL_MANDATORY"):
        if policy_semantics != "ALL_MANDATORY":
            raise QuantitativeObjectiveCoverageError("unsupported alternative Objective policy semantics")
        if design.project_id != project_id or design.methodology != QUANTITATIVE:
            raise QuantitativeObjectiveCoverageError("wrong-project or methodology QZ authority")
        objectives = {x.objective_id for x in design.objectives}
        questions = {x.question_id: x for x in design.research_questions}
        canonical = []
        seen = set()
        for raw in edges:
            try: obligation = ObjectiveResearchQuestionObligation(raw.obligation)
            except (ValueError, AttributeError) as exc: raise QuantitativeObjectiveCoverageError("malformed Objective policy obligation") from exc
            edge = ObjectiveResearchQuestionPolicyEdge(
                _text(raw.objective_id), _text(raw.research_question_id), obligation,
                _text(getattr(raw, "rationale", ""), required=False),
            )
            key = (edge.objective_id, edge.research_question_id)
            if key in seen: raise QuantitativeObjectiveCoverageError("duplicate or contradictory Objective policy edge")
            seen.add(key)
            if edge.objective_id not in objectives: raise QuantitativeObjectiveCoverageError("unknown Objective in policy")
            question = questions.get(edge.research_question_id)
            if question is None: raise QuantitativeObjectiveCoverageError("unknown ResearchQuestion in policy")
            if edge.objective_id not in question.objective_ids:
                raise QuantitativeObjectiveCoverageError("policy ResearchQuestion is not linked to Objective")
            canonical.append(edge)
        if not canonical: raise QuantitativeObjectiveCoverageError("Objective policy cannot be empty")
        linked_objectives = {x.objective_id for x in canonical}
        expected_objectives = {x.objective_id for x in design.objectives if any(x.objective_id in q.objective_ids for q in design.research_questions)}
        expected_edges = {(objective_id, q.question_id) for q in design.research_questions for objective_id in q.objective_ids}
        if linked_objectives != expected_objectives or seen != expected_edges:
            raise QuantitativeObjectiveCoverageError("missing Objective policy authority")
        if any(not any(x.objective_id == objective_id and x.obligation is ObjectiveResearchQuestionObligation.MANDATORY for x in canonical) for objective_id in expected_objectives):
            raise QuantitativeObjectiveCoverageError("each Objective policy requires a mandatory ResearchQuestion")
        payload = {"contract":"RI_OBJECTIVE_RQ_POLICY_V1","project":project_id,"run":run_id,
                   "design_version":design.version_id,"design":design.fingerprint,
                   "edges":tuple(asdict(x) for x in sorted(canonical,key=lambda x:(x.objective_id,x.research_question_id))),
                   "method":RI_METHOD_VERSION}
        value = QuantitativeObjectiveResearchQuestionPolicyVersion(
            policy_id, version_id, version_sequence, project_id, run_id, QUANTITATIVE,
            design.version_id, design.fingerprint,
            tuple(sorted(canonical,key=lambda x:(x.objective_id,x.research_question_id))),
            RI_METHOD_VERSION, parent_version_id, ObjectiveCoverageLifecycle.DRAFT,
            None, canonical_digest(payload,digest_provider=self._digest), created_at, created_by,
        )
        return self.repository.save_policy(value)

    def submit_policy_for_review(self, version_id, *, project_id, run_id, new_version_id, actor_id, changed_at):
        value = self._policy(version_id, project_id, run_id)
        if value.lifecycle_status is not ObjectiveCoverageLifecycle.DRAFT:
            raise QuantitativeObjectiveCoverageError("only draft Objective policy can enter review")
        return self.repository.save_policy(replace(value,version_id=new_version_id,version_sequence=value.version_sequence+1,
            parent_version_id=value.version_id,lifecycle_status=ObjectiveCoverageLifecycle.IN_REVIEW,
            created_at=changed_at,created_by=actor_id))

    def approve_policy(self, version_id, *, project_id, run_id, new_version_id, approval_id,
                       expected_fingerprint, actor_id, decided_at, rationale, current_design=None):
        value = self._policy(version_id, project_id, run_id)
        if value.lifecycle_status is not ObjectiveCoverageLifecycle.IN_REVIEW or value.fingerprint != expected_fingerprint:
            raise QuantitativeObjectiveCoverageError("Objective policy approval fingerprint is stale")
        design = current_design or self._current_design(project_id, run_id)
        if (value.research_design_version_id,value.research_design_fingerprint)!=(design.version_id,design.fingerprint):
            raise QuantitativeObjectiveCoverageError("Objective policy is stale for current QZ authority")
        rationale = _text(rationale)
        approved = replace(value,version_id=new_version_id,version_sequence=value.version_sequence+1,
            parent_version_id=value.version_id,lifecycle_status=ObjectiveCoverageLifecycle.APPROVED,
            approval_reference=approval_id,created_at=decided_at,created_by=actor_id)
        payload={"contract":"RI_POLICY_APPROVAL_V1","project":project_id,"run":run_id,
                 "policy":approved.fingerprint,"policy_version":approved.version_id,"design":design.fingerprint,
                 "decision":"APPROVED","actor":actor_id,"time":decided_at,"rationale":rationale}
        approval=QuantitativeObjectiveResearchQuestionPolicyApproval(
            approval_id,project_id,run_id,QUANTITATIVE,approved.version_id,approved.fingerprint,
            design.version_id,design.fingerprint,ObjectivePolicyDecision.APPROVED,actor_id,decided_at,
            rationale,canonical_digest(payload,digest_provider=self._digest))
        self.repository.save_policy_approval(approval)
        return self.repository.save_policy(approved)

    def reject_policy(self, version_id, *, project_id, run_id, new_version_id, actor_id, decided_at):
        value = self._policy(version_id, project_id, run_id)
        if value.lifecycle_status is not ObjectiveCoverageLifecycle.IN_REVIEW:
            raise QuantitativeObjectiveCoverageError("only in-review Objective policy can be rejected")
        return self.repository.save_policy(replace(
            value, version_id=new_version_id, version_sequence=value.version_sequence + 1,
            parent_version_id=value.version_id, lifecycle_status=ObjectiveCoverageLifecycle.REJECTED,
            approval_reference=None, created_at=decided_at, created_by=actor_id,
        ))

    def supersede_policy(self, version_id, *, project_id, run_id, new_version_id, actor_id, changed_at):
        value = self._policy(version_id, project_id, run_id)
        if value.lifecycle_status is not ObjectiveCoverageLifecycle.APPROVED:
            raise QuantitativeObjectiveCoverageError("only approved Objective policy can be superseded")
        return self.repository.save_policy(replace(
            value, version_id=new_version_id, version_sequence=value.version_sequence + 1,
            parent_version_id=value.version_id, lifecycle_status=ObjectiveCoverageLifecycle.SUPERSEDED,
            approval_reference=None, created_at=changed_at, created_by=actor_id,
        ))
    def assess_objective(self, *, project_id, run_id, design, objective_id, policy,
                         policy_approval, research_question_authorities, created_at, created_by,
                         version_sequence=1, parent_version_id=None):
        objective = next((x for x in design.objectives if x.objective_id==objective_id),None)
        if objective is None: raise QuantitativeObjectiveCoverageError("unknown Objective")
        self._validate_policy_authority(project_id,run_id,design,policy,policy_approval)
        edges=tuple(x for x in policy.edges if x.objective_id==objective_id)
        if not edges: raise QuantitativeObjectiveCoverageError("missing Objective policy")
        supplied={x.research_question_id:x for x in research_question_authorities}
        refs=[]; blockers=[]; limitations=[]
        for edge in edges:
            rh=supplied.get(edge.research_question_id)
            reason=None
            if rh is None: reason="MISSING_RH_AUTHORITY"
            elif objective_id not in rh.objective_ids: reason="AMBIGUOUS_OBJECTIVE_ANCESTRY"
            elif (rh.research_design_version_id,rh.research_design_fingerprint)!=(design.version_id,design.fingerprint): reason="STALE_RH_AUTHORITY"
            elif not rh.approval_id or not rh.approval_fingerprint: reason="MISSING_RH_APPROVAL"
            if reason:
                if edge.obligation is ObjectiveResearchQuestionObligation.MANDATORY: blockers.append(f"{edge.research_question_id}:{reason}")
                continue
            ref_payload={"contract":"RI_RQ_REF_V1","rq":rh.research_question_id,"obligation":edge.obligation.value,
                         "assessment":rh.assessment_fingerprint,"approval":rh.approval_fingerprint,"decision":rh.decision.value}
            refs.append(ObjectiveResearchQuestionAssessmentReference(
                rh.research_question_id,edge.obligation,rh.assessment_version_id,rh.assessment_fingerprint,
                rh.approval_id,rh.approval_fingerprint,rh.decision.value,tuple(rh.blockers),tuple(rh.limitations),
                canonical_digest(ref_payload,digest_provider=self._digest)))
            limitations.extend(rh.limitations)
            if edge.obligation is ObjectiveResearchQuestionObligation.MANDATORY and rh.blockers:
                blockers.extend(f"{edge.research_question_id}:{x}" for x in rh.blockers)
        mandatory=tuple(sorted(x.research_question_id for x in edges if x.obligation is ObjectiveResearchQuestionObligation.MANDATORY))
        optional=tuple(sorted(x.research_question_id for x in edges if x.obligation is ObjectiveResearchQuestionObligation.OPTIONAL))
        if not mandatory: raise QuantitativeObjectiveCoverageError("Objective policy requires at least one mandatory ResearchQuestion")
        mandatory_refs=tuple(x for x in refs if x.obligation is ObjectiveResearchQuestionObligation.MANDATORY)
        status=self._status(mandatory,mandatory_refs,tuple(blockers),tuple(limitations))
        statement_fp=canonical_digest({"contract":"RI_OBJECTIVE_STATEMENT_V1","id":objective_id,"statement":objective.statement},digest_provider=self._digest)
        assessment_id=str(uuid5(NAMESPACE_URL,f"ri:{project_id}:{run_id}:{objective_id}"))
        body={"contract":"RI_OBJECTIVE_ASSESSMENT_V1","project":project_id,"run":run_id,"design":design.fingerprint,
              "objective":objective_id,"statement":statement_fp,"policy":policy.fingerprint,"policy_approval":policy_approval.fingerprint,
              "mandatory":mandatory,"optional":optional,"rq":tuple(asdict(x) for x in sorted(refs,key=lambda x:x.research_question_id)),
              "blockers":tuple(sorted(set(blockers))),"limitations":tuple(sorted(set(limitations))),"status":status.value,"method":RI_METHOD_VERSION}
        fingerprint=canonical_digest(body,digest_provider=self._digest)
        version_id=str(uuid5(NAMESPACE_URL,f"{assessment_id}:{version_sequence}:{fingerprint}"))
        value=QuantitativeObjectiveCoverageAssessmentVersion(
            assessment_id,version_id,version_sequence,project_id,run_id,QUANTITATIVE,design.version_id,design.fingerprint,
            objective_id,objective.statement,statement_fp,policy.version_id,policy.fingerprint,policy_approval.approval_id,
            policy_approval.fingerprint,mandatory,optional,tuple(sorted(refs,key=lambda x:x.research_question_id)),
            tuple(sorted(set(blockers))),tuple(sorted(set(limitations))),status,RI_METHOD_VERSION,parent_version_id,
            ObjectiveCoverageLifecycle.IN_REVIEW,None,fingerprint,created_at,created_by)
        return self.repository.save_assessment(value)

    def assess_current(self, *, project_id, run_id, created_at, created_by):
        design=self._current_design(project_id,run_id)
        policy,policy_approval=self.resolve_current_approved_policy(project_id=project_id,run_id=run_id,design=design)
        results=[]
        for objective in design.objectives:
            edges=tuple(x for x in policy.edges if x.objective_id==objective.objective_id)
            projections=[]
            for edge in edges:
                try:
                    candidates=[x for x in self._questions.repository.list_assessments(project_id=project_id,run_id=run_id) if x.research_question_id==edge.research_question_id]
                    if not candidates: continue
                    latest=candidates[-1]
                    projections.append(self._questions.resolve_current_approved(project_id=project_id,run_id=run_id,research_question_id=edge.research_question_id,upstream_authority_fingerprints=latest.upstream_authority_fingerprints))
                except ValueError: continue
            results.append(self.assess_objective(project_id=project_id,run_id=run_id,design=design,objective_id=objective.objective_id,
                policy=policy,policy_approval=policy_approval,research_question_authorities=tuple(projections),created_at=created_at,created_by=created_by))
        return tuple(results)

    def approve_objective(self, version_id, *, project_id, run_id, new_version_id, approval_id, expected_fingerprint,
                          decision, actor_id, decided_at, rationale, current_design=None):
        value=self.repository.get_assessment(version_id,project_id=project_id)
        if value is None or value.run_id!=run_id: raise QuantitativeObjectiveCoverageError("Objective assessment unavailable for project/run")
        if value.lifecycle_status is not ObjectiveCoverageLifecycle.IN_REVIEW or value.fingerprint!=expected_fingerprint:
            raise QuantitativeObjectiveCoverageError("Objective assessment approval fingerprint is stale")
        design=current_design or self._current_design(project_id,run_id)
        if (value.research_design_version_id,value.research_design_fingerprint)!=(design.version_id,design.fingerprint):
            raise QuantitativeObjectiveCoverageError("Objective assessment is stale for current QZ")
        decision=ObjectiveCoverageDecision(decision); self._validate_decision(value.status,decision)
        rationale=_text(rationale)
        rh_assessments=tuple(x.assessment_fingerprint for x in value.research_question_assessments)
        rh_approvals=tuple(x.approval_fingerprint for x in value.research_question_assessments)
        payload={"contract":"RI_OBJECTIVE_APPROVAL_V1","assessment":value.fingerprint,"decision":decision.value,
                 "policy":value.policy_fingerprint,"rh_assessments":rh_assessments,"rh_approvals":rh_approvals,
                 "actor":actor_id,"time":decided_at,"rationale":rationale}
        approved=replace(value,version_id=new_version_id,version_sequence=value.version_sequence+1,
            parent_version_id=value.version_id,lifecycle_status=ObjectiveCoverageLifecycle.APPROVED,
            approval_reference=approval_id,created_at=decided_at,created_by=actor_id)
        approval=QuantitativeObjectiveCoverageApproval(approval_id,project_id,run_id,QUANTITATIVE,value.objective_id,
            approved.version_id,approved.fingerprint,value.research_design_fingerprint,value.policy_fingerprint,rh_assessments,
            rh_approvals,decision,actor_id,decided_at,rationale,canonical_digest(payload,digest_provider=self._digest))
        self.repository.save_approval(approval)
        self.repository.save_assessment(approved)
        return approval

    def resolve_current_approved_objective(self, *, project_id, run_id, objective_id, design, policy, research_question_authorities):
        values = tuple(x for x in self.repository.list_assessments(project_id=project_id, run_id=run_id) if x.objective_id == objective_id)
        if not values:
            raise QuantitativeObjectiveCoverageError("no Objective coverage assessment")
        value = values[-1]
        approval = self.repository.get_approval(value.approval_reference or "", project_id=project_id)
        expected_rh = tuple(sorted(x.assessment_fingerprint for x in research_question_authorities))
        expected_approvals = tuple(sorted(x.approval_fingerprint for x in research_question_authorities))
        if value.lifecycle_status is not ObjectiveCoverageLifecycle.APPROVED:
            raise QuantitativeObjectiveCoverageError("Objective coverage authority is unapproved")
        if (value.research_design_version_id, value.research_design_fingerprint) != (design.version_id, design.fingerprint) or value.policy_fingerprint != policy.fingerprint:
            raise QuantitativeObjectiveCoverageError("Objective coverage authority is stale")
        if approval is None or approval.assessment_fingerprint != value.fingerprint or tuple(sorted(approval.research_question_assessment_fingerprints)) != expected_rh or tuple(sorted(approval.research_question_approval_fingerprints)) != expected_approvals:
            raise QuantitativeObjectiveCoverageError("Objective coverage approval is missing or stale")
        return value, approval
    def build_run_manifest(self, *, project_id, run_id, design, assessments):
        refs=[]; approvals=[]; unresolved=[]
        for item in sorted(assessments,key=lambda x:x.objective_id):
            if (item.research_design_version_id,item.research_design_fingerprint)!=(design.version_id,design.fingerprint):
                raise QuantitativeObjectiveCoverageError("stale Objective assessment in run manifest")
            refs.append((item.objective_id,item.version_id,item.fingerprint))
            approval=self.repository.get_approval(item.approval_reference or "",project_id=project_id)
            if approval is None: unresolved.append(item.objective_id)
            else: approvals.append((item.objective_id,approval.approval_id,approval.fingerprint))
        unresolved.extend(x.objective_id for x in design.objectives if x.objective_id not in {r[0] for r in refs})
        body={"contract":"RI_RUN_MANIFEST_V1","project":project_id,"run":run_id,"design":design.fingerprint,
              "assessments":tuple(refs),"approvals":tuple(approvals),"unresolved":tuple(sorted(set(unresolved))),"method":RI_METHOD_VERSION}
        fp=canonical_digest(body,digest_provider=self._digest)
        value=QuantitativeObjectiveCoverageRunManifest(str(uuid5(NAMESPACE_URL,f"ri-run:{project_id}:{run_id}:{fp}")),project_id,run_id,
            design.version_id,design.fingerprint,tuple(refs),tuple(approvals),tuple(sorted(set(unresolved))),RI_METHOD_VERSION,fp)
        return self.repository.save_run_manifest(value)

    def dataset_only_absence(self, *, project_id, run_id):
        status="NO_DESIGN_AWARE_OBJECTIVE_COVERAGE"; absence_id=str(uuid5(NAMESPACE_URL,f"ri-absence:{project_id}:{run_id}"))
        value=DatasetOnlyObjectiveCoverageAbsence(absence_id,project_id,run_id,status,
            "Objective sufficiency cannot be assessed without approved design-aware ResearchQuestion authority.",
            canonical_digest({"contract":"RI_DATASET_ONLY_V1","id":absence_id,"status":status},digest_provider=self._digest))
        return self.repository.save_dataset_only_absence(value)

    def resolve_current_approved_policy(self, *, project_id, run_id, design):
        values=self.repository.list_policies(project_id=project_id,run_id=run_id)
        if not values: raise QuantitativeObjectiveCoverageError("missing Objective policy")
        value=values[-1]
        approval=self.repository.get_policy_approval(value.approval_reference or "",project_id=project_id)
        self._validate_policy_authority(project_id,run_id,design,value,approval)
        return value,approval

    def _policy(self, version_id, project_id, run_id):
        value=self.repository.get_policy(version_id,project_id=project_id)
        if value is None or value.run_id!=run_id: raise QuantitativeObjectiveCoverageError("Objective policy unavailable for project/run")
        return value

    def _current_design(self, project_id, run_id):
        if self._designs is None: raise QuantitativeObjectiveCoverageError("QZ service unavailable")
        return self._designs.resolve_current_approved(project_id=project_id,run_id=run_id)

    @staticmethod
    def _validate_policy_authority(project_id,run_id,design,policy,approval):
        if policy.project_id!=project_id or policy.run_id!=run_id or design.project_id!=project_id: raise QuantitativeObjectiveCoverageError("wrong project/run RI authority")
        if policy.lifecycle_status is not ObjectiveCoverageLifecycle.APPROVED: raise QuantitativeObjectiveCoverageError("Objective policy is unapproved")
        if (policy.research_design_version_id,policy.research_design_fingerprint)!=(design.version_id,design.fingerprint): raise QuantitativeObjectiveCoverageError("stale QZ/policy authority")
        if approval is None or approval.decision is not ObjectivePolicyDecision.APPROVED or approval.policy_version_id!=policy.version_id or approval.policy_fingerprint!=policy.fingerprint or approval.research_design_fingerprint!=design.fingerprint: raise QuantitativeObjectiveCoverageError("Objective policy approval is missing or stale")

    @staticmethod
    def _status(mandatory_ids,refs,blockers,limitations):
        if blockers or len(refs)!=len(mandatory_ids): return ObjectiveAssessmentStatus.BLOCKED
        if any("CONFLICT" in x.upper() or "UNRESOLVED" in x.upper() for x in limitations): return ObjectiveAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW
        decisions={x.decision for x in refs}
        if decisions=={ResearchQuestionCoverageDecision.SUFFICIENTLY_ANSWERED.value}: return ObjectiveAssessmentStatus.READY_FOR_OBJECTIVE_REVIEW
        if decisions=={ResearchQuestionCoverageDecision.NOT_APPLICABLE.value}: return ObjectiveAssessmentStatus.NOT_APPLICABLE_REVIEW
        if decisions=={ResearchQuestionCoverageDecision.NOT_ANSWERED.value}: return ObjectiveAssessmentStatus.NOT_SATISFIED
        if decisions=={ResearchQuestionCoverageDecision.INCONCLUSIVE.value}: return ObjectiveAssessmentStatus.INCONCLUSIVE
        if ResearchQuestionCoverageDecision.SUFFICIENTLY_ANSWERED.value in decisions: return ObjectiveAssessmentStatus.PARTIALLY_SUPPORTED
        if ResearchQuestionCoverageDecision.INCONCLUSIVE.value in decisions: return ObjectiveAssessmentStatus.INCONCLUSIVE
        return ObjectiveAssessmentStatus.PARTIALLY_SUPPORTED

    @staticmethod
    def _validate_decision(status,decision):
        allowed={
            ObjectiveAssessmentStatus.READY_FOR_OBJECTIVE_REVIEW:{ObjectiveCoverageDecision.OBJECTIVE_SATISFIED,ObjectiveCoverageDecision.OBJECTIVE_PARTIALLY_SATISFIED},
            ObjectiveAssessmentStatus.PARTIALLY_SUPPORTED:{ObjectiveCoverageDecision.OBJECTIVE_PARTIALLY_SATISFIED,ObjectiveCoverageDecision.OBJECTIVE_NOT_SATISFIED},
            ObjectiveAssessmentStatus.INCONCLUSIVE:{ObjectiveCoverageDecision.OBJECTIVE_INCONCLUSIVE,ObjectiveCoverageDecision.OBJECTIVE_NOT_SATISFIED},
            ObjectiveAssessmentStatus.NOT_SATISFIED:{ObjectiveCoverageDecision.OBJECTIVE_NOT_SATISFIED},
            ObjectiveAssessmentStatus.NOT_APPLICABLE_REVIEW:{ObjectiveCoverageDecision.OBJECTIVE_NOT_APPLICABLE},
            ObjectiveAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW:{ObjectiveCoverageDecision.OBJECTIVE_PARTIALLY_SATISFIED,ObjectiveCoverageDecision.OBJECTIVE_INCONCLUSIVE,ObjectiveCoverageDecision.OBJECTIVE_NOT_SATISFIED},
            ObjectiveAssessmentStatus.BLOCKED:set(),
        }
        if decision not in allowed[status]: raise QuantitativeObjectiveCoverageError("Objective decision cannot override structural assessment authority")
