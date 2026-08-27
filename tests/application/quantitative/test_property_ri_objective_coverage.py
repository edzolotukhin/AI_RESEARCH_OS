import unittest
from dataclasses import replace
from types import SimpleNamespace as NS

from application.quantitative.objective_coverage import QuantitativeObjectiveCoverageError, QuantitativeObjectiveCoverageService
from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from domain.quantitative.objective_coverage import (
    ObjectiveAssessmentStatus, ObjectiveCoverageDecision, ObjectiveResearchQuestionObligation,
    ObjectiveResearchQuestionPolicyEdge,
)
from domain.quantitative.research_question_coverage import ApprovedResearchQuestionCoverageProjection, ResearchQuestionCoverageDecision
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_objective_coverage_repository import QLQuantitativeObjectiveCoverageRepository
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider

class MemoryRepository:
    def __init__(self): self.policies={}; self.policy_approvals={}; self.assessments={}; self.approvals={}; self.manifests={}; self.absences={}
    def _save(self,store,key,value):
        if key in store and store[key]!=value: raise ValueError("conflict")
        store[key]=value; return value
    def save_policy(self,v): return self._save(self.policies,v.version_id,v)
    def get_policy(self,k,*,project_id):
        v=self.policies.get(k); return v if v is None or v.project_id==project_id else None
    def list_policies(self,*,project_id,run_id): return tuple(sorted((v for v in self.policies.values() if (v.project_id,v.run_id)==(project_id,run_id)),key=lambda x:x.version_sequence))
    def save_policy_approval(self,v): return self._save(self.policy_approvals,v.approval_id,v)
    def get_policy_approval(self,k,*,project_id):
        v=self.policy_approvals.get(k); return v if v is None or v.project_id==project_id else None
    def save_assessment(self,v): return self._save(self.assessments,v.version_id,v)
    def get_assessment(self,k,*,project_id):
        v=self.assessments.get(k); return v if v is None or v.project_id==project_id else None
    def list_assessments(self,*,project_id,run_id): return tuple(sorted((v for v in self.assessments.values() if (v.project_id,v.run_id)==(project_id,run_id)),key=lambda x:x.version_sequence))
    def save_approval(self,v): return self._save(self.approvals,v.approval_id,v)
    def get_approval(self,k,*,project_id):
        v=self.approvals.get(k); return v if v is None or v.project_id==project_id else None
    def save_run_manifest(self,v): return self._save(self.manifests,v.manifest_id,v)
    def get_run_manifest(self,k,*,project_id): return self.manifests.get(k)
    def save_dataset_only_absence(self,v): return self._save(self.absences,v.absence_id,v)

class PropertyRITests(unittest.TestCase):
    def setUp(self):
        self.repo=MemoryRepository(); self.service=QuantitativeObjectiveCoverageService(repository=self.repo,digest_provider=Sha256DigestProvider())
        self.design=NS(project_id="p",methodology="QUANTITATIVE",version_id="qz-v1",fingerprint="qz-fp",
            objectives=(NS(objective_id="o1",statement="Understand demand"),NS(objective_id="o2",statement="Understand retention")),
            research_questions=(NS(question_id="rq1",objective_ids=("o1","o2")),NS(question_id="rq2",objective_ids=("o1",)),NS(question_id="rq3",objective_ids=("o2",))))

    def edge(self,o,r,ob="MANDATORY",why="Required by design review"):
        return ObjectiveResearchQuestionPolicyEdge(o,r,ObjectiveResearchQuestionObligation(ob),why)

    def approved_policy(self,edges=None):
        edges=edges or (self.edge("o1","rq1"),self.edge("o1","rq2","OPTIONAL"),self.edge("o2","rq1"),self.edge("o2","rq3"))
        draft=self.service.create_policy(policy_id="policy",version_id="policy-draft",project_id="p",run_id="r",design=self.design,edges=edges,created_at="t0",created_by="human")
        review=self.service.submit_policy_for_review(draft.version_id,project_id="p",run_id="r",new_version_id="policy-review",actor_id="human",changed_at="t1")
        approved=self.service.approve_policy(review.version_id,project_id="p",run_id="r",new_version_id="policy-approved",approval_id="policy-approval",expected_fingerprint=review.fingerprint,actor_id="human",decided_at="t2",rationale="Reviewed methodology",current_design=self.design)
        return approved,self.repo.policy_approvals["policy-approval"]

    def rh(self,rq,decision="SUFFICIENTLY_ANSWERED",objectives=None,limitations=()):
        objectives=objectives or next(x.objective_ids for x in self.design.research_questions if x.question_id==rq)
        return ApprovedResearchQuestionCoverageProjection("rh",f"rh-{rq}",f"rh-fp-{rq}",rq,objectives,ResearchQuestionCoverageDecision(decision),(),(),limitations,
            f"rh-ap-{rq}",f"rh-ap-fp-{rq}",self.design.version_id,self.design.fingerprint,("ar1",),(),(("re","fp"),))

    def assess(self,objective="o1",rhs=None,policy=None,approval=None):
        if policy is None: policy,approval=self.approved_policy()
        return self.service.assess_objective(project_id="p",run_id="r",design=self.design,objective_id=objective,policy=policy,policy_approval=approval,
            research_question_authorities=tuple(rhs if rhs is not None else (self.rh("rq1"),)),created_at="t3",created_by="system")

    def test_policy_validation_and_exact_approval(self):
        policy,approval=self.approved_policy()
        self.assertEqual(policy.fingerprint,approval.policy_fingerprint)
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"duplicate"):
            self.service.create_policy(policy_id="x",version_id="x",project_id="p",run_id="r",design=self.design,edges=(self.edge("o1","rq1"),self.edge("o1","rq1","OPTIONAL")),created_at="t",created_by="x")
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"unknown Objective"):
            self.service.create_policy(policy_id="x",version_id="y",project_id="p",run_id="r",design=self.design,edges=(self.edge("missing","rq1"),),created_at="t",created_by="x")
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"not linked"):
            self.service.create_policy(policy_id="x",version_id="z",project_id="p",run_id="r",design=self.design,edges=(self.edge("o2","rq2"),self.edge("o1","rq1")),created_at="t",created_by="x")
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"unsupported alternative"):
            self.service.create_policy(policy_id="x",version_id="a",project_id="p",run_id="r",design=self.design,edges=(self.edge("o1","rq1"),),created_at="t",created_by="x",policy_semantics="ANY")

    def test_ready_optional_gap_and_human_approval(self):
        value=self.assess()
        self.assertEqual(ObjectiveAssessmentStatus.READY_FOR_OBJECTIVE_REVIEW,value.status)
        approval=self.service.approve_objective(value.version_id,project_id="p",run_id="r",new_version_id="o1-approved",approval_id="oa",expected_fingerprint=value.fingerprint,decision=ObjectiveCoverageDecision.OBJECTIVE_SATISFIED,actor_id="human",decided_at="t4",rationale="Objective evidence is sufficient",current_design=self.design)
        self.assertEqual(ObjectiveCoverageDecision.OBJECTIVE_SATISFIED,approval.decision)

    def test_missing_mandatory_blocks_and_cannot_be_overridden(self):
        value=self.assess(rhs=())
        self.assertEqual(ObjectiveAssessmentStatus.BLOCKED,value.status)
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"cannot override"):
            self.service.approve_objective(value.version_id,project_id="p",run_id="r",new_version_id="bad",approval_id="bad",expected_fingerprint=value.fingerprint,decision="OBJECTIVE_SATISFIED",actor_id="human",decided_at="t",rationale="No",current_design=self.design)

    def test_partial_inconclusive_and_not_applicable_are_structural(self):
        policy,approval=self.approved_policy(edges=(self.edge("o1","rq1"),self.edge("o1","rq2"),self.edge("o2","rq1"),self.edge("o2","rq3")))
        partial=self.assess(rhs=(self.rh("rq1"),self.rh("rq2","PARTIALLY_SUPPORTED")),policy=policy,approval=approval)
        self.assertEqual(ObjectiveAssessmentStatus.PARTIALLY_SUPPORTED,partial.status)
        inconclusive=self.assess(rhs=(self.rh("rq1","INCONCLUSIVE"),self.rh("rq2","INCONCLUSIVE")),policy=policy,approval=approval)
        self.assertEqual(ObjectiveAssessmentStatus.INCONCLUSIVE,inconclusive.status)
        na=self.assess(rhs=(self.rh("rq1","NOT_APPLICABLE"),self.rh("rq2","NOT_APPLICABLE")),policy=policy,approval=approval)
        self.assertEqual(ObjectiveAssessmentStatus.NOT_APPLICABLE_REVIEW,na.status)
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"cannot override"):
            self.service.approve_objective(na.version_id,project_id="p",run_id="r",new_version_id="bad-na",approval_id="x",expected_fingerprint=na.fingerprint,decision="OBJECTIVE_SATISFIED",actor_id="h",decided_at="t",rationale="bad",current_design=self.design)

    def test_shared_rq_preserves_objective_specific_policy(self):
        policy,approval=self.approved_policy()
        first=self.assess("o1",(self.rh("rq1"),),policy,approval)
        second=self.assess("o2",(self.rh("rq1"),self.rh("rq3","NOT_ANSWERED")),policy,approval)
        self.assertEqual(ObjectiveAssessmentStatus.READY_FOR_OBJECTIVE_REVIEW,first.status)
        self.assertEqual(ObjectiveAssessmentStatus.PARTIALLY_SUPPORTED,second.status)
        self.assertEqual("o1",next(x for x in policy.edges if x.objective_id=="o1").objective_id)

    def test_conflicting_limitation_requires_methodological_review(self):
        value=self.assess(rhs=(self.rh("rq1",limitations=("Unresolved conflict between valid branches",)),))
        self.assertEqual(ObjectiveAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW,value.status)

    def test_stale_qz_policy_and_rh_fail_closed(self):
        policy,approval=self.approved_policy()
        stale_design=NS(**{**vars(self.design),"fingerprint":"changed"})
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"stale QZ/policy"):
            self.service.assess_objective(project_id="p",run_id="r",design=stale_design,objective_id="o1",policy=policy,policy_approval=approval,research_question_authorities=(self.rh("rq1"),),created_at="t",created_by="x")
        blocked=self.assess(rhs=(replace(self.rh("rq1"),research_design_fingerprint="old"),),policy=policy,approval=approval)
        self.assertEqual(ObjectiveAssessmentStatus.BLOCKED,blocked.status)

    def test_run_manifest_is_not_study_sufficiency(self):
        value=self.assess(); manifest=self.service.build_run_manifest(project_id="p",run_id="r",design=self.design,assessments=(value,))
        self.assertIn("o1",manifest.unresolved_objective_ids); self.assertIn("o2",manifest.unresolved_objective_ids)
        self.assertFalse(hasattr(manifest,"study_sufficient"))

    def test_policy_rejected_and_superseded_are_not_current(self):
        draft=self.service.create_policy(policy_id="reject",version_id="reject-draft",project_id="p",run_id="r",design=self.design,edges=(self.edge("o1","rq1"),self.edge("o1","rq2","OPTIONAL"),self.edge("o2","rq1"),self.edge("o2","rq3")),created_at="t",created_by="h")
        review=self.service.submit_policy_for_review(draft.version_id,project_id="p",run_id="r",new_version_id="reject-review",actor_id="h",changed_at="t")
        rejected=self.service.reject_policy(review.version_id,project_id="p",run_id="r",new_version_id="rejected",actor_id="h",decided_at="t")
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"unapproved"):
            self.service.assess_objective(project_id="p",run_id="r",design=self.design,objective_id="o1",policy=rejected,policy_approval=None,research_question_authorities=(self.rh("rq1"),),created_at="t",created_by="h")
        policy,approval=self.approved_policy()
        superseded=self.service.supersede_policy(policy.version_id,project_id="p",run_id="r",new_version_id="superseded",actor_id="h",changed_at="t")
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"unapproved"):
            self.service.assess_objective(project_id="p",run_id="r",design=self.design,objective_id="o1",policy=superseded,policy_approval=approval,research_question_authorities=(self.rh("rq1"),),created_at="t",created_by="h")

    def test_current_resolution_rejects_changed_rh_and_preserves_history(self):
        policy,policy_approval=self.approved_policy()
        rh=self.rh("rq1")
        value=self.assess(rhs=(rh,),policy=policy,approval=policy_approval)
        approval=self.service.approve_objective(value.version_id,project_id="p",run_id="r",new_version_id="approved-current",approval_id="objective-approval",expected_fingerprint=value.fingerprint,decision="OBJECTIVE_SATISFIED",actor_id="human",decided_at="t",rationale="Reviewed",current_design=self.design)
        current,current_approval=self.service.resolve_current_approved_objective(project_id="p",run_id="r",objective_id="o1",design=self.design,policy=policy,research_question_authorities=(rh,))
        self.assertEqual(approval,current_approval); self.assertEqual("approved-current",current.version_id)
        self.assertIsNotNone(self.repo.get_assessment(value.version_id,project_id="p"))
        with self.assertRaisesRegex(QuantitativeObjectiveCoverageError,"missing or stale"):
            self.service.resolve_current_approved_objective(project_id="p",run_id="r",objective_id="o1",design=self.design,policy=policy,research_question_authorities=(replace(rh,approval_fingerprint="new"),))
    def test_dataset_only_has_explicit_absence(self):
        value=self.service.dataset_only_absence(project_id="p",run_id="r")
        self.assertEqual("NO_DESIGN_AWARE_OBJECTIVE_COVERAGE",value.status)
        self.assertFalse(hasattr(value,"objective_id"))

    def test_ql_restart_identical_replay_wrong_project_and_corruption(self):
        records=InMemoryQuantitativeStateRepository(); state=QuantitativeStateService(repository=records,digest_provider=Sha256DigestProvider())
        repo=QLQuantitativeObjectiveCoverageRepository(state); service=QuantitativeObjectiveCoverageService(repository=repo,digest_provider=Sha256DigestProvider())
        value=service.dataset_only_absence(project_id="p",run_id="r")
        self.assertEqual(value,service.dataset_only_absence(project_id="p",run_id="r"))
        self.assertIsNone(repo._get(value.absence_id,"other",type(value)))
        record=records._records[value.absence_id]; records._records[value.absence_id]=replace(record,payload_checksum="corrupt")
        with self.assertRaisesRegex(QuantitativePersistenceError,"checksum"): state.load(value.absence_id,project_id="p")

    def test_authority_contains_no_respondent_payload(self):
        value=self.assess(); encoded=repr(value).lower()
        for forbidden in ("respondent_id","raw_rows","credentials","storage_path"): self.assertNotIn(forbidden,encoded)

if __name__ == "__main__": unittest.main()
