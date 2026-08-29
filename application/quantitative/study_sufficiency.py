from dataclasses import asdict,replace
from uuid import NAMESPACE_URL,uuid5
from application.quantitative.fingerprints import canonical_digest
from domain.quantitative.objective_coverage import ObjectiveCoverageDecision
from domain.quantitative.study_sufficiency import *

class QuantitativeStudySufficiencyError(ValueError):pass
def _text(v,required=True):
    x=" ".join(str(v).split())
    if required and not x:raise QuantitativeStudySufficiencyError("required RJ text is empty")
    if len(x)>4000:raise QuantitativeStudySufficiencyError("RJ text is oversized")
    return x

class QuantitativeStudySufficiencyService:
    def __init__(self,*,repository,digest_provider,authority_chain_selection_service,research_design_service,objective_coverage_service):
        self.repository=repository;self._digest=digest_provider;self._rk=authority_chain_selection_service;self._qz=research_design_service;self._ri=objective_coverage_service
    def _root(self,project_id,run_id):
        selection,chain=self._rk.resolve_current_selection(project_id=project_id,run_id=run_id)
        design=self._qz.resolve_current_approved(project_id=project_id,run_id=run_id)
        brief=self._qz.resolve_current_approved_brief(project_id=project_id,run_id=run_id)
        refs={(x.authority_kind,x.authority_id,x.authority_fingerprint) for x in chain.ordered_authorities}
        if ("QZ_DESIGN",design.version_id,design.fingerprint) not in refs or (brief.version_id,brief.fingerprint)!=(design.source_brief_version_id,design.source_brief_fingerprint):raise QuantitativeStudySufficiencyError("stale selected QZ/Brief authority")
        return selection,chain,design,brief
    def create_policy(self,*,policy_id,version_id,project_id,run_id,entries,created_at,created_by,version_sequence=1,parent_version_id=None,policy_semantics="ALL_MANDATORY"):
        if policy_semantics!="ALL_MANDATORY":raise QuantitativeStudySufficiencyError("unsupported alternative Study policy semantics")
        selection,chain,design,brief=self._root(project_id,run_id);expected={x.objective_id for x in design.objectives};seen=set();items=[]
        for raw in entries:
            oid=_text(raw.objective_id)
            if oid in seen:raise QuantitativeStudySufficiencyError("duplicate or contradictory Objective policy entry")
            if oid not in expected:raise QuantitativeStudySufficiencyError("unknown Objective in Study policy")
            seen.add(oid)
            try:ob=StudyObjectiveObligation(raw.obligation)
            except Exception as e:raise QuantitativeStudySufficiencyError("explicit Objective obligation required") from e
            items.append(StudyObjectivePolicyEntry(oid,ob,_text(getattr(raw,"rationale",""),False)))
        if seen!=expected:raise QuantitativeStudySufficiencyError("Objective omitted from Study policy")
        if not any(x.obligation is StudyObjectiveObligation.MANDATORY for x in items):raise QuantitativeStudySufficiencyError("Study policy requires a mandatory Objective")
        if parent_version_id is not None:
            parent=self._policy(parent_version_id,project_id,run_id)
            if self._policy_root(parent)!=(project_id,run_id,"QUANTITATIVE",selection.fingerprint,chain.manifest_fingerprint,design.fingerprint,brief.fingerprint):raise QuantitativeStudySufficiencyError("Study policy parent belongs to a different authority root")
            if version_sequence!=parent.version_sequence+1:raise QuantitativeStudySufficiencyError("Study policy version sequence does not follow its parent")
        items=tuple(sorted(items,key=lambda x:x.objective_id));body={"contract":"RJ_POLICY_V1","project":project_id,"run":run_id,"selection":selection.fingerprint,"manifest":chain.manifest_fingerprint,"qz":design.fingerprint,"brief":brief.fingerprint,"entries":tuple(asdict(x) for x in items),"method":RJ_METHOD_VERSION};fp=canonical_digest(body,digest_provider=self._digest)
        return self.repository.save_policy(QuantitativeStudyObjectiveObligationPolicyVersion(policy_id,version_id,version_sequence,project_id,run_id,"QUANTITATIVE",selection.selection_id,selection.fingerprint,chain.manifest_id,chain.manifest_fingerprint,design.version_id,design.fingerprint,brief.version_id,brief.fingerprint,items,RJ_METHOD_VERSION,parent_version_id,StudySufficiencyLifecycle.DRAFT,None,fp,created_at,created_by))
    def submit_policy_for_review(self,version_id,*,project_id,run_id,new_version_id,actor_id,changed_at):
        v=self._policy(version_id,project_id,run_id)
        if v.lifecycle_status is not StudySufficiencyLifecycle.DRAFT:raise QuantitativeStudySufficiencyError("only draft Study policy can enter review")
        return self.repository.save_policy(replace(v,version_id=new_version_id,version_sequence=v.version_sequence+1,parent_version_id=v.version_id,lifecycle_status=StudySufficiencyLifecycle.IN_REVIEW,created_at=changed_at,created_by=actor_id))
    def approve_policy(self,version_id,*,project_id,run_id,new_version_id,approval_id,expected_fingerprint,actor_id,decided_at,rationale):
        v=self._policy(version_id,project_id,run_id);selection,chain,design,_=self._root(project_id,run_id)
        if v.lifecycle_status is not StudySufficiencyLifecycle.IN_REVIEW or v.fingerprint!=expected_fingerprint or (v.selection_fingerprint,v.manifest_fingerprint,v.research_design_fingerprint)!=(selection.fingerprint,chain.manifest_fingerprint,design.fingerprint):raise QuantitativeStudySufficiencyError("Study policy approval is stale")
        approved=replace(v,version_id=new_version_id,version_sequence=v.version_sequence+1,parent_version_id=v.version_id,lifecycle_status=StudySufficiencyLifecycle.APPROVED,approval_reference=approval_id,created_at=decided_at,created_by=actor_id);rationale=_text(rationale);body={"contract":"RJ_POLICY_APPROVAL_V1","policy":approved.fingerprint,"selection":selection.fingerprint,"manifest":chain.manifest_fingerprint,"qz":design.fingerprint,"actor":actor_id,"time":decided_at,"rationale":rationale};ap=QuantitativeStudyObjectiveObligationPolicyApproval(approval_id,project_id,run_id,approved.version_id,approved.fingerprint,selection.fingerprint,chain.manifest_fingerprint,design.fingerprint,StudyPolicyDecision.APPROVED,actor_id,decided_at,rationale,canonical_digest(body,digest_provider=self._digest));self.repository.save_policy_approval(ap);return self.repository.save_policy(approved)
    def reject_policy(self,version_id,*,project_id,run_id,new_version_id,actor_id,decided_at):
        v=self._policy(version_id,project_id,run_id)
        if v.lifecycle_status is not StudySufficiencyLifecycle.IN_REVIEW:raise QuantitativeStudySufficiencyError("only in-review Study policy can be rejected")
        return self.repository.save_policy(replace(v,version_id=new_version_id,version_sequence=v.version_sequence+1,parent_version_id=v.version_id,lifecycle_status=StudySufficiencyLifecycle.REJECTED,approval_reference=None,created_at=decided_at,created_by=actor_id))
    def supersede_policy(self,version_id,*,project_id,run_id,new_version_id,actor_id,changed_at):
        v=self._policy(version_id,project_id,run_id)
        if v.lifecycle_status is not StudySufficiencyLifecycle.APPROVED:raise QuantitativeStudySufficiencyError("only approved Study policy can be superseded")
        return self.repository.save_policy(replace(v,version_id=new_version_id,version_sequence=v.version_sequence+1,parent_version_id=v.version_id,lifecycle_status=StudySufficiencyLifecycle.SUPERSEDED,approval_reference=None,created_at=changed_at,created_by=actor_id))
    def assess_current_study(self,*,project_id,run_id,created_at,created_by):
        selection,chain,design,brief=self._root(project_id,run_id);policy,pa=self._current_policy(project_id,run_id,selection,chain,design);authorities=[]
        for e in policy.entries:
            try:authorities.append(self._ri.get_approved_projection(project_id=project_id,run_id=run_id,objective_id=e.objective_id))
            except Exception:authorities.append(None)
        refs=[];blockers=[];limits=[]
        for e,a in zip(policy.entries,authorities):
            reason=None
            if a is None:reason="MISSING_RI_AUTHORITY"
            elif (a.project_id,a.run_id,a.research_design_fingerprint)!=(project_id,run_id,design.fingerprint):reason="STALE_RI_AUTHORITY"
            elif not a.approval_id or not a.approval_fingerprint:reason="UNAPPROVED_RI_AUTHORITY"
            if reason:
                (blockers if e.obligation is StudyObjectiveObligation.MANDATORY else limits).append(f"{e.objective_id}:{reason}");continue
            rb={"contract":"RJ_RI_REF_V1","objective":e.objective_id,"obligation":e.obligation.value,"assessment":a.assessment_fingerprint,"approval":a.approval_fingerprint,"decision":a.decision.value};refs.append(StudyObjectiveAssessmentReference(e.objective_id,e.obligation,a.assessment_version_id,a.assessment_fingerprint,a.approval_id,a.approval_fingerprint,a.decision.value,a.deterministic_status.value,tuple(a.blockers),tuple(a.limitations),canonical_digest(rb,digest_provider=self._digest)));limits.extend(a.limitations)
            if e.obligation is StudyObjectiveObligation.MANDATORY:blockers.extend(f"{e.objective_id}:{x}" for x in a.blockers)
        mandatory=tuple(x.objective_id for x in policy.entries if x.obligation is StudyObjectiveObligation.MANDATORY);optional=tuple(x.objective_id for x in policy.entries if x.obligation is StudyObjectiveObligation.OPTIONAL);mrefs=tuple(x for x in refs if x.obligation is StudyObjectiveObligation.MANDATORY);status=self._status(mandatory,mrefs,blockers)
        aid=str(uuid5(NAMESPACE_URL,f"rj:{project_id}:{run_id}"));body={"contract":"RJ_ASSESSMENT_V1","selection":selection.fingerprint,"manifest":chain.manifest_fingerprint,"brief":brief.fingerprint,"qz":design.fingerprint,"policy":policy.fingerprint,"policy_approval":pa.fingerprint,"mandatory":mandatory,"optional":optional,"refs":tuple(asdict(x) for x in refs),"blockers":tuple(sorted(set(blockers))),"limitations":tuple(sorted(set(limits))),"status":status.value,"method":RJ_METHOD_VERSION};fp=canonical_digest(body,digest_provider=self._digest);vid=str(uuid5(NAMESPACE_URL,f"{aid}:{fp}"));v=QuantitativeStudySufficiencyAssessmentVersion(aid,vid,1,project_id,run_id,"QUANTITATIVE",selection.selection_id,selection.fingerprint,chain.manifest_id,chain.manifest_fingerprint,brief.version_id,brief.fingerprint,design.version_id,design.fingerprint,policy.version_id,policy.fingerprint,pa.approval_id,pa.fingerprint,mandatory,optional,tuple(sorted(refs,key=lambda x:x.objective_id)),tuple(sorted(set(blockers))),tuple(sorted(set(limits))),status,RJ_METHOD_VERSION,None,StudySufficiencyLifecycle.IN_REVIEW,None,fp,created_at,created_by);return self.repository.save_assessment(v)
    def approve_study(self,version_id,*,project_id,run_id,new_version_id,approval_id,expected_fingerprint,decision,actor_id,decided_at,rationale):
        v=self.repository.get_assessment(version_id,project_id=project_id)
        if v is None or v.run_id!=run_id or v.fingerprint!=expected_fingerprint or v.lifecycle_status is not StudySufficiencyLifecycle.IN_REVIEW:raise QuantitativeStudySufficiencyError("Study assessment approval is stale")
        selection,chain,_,_=self._root(project_id,run_id)
        if (v.selection_fingerprint,v.manifest_fingerprint)!=(selection.fingerprint,chain.manifest_fingerprint):raise QuantitativeStudySufficiencyError("Study assessment is historical")
        decision=StudySufficiencyDecision(decision);self._decision(v.status,decision);m=tuple(x for x in v.objective_assessments if x.obligation is StudyObjectiveObligation.MANDATORY);approved=replace(v,version_id=new_version_id,version_sequence=v.version_sequence+1,parent_version_id=v.version_id,lifecycle_status=StudySufficiencyLifecycle.APPROVED,approval_reference=approval_id,created_at=decided_at,created_by=actor_id);rationale=_text(rationale);body={"contract":"RJ_APPROVAL_V1","assessment":approved.fingerprint,"selection":selection.fingerprint,"manifest":chain.manifest_fingerprint,"policy":v.policy_fingerprint,"policy_approval":v.policy_approval_fingerprint,"assessments":tuple(x.assessment_fingerprint for x in m),"approvals":tuple(x.approval_fingerprint for x in m),"decision":decision.value,"actor":actor_id,"time":decided_at,"rationale":rationale};ap=QuantitativeStudySufficiencyApproval(approval_id,project_id,run_id,approved.version_id,approved.fingerprint,selection.selection_id,selection.fingerprint,chain.manifest_id,chain.manifest_fingerprint,v.policy_version_id,v.policy_fingerprint,v.policy_approval_id,v.policy_approval_fingerprint,tuple(x.assessment_fingerprint for x in m),tuple(x.approval_fingerprint for x in m),decision,actor_id,decided_at,rationale,canonical_digest(body,digest_provider=self._digest));self.repository.save_approval(ap);self.repository.save_assessment(approved);return ap
    def resolve_current_approved_study(self,*,project_id,run_id):
        selection,chain,design,_=self._root(project_id,run_id);policy,pa=self._current_policy(project_id,run_id,selection,chain,design);values=self.repository.list_assessments(project_id=project_id,run_id=run_id)
        candidates=tuple(x for x in values if x.lifecycle_status is StudySufficiencyLifecycle.APPROVED and x.selection_fingerprint==selection.fingerprint and x.manifest_fingerprint==chain.manifest_fingerprint and x.policy_fingerprint==policy.fingerprint and x.policy_approval_fingerprint==pa.fingerprint)
        if len(candidates)!=1:raise QuantitativeStudySufficiencyError("current Study assessment is missing or ambiguous")
        v=candidates[0];ap=self.repository.get_approval(v.approval_reference or "",project_id=project_id)
        if v.lifecycle_status is not StudySufficiencyLifecycle.APPROVED or ap is None:raise QuantitativeStudySufficiencyError("Study sufficiency unavailable downstream")
        if (v.selection_fingerprint,v.manifest_fingerprint,v.policy_fingerprint,v.policy_approval_fingerprint)!=(selection.fingerprint,chain.manifest_fingerprint,policy.fingerprint,pa.fingerprint):raise QuantitativeStudySufficiencyError("Study sufficiency is historical")
        for ref in v.objective_assessments:
            if ref.obligation is StudyObjectiveObligation.MANDATORY:
                cur=self._ri.get_approved_projection(project_id=project_id,run_id=run_id,objective_id=ref.objective_id)
                if (cur.assessment_fingerprint,cur.approval_fingerprint)!=(ref.assessment_fingerprint,ref.approval_fingerprint):raise QuantitativeStudySufficiencyError("mandatory RI authority is stale")
        return v,ap
    def get_approved_projection(self,*,project_id,run_id):
        v,ap=self.resolve_current_approved_study(project_id=project_id,run_id=run_id);m=tuple(x for x in v.objective_assessments if x.obligation is StudyObjectiveObligation.MANDATORY);o=tuple(x for x in v.objective_assessments if x.obligation is StudyObjectiveObligation.OPTIONAL);fp=canonical_digest({"contract":"RJ_PROJECTION_V1","assessment":v.fingerprint,"approval":ap.fingerprint},digest_provider=self._digest);return ApprovedStudySufficiencyProjection(project_id,run_id,v.selection_id,v.selection_fingerprint,v.manifest_id,v.manifest_fingerprint,v.research_design_version_id,v.research_design_fingerprint,v.version_id,v.fingerprint,ap.approval_id,ap.fingerprint,ap.decision,v.status,m,o,v.blockers,v.limitations,fp)
    def dataset_only_absence(self,*,project_id,run_id):
        status="NO_DESIGN_AWARE_STUDY_SUFFICIENCY_AUTHORITY";aid=str(uuid5(NAMESPACE_URL,f"rj-absence:{project_id}:{run_id}"));v=DatasetOnlyStudySufficiencyAbsence(aid,project_id,run_id,status,"Study sufficiency is unavailable without design-aware authority.",canonical_digest({"contract":"RJ_ABSENCE_V1","id":aid,"status":status},digest_provider=self._digest));return self.repository.save_dataset_only_absence(v)
    def _policy(self,k,p,r):
        v=self.repository.get_policy(k,project_id=p)
        if v is None or v.run_id!=r:raise QuantitativeStudySufficiencyError("Study policy unavailable for project/run")
        return v
    def _current_policy(self,p,r,selection,chain,design):
        values=self.repository.list_policies(project_id=p,run_id=r)
        expected=(p,r,"QUANTITATIVE",selection.fingerprint,chain.manifest_fingerprint,design.fingerprint,design.source_brief_fingerprint)
        by_id={v.version_id:v for v in values}
        if len(by_id)!=len(values):raise QuantitativeStudySufficiencyError("Study policy lineage contains duplicate version IDs")
        relevant={v.version_id:v for v in values if self._policy_root(v)==expected}
        children={k:set() for k in relevant}
        for v in values:
            if v.parent_version_id is None:continue
            parent=by_id.get(v.parent_version_id)
            if parent is None:
                if v.version_id in relevant:raise QuantitativeStudySufficiencyError("Study policy lineage has a missing parent")
                continue
            if self._policy_root(parent)!=self._policy_root(v):raise QuantitativeStudySufficiencyError("Study policy lineage crosses authority roots")
            if v.version_sequence!=parent.version_sequence+1:raise QuantitativeStudySufficiencyError("Study policy lineage has an invalid version sequence")
            if v.version_id in relevant:children[parent.version_id].add(v.version_id)
        visiting=set();visited=set()
        def visit(version_id):
            if version_id in visiting:raise QuantitativeStudySufficiencyError("Study policy lineage contains a cycle")
            if version_id in visited:return
            visiting.add(version_id)
            for child_id in children[version_id]:visit(child_id)
            visiting.remove(version_id);visited.add(version_id)
        for version_id in relevant:visit(version_id)
        approved={v.version_id:v for v in relevant.values() if v.lifecycle_status is StudySufficiencyLifecycle.APPROVED}
        superseded_approved=set()
        for version_id in approved:
            pending=list(children[version_id]);seen=set()
            while pending:
                child_id=pending.pop()
                if child_id in seen:continue
                seen.add(child_id)
                if child_id in approved:superseded_approved.add(version_id);break
                pending.extend(children[child_id])
        candidates=[]
        for version_id,v in approved.items():
            if version_id in superseded_approved:continue
            a=self.repository.get_policy_approval(v.approval_reference or "",project_id=p)
            if a is not None and a.decision is StudyPolicyDecision.APPROVED and (a.project_id,a.run_id,a.policy_version_id,a.policy_fingerprint,a.selection_fingerprint,a.manifest_fingerprint,a.research_design_fingerprint)==(p,r,v.version_id,v.fingerprint,selection.fingerprint,chain.manifest_fingerprint,design.fingerprint):candidates.append((v,a))
        if len(candidates)!=1:raise QuantitativeStudySufficiencyError("current Study policy is missing or ambiguous")
        return candidates[0]
    @staticmethod
    def _policy_root(v):
        return (v.project_id,v.run_id,v.methodology,v.selection_fingerprint,v.manifest_fingerprint,v.research_design_fingerprint,v.source_brief_fingerprint)
    @staticmethod
    def _status(ids,refs,blockers):
        if blockers or len(ids)!=len(refs):return StudySufficiencyStatus.BLOCKED
        d={x.decision for x in refs}
        if ObjectiveCoverageDecision.OBJECTIVE_NOT_SATISFIED.value in d:return StudySufficiencyStatus.NOT_SUFFICIENT
        if ObjectiveCoverageDecision.OBJECTIVE_INCONCLUSIVE.value in d:return StudySufficiencyStatus.INCONCLUSIVE
        if ObjectiveCoverageDecision.OBJECTIVE_PARTIALLY_SATISFIED.value in d:return StudySufficiencyStatus.PARTIALLY_SUPPORTED
        if d=={ObjectiveCoverageDecision.OBJECTIVE_NOT_APPLICABLE.value}:return StudySufficiencyStatus.NOT_APPLICABLE_REVIEW
        if ObjectiveCoverageDecision.OBJECTIVE_NOT_APPLICABLE.value in d:return StudySufficiencyStatus.REQUIRES_METHODOLOGICAL_REVIEW
        return StudySufficiencyStatus.READY_FOR_STUDY_REVIEW if d=={ObjectiveCoverageDecision.OBJECTIVE_SATISFIED.value} else StudySufficiencyStatus.REQUIRES_METHODOLOGICAL_REVIEW
    @staticmethod
    def _decision(status,decision):
        allowed={StudySufficiencyStatus.READY_FOR_STUDY_REVIEW:{StudySufficiencyDecision.STUDY_SUFFICIENT},StudySufficiencyStatus.PARTIALLY_SUPPORTED:{StudySufficiencyDecision.STUDY_PARTIALLY_SUFFICIENT},StudySufficiencyStatus.INCONCLUSIVE:{StudySufficiencyDecision.STUDY_INCONCLUSIVE},StudySufficiencyStatus.NOT_SUFFICIENT:{StudySufficiencyDecision.STUDY_NOT_SUFFICIENT},StudySufficiencyStatus.NOT_APPLICABLE_REVIEW:{StudySufficiencyDecision.STUDY_NOT_APPLICABLE},StudySufficiencyStatus.REQUIRES_METHODOLOGICAL_REVIEW:{StudySufficiencyDecision.STUDY_PARTIALLY_SUFFICIENT,StudySufficiencyDecision.STUDY_INCONCLUSIVE,StudySufficiencyDecision.STUDY_NOT_SUFFICIENT},StudySufficiencyStatus.BLOCKED:set()}
        if decision not in allowed[status]:raise QuantitativeStudySufficiencyError("Study decision cannot override structural authority")
