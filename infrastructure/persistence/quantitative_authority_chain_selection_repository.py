from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.authority_chain import QuantitativeCurrentAuthorityChainSelection

class QLQuantitativeAuthorityChainSelectionRepository:
    def __init__(self, state_service): self._state = state_service
    def save_selection(self, value):
        try:
            self._state.persist(value, record_id=value.selection_id, project_id=value.project_id, run_id=value.run_id, accepted=True)
            return value
        except ValueError:
            existing=self.get_selection(value.selection_id,project_id=value.project_id)
            if existing!=value: raise QuantitativePersistenceError("conflicting deterministic authority-chain selection")
            return existing
    def get_selection(self, selection_id, *, project_id):
        try: return self._state.load(selection_id,project_id=project_id,expected_type=QuantitativeCurrentAuthorityChainSelection)
        except QuantitativePersistenceError as exc:
            if "unavailable for project" in str(exc): return None
            raise
    def list_selections(self, *, project_id, run_id):
        record_type = f"{QuantitativeCurrentAuthorityChainSelection.__module__}.{QuantitativeCurrentAuthorityChainSelection.__qualname__}"
        records = self._state._repository.list_for_run(run_id, project_id=project_id, record_type=record_type)
        return tuple(self._state.load(record.record_id, project_id=project_id, expected_type=QuantitativeCurrentAuthorityChainSelection) for record in records)
