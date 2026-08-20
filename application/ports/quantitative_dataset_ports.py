from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from domain.quantitative.dataset import DatasetFormat, DatasetVersion


@dataclass(frozen=True)
class ParsedVariable:
    name: str
    label: str = ""
    storage_type: str = "unknown"
    measurement_level: str = "unknown"
    value_labels: tuple[tuple[Any, str], ...] = ()
    user_missing: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDataset:
    format: DatasetFormat
    variables: tuple[ParsedVariable, ...]
    rows: tuple[tuple[Any, ...], ...]
    parser_name: str
    parser_version: str
    warnings: tuple[str, ...] = ()


class QuantitativeDatasetImporter(Protocol):
    format: DatasetFormat

    def parse(
        self,
        data: bytes,
        *,
        filename: str,
        data_sheet: str | None = None,
    ) -> ParsedDataset:
        ...


class DatasetStorage(Protocol):
    def put_raw_file(self, source_file_id: str, data: bytes) -> str:
        ...

    def get_raw_file(self, source_file_id: str) -> bytes:
        ...

    def put_parsed_rows(
        self,
        version_id: str,
        rows: tuple[tuple[Any, ...], ...],
    ) -> str:
        ...

    def get_parsed_rows(self, version_id: str) -> tuple[tuple[Any, ...], ...]:
        ...

    def put_manifest(self, version: DatasetVersion) -> None:
        ...

    def get_manifest(self, version_id: str) -> DatasetVersion:
        ...
