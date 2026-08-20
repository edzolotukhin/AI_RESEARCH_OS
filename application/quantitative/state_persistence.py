from __future__ import annotations

from dataclasses import fields, is_dataclass
import base64
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_state_repository import QuantitativeStateRecord, QuantitativeStateRepository
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.fingerprints import fingerprint_codebook, fingerprint_data, fingerprint_dataset, fingerprint_schema, sha256_bytes
from domain.quantitative.dataset import CodebookVersion, DatasetVersion
from domain.quantitative.weighting import WeightSet
from domain.quantitative.analysis import StatisticalResult


class QuantitativePersistenceError(ValueError):
    pass


def _classes() -> dict[str, type]:
    from domain.quantitative import analysis, dataset, finding, insight, quality, report, weighting, workflow
    result = {}
    for module in (analysis, dataset, finding, insight, quality, report, weighting, workflow):
        for value in vars(module).values():
            if isinstance(value, type) and (is_dataclass(value) or issubclass(value, Enum)):
                result[f"{value.__module__}.{value.__qualname__}"] = value
    return result


_ALLOWED = _classes()


def encode_quantitative(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise QuantitativePersistenceError("non-finite float cannot be persisted")
        return {"$float": repr(value)}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, time):
        return {"$time": value.isoformat()}
    if isinstance(value, Enum):
        return {"$enum": f"{type(value).__module__}.{type(value).__qualname__}", "value": value.value}
    if is_dataclass(value):
        name = f"{type(value).__module__}.{type(value).__qualname__}"
        if name not in _ALLOWED:
            raise QuantitativePersistenceError(f"unsupported persisted type: {name}")
        return {"$type": name, "fields": {item.name: encode_quantitative(getattr(value, item.name)) for item in fields(value)}}
    if isinstance(value, tuple):
        return {"$tuple": [encode_quantitative(item) for item in value]}
    if isinstance(value, list):
        return {"$list": [encode_quantitative(item) for item in value]}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise QuantitativePersistenceError("persisted mappings require string keys")
        return {"$map": {key: encode_quantitative(item) for key, item in sorted(value.items())}}
    raise QuantitativePersistenceError(f"unsupported persisted value: {type(value)!r}")


def decode_quantitative(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if not isinstance(value, dict) or len(value) != 1 and "$type" not in value and "$enum" not in value:
        raise QuantitativePersistenceError("invalid persisted Quantitative payload")
    if "$float" in value: return float(value["$float"])
    if "$decimal" in value: return Decimal(value["$decimal"])
    if "$bytes" in value: return base64.b64decode(value["$bytes"], validate=True)
    if "$datetime" in value: return datetime.fromisoformat(value["$datetime"])
    if "$date" in value: return date.fromisoformat(value["$date"])
    if "$time" in value: return time.fromisoformat(value["$time"])
    if "$tuple" in value: return tuple(decode_quantitative(item) for item in value["$tuple"])
    if "$list" in value: return [decode_quantitative(item) for item in value["$list"]]
    if "$map" in value: return {key: decode_quantitative(item) for key, item in value["$map"].items()}
    if "$enum" in value:
        cls = _ALLOWED.get(value["$enum"])
        if cls is None or not issubclass(cls, Enum): raise QuantitativePersistenceError("unapproved enum type")
        return cls(value["value"])
    cls = _ALLOWED.get(value.get("$type"))
    if cls is None or not is_dataclass(cls): raise QuantitativePersistenceError("unapproved dataclass type")
    return cls(**{key: decode_quantitative(item) for key, item in value["fields"].items()})


def authority_fingerprint(value: Any) -> str:
    if isinstance(value, DatasetVersion):
        return value.dataset_fingerprint
    if isinstance(value, WeightSet):
        return value.reproducibility_fingerprint
    if isinstance(value, StatisticalResult):
        return value.reproducibility_fingerprint
    for name in ("support_validation_fingerprint", "validation_fingerprint", "generation_fingerprint", "composition_fingerprint", "rejection_fingerprint", "reproducibility_fingerprint", "fingerprint"):
        result = getattr(value, name, None)
        if isinstance(result, str) and result:
            return result
    raise QuantitativePersistenceError("object has no authoritative fingerprint")


class QuantitativeStateService:
    def __init__(self, *, repository: QuantitativeStateRepository, digest_provider: DeterministicDigestProvider) -> None:
        self._repository = repository
        self._digest = digest_provider

    def persist(self, value: Any, *, record_id: str, project_id: str, run_id: str, dataset_version_id: str | None = None, parent_record_id: str | None = None, accepted: bool | None = None) -> QuantitativeStateRecord:
        payload = encode_quantitative(value)
        checksum = canonical_digest(payload, digest_provider=self._digest)
        record = QuantitativeStateRecord(record_id, project_id, run_id, f"{type(value).__module__}.{type(value).__qualname__}", payload, checksum, authority_fingerprint(value), dataset_version_id, parent_record_id, accepted)
        self._repository.create(record)
        return record

    def load(self, record_id: str, *, project_id: str, expected_type: type | None = None) -> Any:
        record = self._repository.get_for_project(record_id, project_id=project_id)
        if record is None: raise QuantitativePersistenceError("Quantitative record is unavailable for project")
        if canonical_digest(record.payload, digest_provider=self._digest) != record.payload_checksum:
            raise QuantitativePersistenceError("Quantitative payload checksum mismatch")
        value = decode_quantitative(record.payload)
        if expected_type is not None and not isinstance(value, expected_type): raise QuantitativePersistenceError("Quantitative record type mismatch")
        if authority_fingerprint(value) != record.authority_fingerprint: raise QuantitativePersistenceError("Quantitative authority fingerprint mismatch")
        return value

    def list_for_run(self, run_id: str, *, project_id: str, expected_type: type | None = None) -> tuple[Any, ...]:
        values = []
        for record in self._repository.list_for_run(run_id, project_id=project_id):
            try:
                value = self.load(record.record_id, project_id=project_id, expected_type=expected_type)
            except QuantitativePersistenceError:
                if expected_type is None:
                    raise
                continue
            values.append(value)
        return tuple(values)


def validate_recovered_dataset(*, dataset: DatasetVersion, codebook: CodebookVersion, storage, digest_provider: DeterministicDigestProvider) -> None:
    raw = storage.get_raw_file(dataset.source_file_id)
    rows = storage.get_parsed_rows(dataset.version_id)
    file_checksum = sha256_bytes(raw, digest_provider=digest_provider)
    codebook_fp = fingerprint_codebook(codebook.variables, digest_provider=digest_provider)
    schema_fp = fingerprint_schema(codebook.variables, digest_provider=digest_provider)
    data_fp = fingerprint_data(rows, digest_provider=digest_provider)
    dataset_fp = fingerprint_dataset(file_checksum=file_checksum, schema_fingerprint=schema_fp, codebook_fingerprint=codebook_fp, data_fingerprint=data_fp, digest_provider=digest_provider)
    observed = (file_checksum, schema_fp, codebook_fp, data_fp, dataset_fp, codebook.codebook_version_id)
    expected = (dataset.file_checksum, dataset.schema_fingerprint, dataset.codebook_fingerprint, dataset.data_fingerprint, dataset.dataset_fingerprint, dataset.codebook_version_id)
    if observed != expected or codebook.fingerprint != codebook_fp:
        raise QuantitativePersistenceError("recovered DatasetVersion authority mismatch")


def validate_recovered_analysis_linkage(*, dataset: DatasetVersion, weight_set: WeightSet | None = None, result: StatisticalResult | None = None) -> None:
    if weight_set is not None and (weight_set.dataset_version_id != dataset.version_id or weight_set.dataset_fingerprint != dataset.dataset_fingerprint):
        raise QuantitativePersistenceError("recovered WeightSet is stale for DatasetVersion")
    if result is not None and (result.dataset_version_id != dataset.version_id or result.dataset_fingerprint != dataset.dataset_fingerprint or result.data_fingerprint != dataset.data_fingerprint or result.codebook_fingerprint != dataset.codebook_fingerprint):
        raise QuantitativePersistenceError("recovered StatisticalResult is stale for DatasetVersion")
