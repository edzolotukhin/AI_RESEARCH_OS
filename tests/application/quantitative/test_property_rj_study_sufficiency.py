import unittest
from dataclasses import replace
from types import SimpleNamespace as NS
from application.quantitative.study_sufficiency import QuantitativeStudySufficiencyError,QuantitativeStudySufficiencyService
from domain.quantitative.authority_chain import QuantitativeCurrentAuthorityChainSelection,QuantitativeDesignAwareAuthorityChainProjection
from domain.quantitative.objective_coverage import ApprovedObjectiveCoverageProjection,ObjectiveAssessmentStatus,ObjectiveCoverageDecision
from domain.quantitative.research_question_coverage import QuantitativeAuthorityReference
from domain.quantitative.study_sufficiency import *
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider

class Repo:
    def __init__(self):self.p={};self.pa={};self.a={};self.ap={};self.abs={}
    def _s(self,d,k,v):
        if k in d and d[k]!=v:raise ValueError("conflict")
        d[k]=v;return v
    def save_policy(self,v):return self._s(self.p,v.version_id,v)
    def get_policy(self,k,*,project_id):return self.p.get(k)
    def list_policies(self,*,project_id,run_id):return tuple(sorted(self.p.values(),key=lambda x:x.version_sequence))
    def save_policy_approval(self,v):return self._s(self.pa,v.approval_id,v)
    def get_policy_approval(self,k,*,project_id):return self.pa.get(k)
    def save_assessment(self,v):return self._s(self.a,v.version_id,v)
    def get_assessment(self,k,*,project_id):return self.a.get(k)
    def list_assessments(self,*,project_id,run_id):return tuple(sorted(self.a.values(),key=lambda x:x.version_sequence))
    def save_approval(self,v):return self._s(self.ap,v.approval_id,v)
    def get_approval(self,k,*,project_id):return self.ap.get(k)
    def save_dataset_only_absence(self,v):return self._s(self.abs,v.absence_id,v)

class PropertyRJTests(unittest.TestCase):
    def setUp(self):
        self.repo=Repo();self.selection=QuantitativeCurrentAuthorityChainSelection("sel","p","r","QUANTITATIVE","DESIGN_AWARE_EXECUTION","chain","chain-fp","qz-v1","qz-fp","rc","rc-fp",None,"t","system","rk-1","sel-fp");qzref=QuantitativeAuthorityReference("QZ_DESIGN","qz-v1","qz-fp");self.chain=QuantitativeDesignAwareAuthorityChainProjection("chain","chain-fp","p","r","DESIGN_AWARE_EXECUTION",(qzref,),(),(),());self.rk=NS(resolve_current_selection=lambda **_: (self.selection,self.chain));self.brief=NS(version_id="brief-v1",fingerprint="brief-fp");self.design=NS(project_id="p",methodology="QUANTITATIVE",version_id="qz-v1",fingerprint="qz-fp",source_brief_version_id="brief-v1",source_brief_fingerprint="brief-fp",objectives=(NS(objective_id="o1",priority="LOW"),NS(objective_id="o2",priority="HIGH")));self.qz=NS(resolve_current_approved=lambda **_:self.design,resolve_current_approved_brief=lambda **_:self.brief);self.current={"o1":self.ri("o1"),"o2":self.ri("o2")};self.ri_service=NS(get_approved_projection=lambda **k:self.current[k["objective_id"]]);self.service=QuantitativeStudySufficiencyService(repository=self.repo,digest_provider=Sha256DigestProvider(),authority_chain_selection_service=self.rk,research_design_service=self.qz,objective_coverage_service=self.ri_service)
    def ri(self,o,d="OBJECTIVE_SATISFIED"):
        return ApprovedObjectiveCoverageProjection("p","r",o,"qz-v1","qz-fp",f"a-{o}",f"af-{o}",f"ap-{o}",f"apf-{o}",ObjectiveCoverageDecision(d),ObjectiveAssessmentStatus.READY_FOR_OBJECTIVE_REVIEW,"pol","pf","pap","papf",(),(),(),f"proj-{o}")
    def entry(self,o,ob="MANDATORY"):return StudyObjectivePolicyEntry(o,StudyObjectiveObligation(ob),"Reviewed role")
    def policy(self,entries=None):
        entries=entries or (self.entry("o1"),self.entry("o2","OPTIONAL"));tag="-".join(x.objective_id+x.obligation.value for x in entries);d=self.service.create_policy(policy_id=tag,version_id="d"+tag,project_id="p",run_id="r",entries=entries,created_at="t",created_by="h");rv=self.service.submit_policy_for_review(d.version_id,project_id="p",run_id="r",new_version_id="v"+tag,actor_id="h",changed_at="t");p=self.service.approve_policy(rv.version_id,project_id="p",run_id="r",new_version_id="p"+tag,approval_id="pa"+tag,expected_fingerprint=rv.fingerprint,actor_id="h",decided_at="t",rationale="Approved");return p,self.repo.pa["pa"+tag]
    def assess(self,entries=None):self.policy(entries);return self.service.assess_current_study(project_id="p",run_id="r",created_at="t",created_by="system")
    def replacement_draft(self,parent,tag="2",entries=None):
        entries=entries or (self.entry("o1"),self.entry("o2","OPTIONAL"))
        return self.service.create_policy(policy_id=f"replacement-{tag}",version_id=f"replacement-{tag}-draft",project_id="p",run_id="r",entries=entries,created_at="t",created_by="h",version_sequence=parent.version_sequence+1,parent_version_id=parent.version_id)
    def approve_replacement(self,draft,tag="2"):
        review=self.service.submit_policy_for_review(draft.version_id,project_id="p",run_id="r",new_version_id=f"replacement-{tag}-review",actor_id="h",changed_at="t")
        approved=self.service.approve_policy(review.version_id,project_id="p",run_id="r",new_version_id=f"replacement-{tag}-approved",approval_id=f"replacement-{tag}-approval",expected_fingerprint=review.fingerprint,actor_id="h",decided_at="t",rationale="Approved replacement")
        return review,approved,self.repo.pa[f"replacement-{tag}-approval"]
    def test_policy_validation_and_exact_binding(self):
        p,a=self.policy();self.assertEqual(self.selection.fingerprint,p.selection_fingerprint);self.assertEqual(p.fingerprint,a.policy_fingerprint)
        for entries,message in [((self.entry("o1"),),"omitted"),((self.entry("o1"),self.entry("bad")),"unknown"),((self.entry("o1"),self.entry("o1"),self.entry("o2")),"duplicate"),((self.entry("o1","OPTIONAL"),self.entry("o2","OPTIONAL")),"mandatory")]:
            with self.subTest(message=message),self.assertRaisesRegex(QuantitativeStudySufficiencyError,message):self.service.create_policy(policy_id=message,version_id=message,project_id="p",run_id="r",entries=entries,created_at="t",created_by="h")
    def test_root_uses_public_qz_boundary_and_checks_exact_brief_binding(self):
        calls=[]
        self.qz=NS(
            resolve_current_approved=lambda **scope:(calls.append(("design",scope)) or self.design),
            resolve_current_approved_brief=lambda **scope:(calls.append(("brief",scope)) or self.brief),
        )
        self.service._qz=self.qz
        self.service.create_policy(policy_id="public",version_id="public-v1",project_id="p",run_id="r",entries=(self.entry("o1"),self.entry("o2")),created_at="t",created_by="h")
        self.assertEqual([("design",{"project_id":"p","run_id":"r"}),("brief",{"project_id":"p","run_id":"r"})],calls)
        for brief in (NS(version_id="brief-v2",fingerprint=self.brief.fingerprint),NS(version_id=self.brief.version_id,fingerprint="other")):
            with self.subTest(brief=brief),self.assertRaisesRegex(QuantitativeStudySufficiencyError,"stale selected QZ/Brief"):
                self.qz.resolve_current_approved_brief=lambda **_:brief
                self.service.create_policy(policy_id="stale",version_id="stale",project_id="p",run_id="r",entries=(self.entry("o1"),self.entry("o2")),created_at="t",created_by="h")
    def test_ready_optional_absence_and_delivery_separation(self):
        del self.current["o2"];v=self.assess();self.assertEqual(StudySufficiencyStatus.READY_FOR_STUDY_REVIEW,v.status);self.assertNotIn("report",repr(v).lower())
    def test_status_precedence(self):
        entries=(self.entry("o1"),self.entry("o2"))
        for d,status in (("OBJECTIVE_NOT_SATISFIED",StudySufficiencyStatus.NOT_SUFFICIENT),("OBJECTIVE_INCONCLUSIVE",StudySufficiencyStatus.INCONCLUSIVE),("OBJECTIVE_PARTIALLY_SATISFIED",StudySufficiencyStatus.PARTIALLY_SUPPORTED)):
            self.current["o2"]=self.ri("o2",d);self.assertEqual(status,self.assess(entries).status)
        self.current.pop("o2");self.assertEqual(StudySufficiencyStatus.BLOCKED,self.assess(entries).status)
    def test_applicability(self):
        e=(self.entry("o1"),self.entry("o2"));self.current={"o1":self.ri("o1","OBJECTIVE_NOT_APPLICABLE"),"o2":self.ri("o2","OBJECTIVE_NOT_APPLICABLE")};self.assertEqual(StudySufficiencyStatus.NOT_APPLICABLE_REVIEW,self.assess(e).status);self.current["o1"]=self.ri("o1");self.assertEqual(StudySufficiencyStatus.REQUIRES_METHODOLOGICAL_REVIEW,self.assess(e).status)
    def test_human_approval_and_blocked_override(self):
        v=self.assess();ap=self.service.approve_study(v.version_id,project_id="p",run_id="r",new_version_id="approved",approval_id="sap",expected_fingerprint=v.fingerprint,decision="STUDY_SUFFICIENT",actor_id="h",decided_at="t",rationale="Sufficient");self.assertEqual(StudySufficiencyDecision.STUDY_SUFFICIENT,ap.decision)
        self.repo=Repo();self.service.repository=self.repo;self.current.pop("o1");b=self.assess();self.assertEqual(StudySufficiencyStatus.BLOCKED,b.status)
        with self.assertRaisesRegex(QuantitativeStudySufficiencyError,"cannot override"):self.service.approve_study(b.version_id,project_id="p",run_id="r",new_version_id="bad",approval_id="bad",expected_fingerprint=b.fingerprint,decision="STUDY_SUFFICIENT",actor_id="h",decided_at="t",rationale="bad")
    def test_rk_and_ri_replacement_stale_history(self):
        v=self.assess();self.service.approve_study(v.version_id,project_id="p",run_id="r",new_version_id="approved",approval_id="sap",expected_fingerprint=v.fingerprint,decision="STUDY_SUFFICIENT",actor_id="h",decided_at="t",rationale="yes");self.current["o1"]=replace(self.current["o1"],approval_fingerprint="new")
        with self.assertRaisesRegex(QuantitativeStudySufficiencyError,"mandatory RI"):self.service.resolve_current_approved_study(project_id="p",run_id="r")
        self.assertIsNotNone(self.repo.get_assessment(v.version_id,project_id="p"))
    def test_dataset_only_and_payload_safety(self):
        x=self.service.dataset_only_absence(project_id="p",run_id="r");self.assertEqual("NO_DESIGN_AWARE_STUDY_SUFFICIENCY_AUTHORITY",x.status);text=repr(self.assess()).lower()
        for word in ("respondent_id","raw_sav","credentials","storage_path"):self.assertNotIn(word,text)

    def test_immutable_replacement_selects_only_approved_lineage_head(self):
        p1,p1_approval=self.policy((self.entry("o1"),self.entry("o2")))
        current,approval=self.service._current_policy("p","r",self.selection,self.chain,self.design)
        self.assertEqual((p1.version_id,p1_approval.approval_id),(current.version_id,approval.approval_id))
        old_assessment=self.service.assess_current_study(project_id="p",run_id="r",created_at="t",created_by="system")
        self.service.approve_study(old_assessment.version_id,project_id="p",run_id="r",new_version_id="old-approved-assessment",approval_id="old-study-approval",expected_fingerprint=old_assessment.fingerprint,decision="STUDY_SUFFICIENT",actor_id="h",decided_at="t",rationale="Historically sufficient")
        marker=self.service.supersede_policy(p1.version_id,project_id="p",run_id="r",new_version_id="p1-superseded",actor_id="h",changed_at="t")
        draft=self.replacement_draft(marker)
        self.assertEqual(p1.version_id,self.service._current_policy("p","r",self.selection,self.chain,self.design)[0].version_id)
        review=self.service.submit_policy_for_review(draft.version_id,project_id="p",run_id="r",new_version_id="replacement-2-review",actor_id="h",changed_at="t")
        self.assertEqual(p1.version_id,self.service._current_policy("p","r",self.selection,self.chain,self.design)[0].version_id)
        p2=self.service.approve_policy(review.version_id,project_id="p",run_id="r",new_version_id="replacement-2-approved",approval_id="replacement-2-approval",expected_fingerprint=review.fingerprint,actor_id="h",decided_at="t",rationale="Approved replacement")
        current,approval=self.service._current_policy("p","r",self.selection,self.chain,self.design)
        self.assertEqual((p2.version_id,"replacement-2-approval"),(current.version_id,approval.approval_id))
        self.assertEqual(StudySufficiencyLifecycle.APPROVED,self.repo.get_policy(p1.version_id,project_id="p").lifecycle_status)
        self.assertEqual(p1_approval,self.repo.get_policy_approval(p1_approval.approval_id,project_id="p"))
        assessment=self.service.assess_current_study(project_id="p",run_id="r",created_at="t2",created_by="system")
        self.assertEqual(("o1",),assessment.mandatory_objective_ids);self.assertEqual(("o2",),assessment.optional_objective_ids)
        with self.assertRaisesRegex(QuantitativeStudySufficiencyError,"missing or ambiguous"):
            self.service.resolve_current_approved_study(project_id="p",run_id="r")

    def test_linear_replacements_and_competing_approved_heads(self):
        p1,_=self.policy((self.entry("o1"),self.entry("o2")))
        marker=self.service.supersede_policy(p1.version_id,project_id="p",run_id="r",new_version_id="linear-marker-1",actor_id="h",changed_at="t")
        _,p2,_=self.approve_replacement(self.replacement_draft(marker,"2"),"2")
        marker2=self.service.supersede_policy(p2.version_id,project_id="p",run_id="r",new_version_id="linear-marker-2",actor_id="h",changed_at="t")
        _,p3,_=self.approve_replacement(self.replacement_draft(marker2,"3"),"3")
        self.assertEqual(p3.version_id,self.service._current_policy("p","r",self.selection,self.chain,self.design)[0].version_id)
        self.assertEqual(StudySufficiencyLifecycle.APPROVED,self.repo.get_policy(p2.version_id,project_id="p").lifecycle_status)
        branch=self.replacement_draft(marker2,"branch")
        self.approve_replacement(branch,"branch")
        with self.assertRaisesRegex(QuantitativeStudySufficiencyError,"missing or ambiguous"):
            self.service._current_policy("p","r",self.selection,self.chain,self.design)

    def test_rejected_child_and_corrupt_or_cross_root_lineage_fail_closed(self):
        p1,_=self.policy((self.entry("o1"),self.entry("o2")))
        marker=self.service.supersede_policy(p1.version_id,project_id="p",run_id="r",new_version_id="reject-marker",actor_id="h",changed_at="t")
        draft=self.replacement_draft(marker,"rejected")
        review=self.service.submit_policy_for_review(draft.version_id,project_id="p",run_id="r",new_version_id="rejected-review",actor_id="h",changed_at="t")
        self.service.reject_policy(review.version_id,project_id="p",run_id="r",new_version_id="rejected-final",actor_id="h",decided_at="t")
        self.assertEqual(p1.version_id,self.service._current_policy("p","r",self.selection,self.chain,self.design)[0].version_id)
        corrupt=replace(draft,version_id="corrupt",parent_version_id="missing",version_sequence=99)
        self.repo.p[corrupt.version_id]=corrupt
        with self.assertRaisesRegex(QuantitativeStudySufficiencyError,"missing parent"):
            self.service._current_policy("p","r",self.selection,self.chain,self.design)
        del self.repo.p[corrupt.version_id]
        other=replace(draft,version_id="cross-root",project_id="other",parent_version_id=p1.version_id)
        self.repo.p[other.version_id]=other
        with self.assertRaisesRegex(QuantitativeStudySufficiencyError,"crosses authority roots"):
            self.service._current_policy("p","r",self.selection,self.chain,self.design)

if __name__=="__main__":unittest.main()
