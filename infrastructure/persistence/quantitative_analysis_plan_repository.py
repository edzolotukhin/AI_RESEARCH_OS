from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.analysis_plan import *

class QLQuantitativeAnalysisPlanRepository:
    def __init__(self,state_service): self._state=state_service
    def save_plan(self,value,*,run_id): self._state.persist(value,record_id=value.version_id,project_id=value.project_id,run_id=run_id,parent_record_id=value.parent_version_id,accepted=value.lifecycle_status is AnalysisPlanLifecycle.APPROVED)
    def save_coverage(self,value,*,run_id): self._state.persist(value,record_id=value.manifest_id,project_id=value.project_id,run_id=run_id,parent_record_id=value.plan_version_id)
    def save_approval(self,value,*,run_id): self._state.persist(value,record_id=value.approval_id,project_id=value.project_id,run_id=run_id,parent_record_id=value.plan_version_id,accepted=value.decision is AnalysisPlanApprovalDecision.APPROVED)
    def save_dataset_only(self,value): self._state.persist(value,record_id=value.authority_id,project_id=value.project_id,run_id=value.run_id,accepted=True)
    def _load(self,record_id,project_id,expected):
        try:return self._state.load(record_id,project_id=project_id,expected_type=expected)
        except QuantitativePersistenceError as exc:
            if 'unavailable for project' in str(exc): return None
            raise
    def get_plan(self,version_id,*,project_id): return self._load(version_id,project_id,QuantitativeAnalysisPlanVersion)
    def get_coverage(self,manifest_id,*,project_id): return self._load(manifest_id,project_id,QuantitativeAnalysisPlanCoverageManifest)
    def get_approval(self,approval_id,*,project_id): return self._load(approval_id,project_id,QuantitativeAnalysisPlanApproval)
    def list_plans(self,*,project_id,run_id): return tuple(sorted(self._state.list_for_run(run_id,project_id=project_id,expected_type=QuantitativeAnalysisPlanVersion),key=lambda x:x.version_sequence))
