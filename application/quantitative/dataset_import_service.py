from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.quantitative_dataset_ports import (
    DatasetStorage,
    ParsedDataset,
    QuantitativeDatasetImporter,
)
from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import (
    canonical_scalar,
    fingerprint_codebook,
    fingerprint_data,
    fingerprint_dataset,
    fingerprint_schema,
    fingerprint_variable,
    sha256_bytes,
)
from domain.quantitative.dataset import (
    CodebookVersion,
    DatasetFormat,
    DatasetVersion,
    DatasetVersionKind,
    MissingValueRule,
    PiiClassification,
    ValidationStatus,
    VariableDefinition,
    VariableRole,
    VariableType,
)


class QuantitativeImportError(ValueError):
    pass


@dataclass(frozen=True)
class VariableOverride:
    variable_type: VariableType | None = None
    role: VariableRole | None = None
    label: str | None = None
    value_labels: tuple[tuple[Any, str], ...] | None = None
    missing_values: tuple[Any, ...] = ()
    pii_classification: PiiClassification | None = None
    imported_missing_values_declared_valid: tuple[Any, ...] = ()


@dataclass(frozen=True)
class QuantitativeImportResult:
    dataset_version: DatasetVersion
    codebook: CodebookVersion
    analytical_respondent_ids: tuple[str, ...]


class QuantitativeDatasetImportService:
    def __init__(
        self,
        *,
        importers: tuple[QuantitativeDatasetImporter, ...],
        storage: DatasetStorage,
        digest_provider: DeterministicDigestProvider,
    ) -> None:
        self._importers = {item.format: item for item in importers}
        self._storage = storage
        self._digest_provider = digest_provider

    def import_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        dataset_format: DatasetFormat,
        dataset_id: str,
        project_id: str,
        run_id: str,
        data_sheet: str | None = None,
        overrides: dict[str, VariableOverride] | None = None,
        parent_dataset: DatasetVersion | None = None,
    ) -> QuantitativeImportResult:
        if not data:
            raise QuantitativeImportError("dataset bytes are empty")
        importer = self._importers.get(dataset_format)
        if importer is None:
            raise QuantitativeImportError(f"no importer for {dataset_format.value}")
        if parent_dataset is not None and (
            parent_dataset.dataset_id != dataset_id
            or parent_dataset.project_id != project_id
            or parent_dataset.run_id != run_id
        ):
            raise QuantitativeImportError(
                "replacement parent does not match dataset project/run authority"
            )
        parsed = importer.parse(data, filename=filename, data_sheet=data_sheet)
        variables = self._build_variables(
            parsed,
            overrides or {},
            digest_provider=self._digest_provider,
        )
        self._validate_unique_names(variables)

        file_checksum = sha256_bytes(data, digest_provider=self._digest_provider)
        source_file_id = str(uuid5(NAMESPACE_URL, f"qa-file:{file_checksum}"))
        codebook_version_id = str(
            uuid5(
                NAMESPACE_URL,
                f"qa-codebook:{dataset_id}:"
                f"{fingerprint_codebook(variables, digest_provider=self._digest_provider)}",
            )
        )
        codebook_fingerprint = fingerprint_codebook(
            variables,
            digest_provider=self._digest_provider,
        )
        codebook = CodebookVersion(
            codebook_version_id=codebook_version_id,
            variables=variables,
            fingerprint=codebook_fingerprint,
        )
        schema_fingerprint = fingerprint_schema(
            variables,
            digest_provider=self._digest_provider,
        )
        data_fingerprint = fingerprint_data(
            parsed.rows,
            digest_provider=self._digest_provider,
        )
        dataset_fingerprint = fingerprint_dataset(
            file_checksum=file_checksum,
            schema_fingerprint=schema_fingerprint,
            codebook_fingerprint=codebook_fingerprint,
            data_fingerprint=data_fingerprint,
            digest_provider=self._digest_provider,
        )
        version_id = str(
            uuid5(NAMESPACE_URL, f"qa-dataset:{dataset_id}:{dataset_fingerprint}")
        )

        technical_index = self._technical_id_index(variables)
        analytical_ids, binding_supported, protected_bindings = self._respondent_ids(
            dataset_id=dataset_id,
            file_checksum=file_checksum,
            rows=parsed.rows,
            technical_index=technical_index,
            digest_provider=self._digest_provider,
        )
        pii_status = self._pii_status(variables)
        validation_status = self._validation_status(variables, parsed.warnings)
        raw_locator = self._storage.put_raw_file(source_file_id, data)
        self._storage.put_parsed_rows(version_id, parsed.rows)
        self._storage.put_respondent_lineage(version_id, analytical_ids)
        self._storage.put_protected_respondent_bindings(version_id, protected_bindings)
        version = DatasetVersion(
            dataset_id=dataset_id,
            version_id=version_id,
            project_id=project_id,
            run_id=run_id,
            version_kind=DatasetVersionKind.RAW,
            source_file_id=source_file_id,
            original_filename=filename,
            file_checksum=file_checksum,
            format=dataset_format,
            row_count=len(parsed.rows),
            variable_count=len(variables),
            schema_fingerprint=schema_fingerprint,
            codebook_version_id=codebook_version_id,
            codebook_fingerprint=codebook_fingerprint,
            data_fingerprint=data_fingerprint,
            dataset_fingerprint=dataset_fingerprint,
            pii_classification_status=pii_status,
            validation_status=validation_status,
            storage_locator=raw_locator,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            warnings=parsed.warnings,
            respondent_identity_kind=(
                "technical_id_pseudonym" if binding_supported else "generated_pseudonym"
            ),
            weight_set_binding_supported=binding_supported,
            parent_version_id=(
                parent_dataset.version_id if parent_dataset is not None else None
            ),
            parent_dataset_fingerprint=(
                parent_dataset.dataset_fingerprint
                if parent_dataset is not None
                else None
            ),
        )
        self._storage.put_manifest(version)
        return QuantitativeImportResult(version, codebook, analytical_ids)

    @staticmethod
    def _build_variables(
        parsed: ParsedDataset,
        overrides: dict[str, VariableOverride],
        *,
        digest_provider: DeterministicDigestProvider,
    ) -> tuple[VariableDefinition, ...]:
        variables: list[VariableDefinition] = []
        for ordinal, raw in enumerate(parsed.variables):
            override = overrides.get(raw.name, VariableOverride())
            inferred_type = _infer_type(raw, parsed.rows, ordinal)
            variable_type = override.variable_type or inferred_type
            role = override.role or _infer_role(raw.name, raw.label, variable_type)
            pii = override.pii_classification or _infer_pii(raw.name, raw.label, role)
            if pii is PiiClassification.PII_RESTRICTED:
                variable_type = VariableType.PII
                role = VariableRole.PII

            imported_rules = tuple(_missing_rule_from_payload(item) for item in raw.user_missing)
            codebook_rules = tuple(
                MissingValueRule(kind="value", value=value, source="codebook")
                for value in override.missing_values
            )
            conflicts = [
                value
                for value in override.imported_missing_values_declared_valid
                if _matches_any_rule(value, imported_rules)
            ]
            messages: list[str] = []
            status = ValidationStatus.VALID
            if raw.metadata.get("mixed_types"):
                if override.variable_type is None:
                    status = ValidationStatus.BLOCKED
                    messages.append("mixed_types_unresolved")
                else:
                    status = ValidationStatus.VALID_WITH_WARNINGS
                    messages.append("mixed_types_resolved_by_explicit_mapping")
            if conflicts:
                status = ValidationStatus.BLOCKED
                messages.append("missing_value_semantics_conflict")

            variable = VariableDefinition(
                variable_id=f"var-{ordinal + 1}-{raw.name}",
                name=raw.name,
                label=override.label if override.label is not None else raw.label,
                variable_type=variable_type,
                role=role,
                measurement_level=raw.measurement_level,
                value_labels=(
                    override.value_labels
                    if override.value_labels is not None
                    else raw.value_labels
                ),
                missing_rules=imported_rules + codebook_rules,
                pii_classification=pii,
                semantic_hooks=tuple(raw.metadata.get("semantic_hooks", ())),
                validation_status=status,
                validation_messages=tuple(messages),
            )
            variables.append(
                replace(
                    variable,
                    fingerprint=fingerprint_variable(
                        variable,
                        digest_provider=digest_provider,
                    ),
                )
            )
        return tuple(variables)

    @staticmethod
    def _validate_unique_names(variables: tuple[VariableDefinition, ...]) -> None:
        normalized = [item.name.strip().casefold() for item in variables]
        if any(not name for name in normalized):
            raise QuantitativeImportError("variable names must be non-empty")
        if len(set(normalized)) != len(normalized):
            raise QuantitativeImportError("variable names must be unique")

    @staticmethod
    def _technical_id_index(variables: tuple[VariableDefinition, ...]) -> int | None:
        indexes = [
            index
            for index, item in enumerate(variables)
            if item.role is VariableRole.TECHNICAL_ID
        ]
        if len(indexes) > 1:
            raise QuantitativeImportError("only one technical respondent ID is supported")
        return indexes[0] if indexes else None

    @staticmethod
    def _respondent_ids(
        *,
        dataset_id: str,
        file_checksum: str,
        rows: tuple[tuple[Any, ...], ...],
        technical_index: int | None,
        digest_provider: DeterministicDigestProvider,
    ) -> tuple[tuple[str, ...], bool, tuple[tuple[str, str], ...]]:
        if technical_index is None:
            return (
                tuple(
                    sha256_bytes(
                        f"{dataset_id}:{file_checksum}:{index}".encode("utf-8"),
                        digest_provider=digest_provider,
                    )
                    for index in range(len(rows))
                ),
                False,
                (),
            )
        raw_keys = [canonical_scalar(row[technical_index]) for row in rows]
        if any(item["type"] == "missing" or not item["value"] for item in raw_keys):
            raise QuantitativeImportError("technical respondent IDs must be non-missing")
        rendered = [f"{item['type']}:{item['value']}" for item in raw_keys]
        if len(set(rendered)) != len(rendered):
            raise QuantitativeImportError("duplicate technical respondent IDs")
        pseudonyms = tuple(
                sha256_bytes(
                    f"{dataset_id}:{item}".encode("utf-8"),
                    digest_provider=digest_provider,
                )
                for item in rendered
            )
        return (
            pseudonyms,
            True,
            tuple(sorted(zip(rendered, pseudonyms))),
        )

    @staticmethod
    def _pii_status(variables: tuple[VariableDefinition, ...]) -> PiiClassification:
        if any(item.pii_classification is PiiClassification.PII_RESTRICTED for item in variables):
            return PiiClassification.PII_RESTRICTED
        if any(item.pii_classification is PiiClassification.REVIEW_REQUIRED for item in variables):
            return PiiClassification.REVIEW_REQUIRED
        return PiiClassification.NONE

    @staticmethod
    def _validation_status(
        variables: tuple[VariableDefinition, ...],
        warnings: tuple[str, ...],
    ) -> ValidationStatus:
        if any(item.validation_status is ValidationStatus.BLOCKED for item in variables):
            return ValidationStatus.BLOCKED
        if warnings or any(
            item.validation_status is ValidationStatus.VALID_WITH_WARNINGS
            for item in variables
        ):
            return ValidationStatus.VALID_WITH_WARNINGS
        return ValidationStatus.VALID


def _infer_type(raw: Any, rows: tuple[tuple[Any, ...], ...], ordinal: int) -> VariableType:
    measure = raw.measurement_level.strip().casefold()
    if raw.value_labels or measure == "nominal":
        return VariableType.CATEGORICAL
    if measure == "ordinal":
        return VariableType.ORDINAL_SCALE
    observed = [row[ordinal] for row in rows if not _system_missing(row[ordinal])]
    if observed and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in observed):
        return VariableType.NUMERIC
    return VariableType.CATEGORICAL


def _infer_role(name: str, label: str, variable_type: VariableType) -> VariableRole:
    blob = f"{name} {label}".casefold()
    if any(token in blob for token in ("respondent id", "respondent_id", "response id", "response_id")):
        return VariableRole.TECHNICAL_ID
    if any(token in blob for token in ("sex", "gender", "age", "region")):
        return VariableRole.DEMOGRAPHIC
    if variable_type is VariableType.PII:
        return VariableRole.PII
    return VariableRole.RESPONSE


def _infer_pii(name: str, label: str, role: VariableRole) -> PiiClassification:
    blob = f"{name} {label}".casefold().replace("_", " ")
    normalized_name = name.strip().casefold().replace("_", " ")
    if role is VariableRole.PII or normalized_name in {
        "name",
        "full name",
        "respondent name",
        "telephone",
        "phone",
        "phone number",
        "mobile",
        "email",
        "email address",
    } or any(
        token in blob for token in ("full name", "respondent name", "telephone", "phone number", "email address")
    ):
        return PiiClassification.PII_RESTRICTED
    return PiiClassification.NONE


def _missing_rule_from_payload(payload: dict[str, Any]) -> MissingValueRule:
    if "lo" in payload or "hi" in payload:
        return MissingValueRule(
            kind="range",
            low=payload.get("lo"),
            high=payload.get("hi"),
            source="import",
        )
    return MissingValueRule(kind="value", value=payload.get("value"), source="import")


def _matches_any_rule(value: Any, rules: tuple[MissingValueRule, ...]) -> bool:
    for rule in rules:
        if rule.kind == "value" and value == rule.value:
            return True
        if rule.kind == "range" and rule.low <= value <= rule.high:
            return True
    return False


def _system_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))
