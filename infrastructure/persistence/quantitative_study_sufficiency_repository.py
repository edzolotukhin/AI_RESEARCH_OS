from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.study_sufficiency import *

class QLQuantitativeStudySufficiencyRepository:
    def __init__(self,state_service): self._state=state_service
    def _save(self,v,k,t):
        try: self._state.persist(v,record_id=k,project_id=v.project_id,run_id=v.run_id,accepted=True); return v
        except ValueError:
            old=self._get(k,v.project_id,t)
            if old!=v: raise QuantitativePersistenceError("conflicting deterministic Study sufficiency authority")
            return old
    def _get(self,k,p,t):
        try:return self._state.load(k,project_id=p,expected_type=t)
        except QuantitativePersistenceError as e:
            if "unavailable for project" in str(e):return None
            raise
    def save_policy(self,v):return self._save(v,v.version_id,QuantitativeStudyObjectiveObligationPolicyVersion)
    def get_policy(self,k,*,project_id):return self._get(k,project_id,QuantitativeStudyObjectiveObligationPolicyVersion)
    def _list(self,run_id,project_id,t):
        record_type=f"{t.__module__}.{t.__qualname__}"
        records=self._state._repository.list_for_run(run_id,project_id=project_id,record_type=record_type)
        return tuple(self._state.load(x.record_id,project_id=project_id,expected_type=t) for x in records)
    def list_policies(self,*,project_id,run_id):return tuple(sorted(self._list(run_id,project_id,QuantitativeStudyObjectiveObligationPolicyVersion),key=lambda x:x.version_sequence))
    def save_policy_approval(self,v):return self._save(v,v.approval_id,QuantitativeStudyObjectiveObligationPolicyApproval)
    def get_policy_approval(self,k,*,project_id):return self._get(k,project_id,QuantitativeStudyObjectiveObligationPolicyApproval)
    def save_assessment(self,v):return self._save(v,v.version_id,QuantitativeStudySufficiencyAssessmentVersion)
    def get_assessment(self,k,*,project_id):return self._get(k,project_id,QuantitativeStudySufficiencyAssessmentVersion)
    def list_assessments(self,*,project_id,run_id):return tuple(sorted(self._list(run_id,project_id,QuantitativeStudySufficiencyAssessmentVersion),key=lambda x:x.version_sequence))
    def save_approval(self,v):return self._save(v,v.approval_id,QuantitativeStudySufficiencyApproval)
    def get_approval(self,k,*,project_id):return self._get(k,project_id,QuantitativeStudySufficiencyApproval)
    def save_dataset_only_absence(self,v):return self._save(v,v.absence_id,DatasetOnlyStudySufficiencyAbsence)
