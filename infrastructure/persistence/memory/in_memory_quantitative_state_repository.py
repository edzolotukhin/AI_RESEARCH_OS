from __future__ import annotations

import copy

from application.ports.quantitative_state_repository import QuantitativeStateRecord


class InMemoryQuantitativeStateRepository:
    def __init__(self) -> None: self._records = {}
    def create(self, record: QuantitativeStateRecord) -> None:
        if record.record_id in self._records: raise ValueError("immutable Quantitative record already exists")
        self._records[record.record_id] = copy.deepcopy(record)
    def get_for_project(self, record_id: str, *, project_id: str):
        value = self._records.get(record_id)
        return copy.deepcopy(value) if value is not None and value.project_id == project_id else None
    def list_for_run(self, run_id: str, *, project_id: str, record_type: str | None = None):
        return tuple(copy.deepcopy(value) for _, value in sorted(self._records.items()) if value.run_id == run_id and value.project_id == project_id and (record_type is None or value.record_type == record_type))
