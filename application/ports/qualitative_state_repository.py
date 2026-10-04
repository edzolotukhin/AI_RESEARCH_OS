from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualitativeStateRecord:
    record_id: str
    project_id: str
    run_id: str
    record_type: str
    payload: dict
    checksum: str
    parent_record_id: str | None = None


class QualitativeStateRepository:
    def create(self, record: QualitativeStateRecord) -> None: ...
    def get_for_project(self, record_id: str, *, project_id: str): ...
    def list_for_run(self, run_id: str, *, project_id: str, record_type: str | None = None): ...
    def list_by_type(self, record_type: str): ...
