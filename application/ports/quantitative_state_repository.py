from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class QuantitativeStateRecord:
    record_id: str
    project_id: str
    run_id: str
    record_type: str
    payload: dict[str, Any]
    payload_checksum: str
    authority_fingerprint: str
    dataset_version_id: str | None = None
    parent_record_id: str | None = None
    accepted: bool | None = None
    codec_version: str = "ql-1"


class QuantitativeStateRepository(Protocol):
    def create(self, record: QuantitativeStateRecord) -> None: ...
    def get_for_project(self, record_id: str, *, project_id: str) -> QuantitativeStateRecord | None: ...
    def list_for_run(self, run_id: str, *, project_id: str, record_type: str | None = None) -> tuple[QuantitativeStateRecord, ...]: ...
