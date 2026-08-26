import unittest
from dataclasses import replace
from types import SimpleNamespace as NS

from application.quantitative.research_question_coverage import (
    QuantitativeResearchQuestionCoverageError,
    QuantitativeResearchQuestionCoverageService,
)
from domain.quantitative.research_design_authority import RequirementObligation
from domain.quantitative.research_question_coverage import (
    ResearchQuestionAssessmentStatus,
    ResearchQuestionCoverageDecision,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from application.quantitative.state_persistence import QuantitativePersistenceError, QuantitativeStateService
from infrastructure.persistence.memory.in_memory_quantitative_state_repository import InMemoryQuantitativeStateRepository
from infrastructure.persistence.quantitative_research_question_coverage_repository import QLQuantitativeResearchQuestionCoverageRepository


class MemoryRepository:
    def __init__(self): self.assessments={}; self.approvals={}; self.absences={}
    def save_assessment(self,v):
        old=self.assessments.get(v.version_id)
        if old is not None and old != v: raise ValueError("conflict")
        self.assessments[v.version_id]=v; return v
    def get_assessment(self,k,*,project_id):
        v=self.assessments.get(k); return v if v is None or v.project_id==project_id else None
    def list_assessments(self,*,project_id,run_id): return tuple(v for v in self.assessments.values() if (v.project_id,v.run_id)==(project_id,run_id))
    def save_approval(self,v): self.approvals[v.approval_id]=v; return v
    def get_approval(self,k,*,project_id):
        v=self.approvals.get(k); return v if v is None or v.project_id==project_id else None
    def save_dataset_only_absence(self,v): self.absences[v.absence_id]=v; return v


class PropertyRHTests(unittest.TestCase):
    def setUp(self):
        self.repo=MemoryRepository(); self.service=QuantitativeResearchQuestionCoverageService(repository=self.repo,digest_provider=Sha256DigestProvider())
        rq=NS(question_id="rq-1",statement="Does satisfaction differ?",objective_ids=("obj-1",))
        req=NS(requirement_id="ar-1",research_question_ids=("rq-1",),obligation=RequirementObligation.MANDATORY)
        self.design=NS(project_id="p",version_id="qz-v1",fingerprint="qz-fp",research_questions=(rq,),analytical_requirements=(req,))
        self.ra=NS(project_id="p",research_design_version_id="qz-v1",research_design_fingerprint="qz-fp",requirements=(NS(requirement_id="ar-1",status=NS(value="MEASURED")),),fingerprint="ra-fp")
        self.rb=NS(project_id="p",reconciliation_fingerprint="rb-fp",requirements=(NS(requirement_id="ar-1",status=NS(value="DATA_MEASUREMENT_AVAILABLE")),),fingerprint="rb-availability-fp")
        self.plan=NS(project_id="p",version_id="rc-v1",fingerprint="rc-fp",research_design_version_id="qz-v1",research_design_fingerprint="qz-fp",reconciliation_fingerprint="rb-fp",coverage_manifest_id="rc-cov",coverage_manifest_fingerprint="rc-cov-fp")
        self.rc=NS(project_id="p",manifest_id="rc-cov",plan_version_id="rc-v1",requirements=(NS(requirement_id="ar-1",status=NS(value="PLANNED_EXECUTABLE")),),fingerprint="rc-cov-fp")
        self.rd=NS(project_id="p",run_id="r",execution_mode="DESIGN_AWARE_EXECUTION",plan_version_id="rc-v1",plan_fingerprint="rc-fp",coverage_manifest_id="rd-cov",coverage_manifest_fingerprint="rd-cov-fp",fingerprint="rd-fp")
        self.rd_cov=NS(project_id="p",run_id="r",coverage_id="rd-cov",entries=(NS(planned_item_id="pa-1",outcome_id="out-1",analytical_requirement_ids=("ar-1",),status=NS(value="EXECUTED_WITH_RESULTS")),),fingerprint="rd-cov-fp")
        self.re=NS(project_id="p",run_id="r",entries=(NS(analytical_requirement_id="ar-1",status=NS(value="FINDING_SUPPORTED"),finding_ids=("f-1",)),),fingerprint="re-fp")

    def assess(self,**changes):
        values=dict(project_id="p",run_id="r",design=self.design,questionnaire_coverage=self.ra,data_availability=self.rb,plan=self.plan,plan_coverage=self.rc,execution_manifest=self.rd,execution_coverage=self.rd_cov,finding_coverage=self.re,created_at="2026-01-01T00:00:00Z",created_by="system")
        values.update(changes); return self.service.assess(**values)[0]

    def test_ready_requires_human_approval(self):
        value=self.assess()
        self.assertEqual(ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW,value.status)
        approved=self.service.approve(value.version_id,project_id="p",run_id="r",new_version_id="rh-approved",approval_id="a-1",expected_fingerprint=value.fingerprint,decision=ResearchQuestionCoverageDecision.SUFFICIENTLY_ANSWERED,actor_id="human",decided_at="2026-01-02T00:00:00Z",rationale="Evidence is sufficient.")
        projection=self.service.resolve_current_approved(project_id="p",run_id="r",research_question_id="rq-1",upstream_authority_fingerprints=approved.upstream_authority_fingerprints)
        self.assertEqual(ResearchQuestionCoverageDecision.SUFFICIENTLY_ANSWERED,projection.decision)

    def test_upstream_blocker_is_not_approvable(self):
        rb=NS(**{**vars(self.rb),"requirements":(NS(requirement_id="ar-1",status=NS(value="MISSING_IN_DATA")),)})
        value=self.assess(data_availability=rb)
        self.assertEqual(ResearchQuestionAssessmentStatus.BLOCKED,value.status)
        with self.assertRaisesRegex(QuantitativeResearchQuestionCoverageError,"blocked"):
            self.service.approve(value.version_id,project_id="p",run_id="r",new_version_id="x",approval_id="a",expected_fingerprint=value.fingerprint,decision="NOT_ANSWERED",actor_id="human",decided_at="now",rationale="blocked")

    def test_no_supported_finding_is_not_answered(self):
        re=NS(**{**vars(self.re),"entries":(NS(analytical_requirement_id="ar-1",status=NS(value="NO_FINDING_PROPOSED"),finding_ids=()),)})
        self.assertEqual(ResearchQuestionAssessmentStatus.NOT_ANSWERED,self.assess(finding_coverage=re).status)

    def test_non_significance_is_inconclusive_not_execution_failure(self):
        value=self.assess(non_significant_outcome_ids=("out-1",))
        self.assertEqual(ResearchQuestionAssessmentStatus.REQUIRES_METHODOLOGICAL_REVIEW,value.status)

    def test_insight_and_report_are_informational(self):
        rf=NS(project_id="p",run_id="r",entries=(NS(analytical_requirement_id="ar-1",status=NS(value="NO_INSIGHT_PROPOSED"),insight_ids=()),),fingerprint="rf")
        rg=NS(project_id="p",run_id="r",entries=(NS(analytical_requirement_id="ar-1",status=NS(value="REPORT_PROPOSAL_REJECTED"),section_ids=()),),fingerprint="rg")
        self.assertEqual(ResearchQuestionAssessmentStatus.READY_FOR_SUFFICIENCY_REVIEW,self.assess(insight_coverage=rf,report_coverage=rg).status)

    def test_stale_or_wrong_scope_fails_closed(self):
        with self.assertRaisesRegex(QuantitativeResearchQuestionCoverageError,"wrong-project"):
            self.assess(design=NS(**{**vars(self.design),"project_id":"other"}))
        with self.assertRaisesRegex(QuantitativeResearchQuestionCoverageError,"stale QZ/RC"):
            self.assess(plan=NS(**{**vars(self.plan),"research_design_fingerprint":"stale"}))

    def test_ql_restart_and_corruption_fail_closed(self):
        records=InMemoryQuantitativeStateRepository()
        state=QuantitativeStateService(repository=records,digest_provider=Sha256DigestProvider())
        first=QuantitativeResearchQuestionCoverageService(repository=QLQuantitativeResearchQuestionCoverageRepository(state),digest_provider=Sha256DigestProvider())
        value=first.dataset_only_absence(project_id="p",run_id="r")
        second=QLQuantitativeResearchQuestionCoverageRepository(state)
        self.assertEqual(value,second._state.load(value.absence_id,project_id="p"))
        record=records._records[value.absence_id]
        records._records[value.absence_id]=replace(record,payload_checksum="corrupt")
        with self.assertRaisesRegex(QuantitativePersistenceError,"checksum"):
            second._state.load(value.absence_id,project_id="p")
    def test_dataset_only_absence_has_no_design_claim(self):
        value=self.service.dataset_only_absence(project_id="p",run_id="r")
        self.assertEqual("NO_DESIGN_AWARE_RQ_COVERAGE",value.status)


if __name__ == "__main__": unittest.main()
