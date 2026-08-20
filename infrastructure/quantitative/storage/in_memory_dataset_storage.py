from __future__ import annotations

import copy

from application.ports.quantitative_dataset_ports import DatasetStorage
from domain.quantitative.dataset import DatasetVersion


class InMemoryDatasetStorage(DatasetStorage):
    """Deterministic test adapter; never stores respondent data in task JSON."""

    def __init__(self) -> None:
        self._raw_files: dict[str, bytes] = {}
        self._rows: dict[str, tuple[tuple[object, ...], ...]] = {}
        self._manifests: dict[str, DatasetVersion] = {}
        self._lineage: dict[str, tuple[str, ...]] = {}
        self._protected_bindings: dict[str, tuple[tuple[str, str], ...]] = {}

    def put_raw_file(self, source_file_id: str, data: bytes) -> str:
        existing = self._raw_files.get(source_file_id)
        if existing is not None and existing != data:
            raise ValueError("immutable raw file identity collision")
        self._raw_files[source_file_id] = bytes(data)
        return f"memory-dataset://raw/{source_file_id}"

    def get_raw_file(self, source_file_id: str) -> bytes:
        return bytes(self._raw_files[source_file_id])

    def put_parsed_rows(
        self,
        version_id: str,
        rows: tuple[tuple[object, ...], ...],
    ) -> str:
        snapshot = copy.deepcopy(rows)
        existing = self._rows.get(version_id)
        if existing is not None and existing != snapshot:
            raise ValueError("immutable dataset version collision")
        self._rows[version_id] = snapshot
        return f"memory-dataset://parsed/{version_id}"

    def get_parsed_rows(self, version_id: str) -> tuple[tuple[object, ...], ...]:
        return copy.deepcopy(self._rows[version_id])

    def put_respondent_lineage(self, version_id: str, refs: tuple[str, ...]) -> None:
        snapshot = tuple(refs)
        existing = self._lineage.get(version_id)
        if existing is not None and existing != snapshot:
            raise ValueError("immutable respondent lineage collision")
        self._lineage[version_id] = snapshot

    def get_respondent_lineage(self, version_id: str) -> tuple[str, ...]:
        return tuple(self._lineage[version_id])

    def put_protected_respondent_bindings(
        self,
        version_id: str,
        bindings: tuple[tuple[str, str], ...],
    ) -> None:
        snapshot = tuple(bindings)
        existing = self._protected_bindings.get(version_id)
        if existing is not None and existing != snapshot:
            raise ValueError("immutable protected respondent binding collision")
        self._protected_bindings[version_id] = snapshot

    def get_protected_respondent_bindings(
        self,
        version_id: str,
    ) -> tuple[tuple[str, str], ...]:
        return tuple(self._protected_bindings.get(version_id, ()))

    def put_manifest(self, version: DatasetVersion) -> None:
        existing = self._manifests.get(version.version_id)
        if existing is not None and existing != version:
            raise ValueError("immutable dataset manifest collision")
        self._manifests[version.version_id] = copy.deepcopy(version)

    def get_manifest(self, version_id: str) -> DatasetVersion:
        return copy.deepcopy(self._manifests[version_id])
