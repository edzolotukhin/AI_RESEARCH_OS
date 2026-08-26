from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.analysis_execution import *
class QLQuantitativeAnalysisExecutionRepository:
    def __init__(self,state_service): self._state=state_service
    def _save(self,value,record_id,run_id,expected):
        try:self._state.persist(value,record_id=record_id,project_id=value.project_id,run_id=run_id,accepted=True);return value
        except ValueError:
            existing=self._state.load(record_id,project_id=value.project_id,expected_type=expected)
            if existing!=value: raise QuantitativePersistenceError("conflicting deterministic Quantitative execution authority")
            return existing
    def save_analysis_outcome(self,value): return self._save(value,value.outcome_id,value.run_id,PlannedAnalysisExecutionOutcome)
    def save_comparison_outcome(self,value): return self._save(value,value.outcome_id,value.run_id,PlannedComparisonExecutionOutcome)
    def save_coverage(self,value): return self._save(value,value.coverage_id,value.run_id,AnalysisExecutionCoverageManifest)
    def save_manifest(self,value): return self._save(value,value.manifest_id,value.run_id,QuantitativeAnalysisExecutionManifest)
    def _get(self,record_id,project_id,expected):
        try:return self._state.load(record_id,project_id=project_id,expected_type=expected)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc): return None
            raise
    def get_analysis_outcome(self,outcome_id,*,project_id): return self._get(outcome_id,project_id,PlannedAnalysisExecutionOutcome)
    def get_comparison_outcome(self,outcome_id,*,project_id): return self._get(outcome_id,project_id,PlannedComparisonExecutionOutcome)
    def get_coverage(self,coverage_id,*,project_id): return self._get(coverage_id,project_id,AnalysisExecutionCoverageManifest)
    def get_manifest(self,manifest_id,*,project_id): return self._get(manifest_id,project_id,QuantitativeAnalysisExecutionManifest)
