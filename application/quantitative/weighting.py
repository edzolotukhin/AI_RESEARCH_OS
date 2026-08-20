from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_dataset_ports import DatasetStorage
from application.quantitative.fingerprints import (
    canonical_digest,
    canonical_scalar,
    fingerprint_analysis_specification,
)
from domain.quantitative.analysis import AnalysisSpecification
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, VariableRole
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import (
    AnalyticalDatasetView,
    WeightApprovalState,
    WeightSet,
    WeightSetApproval,
    WeightSourceType,
    WeightValidationStatus,
    WeightingMode,
)

VALIDATION_VERSION = "qc-weight-validation-1"


class WeightingError(ValueError):
    pass


def _digest(payload: Any, provider: DeterministicDigestProvider) -> str:
    return canonical_digest(payload, digest_provider=provider)


class WeightImportService:
    def __init__(self, *, storage: DatasetStorage, digest_provider: DeterministicDigestProvider) -> None:
        self._storage = storage
        self._digest = digest_provider

    def from_embedded_variable(self, *, dataset: DatasetVersion, codebook: CodebookVersion, variable_id: str) -> WeightSet:
        variable = codebook.variable_by_id(variable_id)
        if variable.role is not VariableRole.WEIGHT:
            raise WeightingError("embedded weight variable must have WEIGHT role")
        index = next(i for i, item in enumerate(codebook.variables) if item.variable_id == variable_id)
        rows = self._storage.get_parsed_rows(dataset.version_id)
        refs = self._storage.get_respondent_lineage(dataset.version_id)
        pairs = tuple(zip(refs, (row[index] for row in rows)))
        provenance = _digest({"source_file": dataset.file_checksum, "variable": variable.fingerprint}, self._digest)
        return self._build(dataset=dataset, source_type=WeightSourceType.EMBEDDED_VARIABLE, source_provenance=provenance, key_specification="inherited-row-lineage", pairs=pairs, source_checksum=dataset.file_checksum, source_variable_fingerprint=variable.fingerprint)

    def from_separate_keyed_rows(self, *, dataset: DatasetVersion, source_bytes_checksum: str, parser_name: str, parser_version: str, key_specification: str, rows: tuple[tuple[Any, Any], ...]) -> WeightSet:
        protected = dict(self._storage.get_protected_respondent_bindings(dataset.version_id))
        if not protected:
            raise WeightingError("separate keyed weights require protected respondent binding")
        retained = set(self._storage.get_respondent_lineage(dataset.version_id))
        seen: set[str] = set()
        pairs: list[tuple[str, Any]] = []
        messages: list[str] = []
        unknown = 0
        excluded = 0
        for raw_key, value in rows:
            scalar = canonical_scalar(raw_key)
            canonical_key = f"{scalar['type']}:{scalar['value']}"
            if canonical_key in seen:
                messages.append("duplicate_respondent_key")
                continue
            seen.add(canonical_key)
            pseudonym = protected.get(canonical_key)
            if pseudonym is None:
                unknown += 1
            elif pseudonym not in retained:
                excluded += 1
            else:
                pairs.append((pseudonym, value))
        provenance = _digest({"checksum": source_bytes_checksum, "parser": parser_name, "parser_version": parser_version}, self._digest)
        return self._build(dataset=dataset, source_type=WeightSourceType.SEPARATE_FILE, source_provenance=provenance, key_specification=key_specification, pairs=tuple(pairs), initial_messages=tuple(messages), unknown_key_count=unknown, excluded_parent_row_count=excluded, source_checksum=source_bytes_checksum, parser_name=parser_name, parser_version=parser_version)

    def _build(self, *, dataset: DatasetVersion, source_type: WeightSourceType, source_provenance: str, key_specification: str, pairs: tuple[tuple[str, Any], ...], initial_messages: tuple[str, ...] = (), unknown_key_count: int = 0, excluded_parent_row_count: int = 0, source_checksum: str | None = None, source_variable_fingerprint: str | None = None, parser_name: str | None = None, parser_version: str | None = None) -> WeightSet:
        retained = tuple(self._storage.get_respondent_lineage(dataset.version_id))
        messages = list(initial_messages)
        values: dict[str, Decimal] = {}
        observed_refs: set[str] = set()
        negative = missing = non_finite = zero = 0
        for ref, raw in pairs:
            if ref in observed_refs:
                messages.append("duplicate_respondent_key")
                continue
            observed_refs.add(ref)
            if raw is None or isinstance(raw, bool):
                missing += 1
                continue
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError):
                non_finite += 1
                continue
            if not value.is_finite():
                non_finite += 1
                continue
            if value < 0:
                negative += 1
            if value == 0:
                zero += 1
            values[ref] = value
        missing += len(set(retained) - observed_refs)
        canonical_vector = tuple(sorted((ref, values[ref]) for ref in set(retained).intersection(values)))
        if unknown_key_count:
            messages.append("unknown_respondent_key")
        if missing:
            messages.append("incomplete_retained_coverage")
        if negative:
            messages.append("negative_weight")
        if non_finite:
            messages.append("non_numeric_or_non_finite_weight")
        blocking = bool(missing or negative or non_finite or unknown_key_count or "duplicate_respondent_key" in messages)
        if zero:
            messages.append("zero_weight_present")
        if excluded_parent_row_count:
            messages.append("excluded_parent_respondent_ignored")
        status = WeightValidationStatus.BLOCKED if blocking else (WeightValidationStatus.VALID_WITH_WARNINGS if messages else WeightValidationStatus.VALID)
        decimals = [value for _, value in canonical_vector]
        total = sum(decimals, Decimal(0))
        mean = total / Decimal(len(decimals)) if decimals else None
        coverage = Decimal(len(canonical_vector)) / Decimal(len(retained)) if retained else Decimal(1)
        vector_fp = _digest([(ref, canonical_scalar(value)) for ref, value in canonical_vector], self._digest)
        key_fp = _digest(key_specification, self._digest)
        validation_fp = _digest({"version": VALIDATION_VERSION, "messages": sorted(set(messages)), "counts": [zero, negative, missing, non_finite, unknown_key_count, excluded_parent_row_count]}, self._digest)
        reproducibility = _digest({"dataset": dataset.dataset_fingerprint, "source": source_provenance, "key": key_fp, "vector": vector_fp, "validation": validation_fp}, self._digest)
        return WeightSet(
            weight_set_id=str(uuid5(NAMESPACE_URL, f"qc-weight-set:{reproducibility}")),
            dataset_version_id=dataset.version_id,
            dataset_fingerprint=dataset.dataset_fingerprint,
            source_type=source_type,
            source_provenance_fingerprint=source_provenance,
            respondent_key_specification_fingerprint=key_fp,
            weight_vector=canonical_vector,
            vector_fingerprint=vector_fp,
            weight_count=len(canonical_vector),
            retained_respondent_count=len(retained),
            coverage_count=len(canonical_vector),
            coverage_share=coverage,
            minimum_weight=min(decimals) if decimals else None,
            maximum_weight=max(decimals) if decimals else None,
            mean_weight=mean,
            sum_weights=total,
            zero_weight_count=zero,
            negative_weight_count=negative,
            missing_weight_count=missing,
            non_finite_count=non_finite,
            unknown_key_count=unknown_key_count,
            excluded_parent_row_count=excluded_parent_row_count,
            validation_status=status,
            validation_messages=tuple(sorted(set(messages))),
            validation_fingerprint=validation_fp,
            reproducibility_fingerprint=reproducibility,
            source_checksum=source_checksum,
            source_variable_fingerprint=source_variable_fingerprint,
            parser_name=parser_name,
            parser_version=parser_version,
        )


def approve_weight_set(*, weight_set: WeightSet, approver_id: str, approved_at: str, digest_provider: DeterministicDigestProvider) -> WeightSetApproval:
    if weight_set.validation_status is WeightValidationStatus.BLOCKED:
        raise WeightingError("blocked WeightSet cannot be approved")
    payload = {"weight_set": weight_set.reproducibility_fingerprint, "dataset": weight_set.dataset_fingerprint, "validation": weight_set.validation_fingerprint, "approver": approver_id, "approved_at": approved_at}
    return WeightSetApproval(weight_set.weight_set_id, weight_set.reproducibility_fingerprint, weight_set.dataset_fingerprint, weight_set.validation_fingerprint, WeightApprovalState.APPROVED, approver_id, approved_at, _digest(payload, digest_provider))


def build_analytical_view(*, dataset: DatasetVersion, quality: DatasetQualityAssessment, specification: AnalysisSpecification, mode: WeightingMode, respondent_refs: tuple[str, ...], digest_provider: DeterministicDigestProvider, weight_set: WeightSet | None = None, approval: WeightSetApproval | None = None) -> AnalyticalDatasetView:
    if not quality.current or quality.state is not DatasetQualityState.QC_APPROVED or quality.dataset_fingerprint != dataset.dataset_fingerprint:
        raise WeightingError("analytical view requires current QC_APPROVED dataset")
    if mode is WeightingMode.UNWEIGHTED and (weight_set or approval):
        raise WeightingError("unweighted view cannot carry WeightSet")
    if mode is WeightingMode.WEIGHTED:
        if weight_set is None or approval is None or approval.state is not WeightApprovalState.APPROVED:
            raise WeightingError("weighted view requires approved WeightSet")
        if weight_set.dataset_version_id != dataset.version_id or weight_set.dataset_fingerprint != dataset.dataset_fingerprint or approval.dataset_fingerprint != dataset.dataset_fingerprint or approval.weight_set_fingerprint != weight_set.reproducibility_fingerprint or approval.validation_fingerprint != weight_set.validation_fingerprint:
            raise WeightingError("WeightSet approval is not current for dataset")
    specification_fp = fingerprint_analysis_specification(specification, digest_provider=digest_provider)
    eligible_fp = _digest(tuple(sorted(respondent_refs)), digest_provider)
    payload = {"dataset": dataset.dataset_fingerprint, "quality": quality.fingerprint, "specification": specification_fp, "mode": mode.value, "weight_set": weight_set.reproducibility_fingerprint if weight_set else None, "eligible": eligible_fp, "filter": specification.filter_definition, "base": specification.base_definition}
    fingerprint = _digest(payload, digest_provider)
    return AnalyticalDatasetView(str(uuid5(NAMESPACE_URL, f"qc-view:{fingerprint}")), dataset.version_id, dataset.dataset_fingerprint, quality.fingerprint, specification_fp, mode, weight_set.weight_set_id if weight_set else None, weight_set.reproducibility_fingerprint if weight_set else None, eligible_fp, specification.filter_definition, specification.base_definition, fingerprint)
