"""Shared fail-closed authority for structured numeric observations and series."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence

from application.evidence.semantic_assignment import semantic_assignment


@dataclass(frozen=True)
class NumericObservationRequirements:
    allowed_information_need_ids: tuple[str, ...]
    subject_id: str
    subject_fingerprint: str
    research_design_id: str
    allowed_workflow_run_ids: tuple[str, ...]
    metric: str
    unit: str
    geography: str
    required_periods: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedNumericObservation:
    evidence_id: str
    source_id: str
    information_need_id: str
    subject_id: str
    subject_fingerprint: str
    metric: str
    unit: str
    geography: str
    period: str
    value: Decimal
    source_content_checksum: str
    raw_content_checksum: str
    raw_checksum_kind: str
    terminal_resource_key: str
    extraction_revision: str
    content_revision: int
    cell: str
    lineage: Mapping[str, Any]


@dataclass(frozen=True)
class NumericSeriesIntegrity:
    values: Mapping[str, Decimal]
    observations_by_period: Mapping[str, tuple[ValidatedNumericObservation, ...]]
    observations_by_scope: Mapping[tuple[str, str, str, str, str, str], tuple[ValidatedNumericObservation, ...]]
    compatible_duplicate_periods: tuple[str, ...]
    conflicting_periods: tuple[str, ...]


class NumericIntegrityError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_numeric_observation(
    evidence: Any,
    source: Any,
    requirements: NumericObservationRequirements,
    *,
    temporal_eligible: bool,
) -> ValidatedNumericObservation:
    """Validate one observation against the same authority used by Analysis and diagnostics."""
    if not temporal_eligible:
        raise NumericIntegrityError("numeric_temporal_ineligible")
    if source is None or source.id != evidence.source_id or source.project_id != evidence.project_id:
        raise NumericIntegrityError("numeric_source_missing")
    if (evidence.research_design_id != requirements.research_design_id
            or evidence.workflow_run_id not in requirements.allowed_workflow_run_ids
            or requirements.research_design_id not in tuple(source.research_design_refs)
            or evidence.workflow_run_id not in tuple(source.workflow_run_refs)):
        raise NumericIntegrityError("numeric_source_authority_scope_mismatch")

    assignment = semantic_assignment(evidence)
    if (not assignment
            or assignment.get("subject_id") != requirements.subject_id
            or assignment.get("subject_fingerprint") != requirements.subject_fingerprint):
        raise NumericIntegrityError("unvalidated_numeric_semantics")
    assignment_need = str(assignment.get("information_need_id", ""))
    allowed_needs = set(requirements.allowed_information_need_ids)
    if assignment_need not in allowed_needs or assignment_need not in set(evidence.information_need_refs):
        raise NumericIntegrityError("numeric_semantic_dependency_mismatch")

    data = evidence.metadata
    if not data.get("structured_table"):
        raise NumericIntegrityError("numeric_structured_observation_required")
    locator = evidence.source_locator.get("structured", {})
    if not isinstance(locator, dict) or locator != data.get("workbook_provenance"):
        raise NumericIntegrityError("numeric_source_revision_mismatch")
    if (locator.get("terminal_resource_key") != source.terminal_resource_key
            or locator.get("extraction_revision") != source.extraction_revision
            or locator.get("content_revision") != source.content_revision
            or locator.get("raw_workbook_checksum") != source.raw_content_checksum
            or (locator.get("raw_checksum_kind") is not None
                and locator.get("raw_checksum_kind") != source.raw_checksum_kind)):
        raise NumericIntegrityError("numeric_source_revision_mismatch")

    rows = [
        row for row in source.metadata.get("structured_tables_v2", ())
        if isinstance(row, dict)
        and row.get("sheet") == locator.get("sheet")
        and row.get("table_range") == locator.get("table_range")
        and row.get("row") == locator.get("row")
    ]
    if len(rows) != 1 or rows[0].get("ambiguous_headers"):
        raise NumericIntegrityError("ambiguous_numeric_source")
    row = rows[0]
    if locator.get("header_checksum") != row.get("header_checksum") or evidence.source_excerpt != row.get("excerpt"):
        raise NumericIntegrityError("numeric_header_or_excerpt_mismatch")
    cells = {
        cell.get("cell"): cell for cell in row.get("cells", ())
        if isinstance(cell, dict) and cell.get("cell")
    }
    value_cell = cells.get(locator.get("cell"), {})
    period_cell = cells.get(locator.get("period_cell"), {})

    units = [
        cell.get("value") for cell in cells.values()
        if str(cell.get("header", "")).casefold() in {"unit", "units", "одиниця", "одиниці"}
    ]
    header_unit = re.search(r"\(([^)]+)\)\s*$", str(value_cell.get("header", "")))
    if header_unit:
        units.append(header_unit.group(1))
    geographies = [
        cell.get("value") for cell in cells.values()
        if str(cell.get("header", "")).casefold() in {"geography", "country", "географія", "країна"}
    ]
    if (not units or any(not same(value, requirements.unit) for value in units)
            or not geographies or any(not same(value, requirements.geography) for value in geographies)):
        raise NumericIntegrityError("numeric_unit_or_geography_binding_invalid")
    if (not same(data.get("metric"), requirements.metric)
            or not same(data.get("unit"), requirements.unit)
            or not same(data.get("geography"), requirements.geography)):
        raise NumericIntegrityError("numeric_unit_or_geography_binding_invalid")

    period = str(data.get("observation_period", ""))
    if not period or (requirements.required_periods and period not in requirements.required_periods):
        raise NumericIntegrityError("numeric_period_invalid")
    try:
        value = Decimal(str(data.get("normalized_numeric_value", "NaN")))
        metadata_value = Decimal(str(data.get("numeric_value", "NaN")))
        cell_value = Decimal(str(value_cell.get("numeric_value", "NaN")))
    except (InvalidOperation, ValueError, TypeError):
        raise NumericIntegrityError("numeric_cell_binding_invalid") from None
    metric_header = re.sub(r"\s*\([^)]*\)\s*$", "", str(value_cell.get("header", "")))
    if (not value.is_finite() or metadata_value != value or cell_value != value
            or value_cell.get("formula") or period_cell.get("formula")
            or str(period_cell.get("value")) != period
            or not same(metric_header, requirements.metric)):
        raise NumericIntegrityError("numeric_cell_binding_invalid")

    return ValidatedNumericObservation(
        evidence_id=evidence.id,
        source_id=source.id,
        information_need_id=assignment_need,
        subject_id=requirements.subject_id,
        subject_fingerprint=requirements.subject_fingerprint,
        metric=requirements.metric,
        unit=requirements.unit,
        geography=requirements.geography,
        period=period,
        value=value,
        source_content_checksum=source.content_checksum,
        raw_content_checksum=source.raw_content_checksum,
        raw_checksum_kind=source.raw_checksum_kind,
        terminal_resource_key=source.terminal_resource_key,
        extraction_revision=source.extraction_revision,
        content_revision=source.content_revision,
        cell=str(locator.get("cell", "")),
        lineage=dict(data.get("data_lineage") or {}),
    )


def evaluate_numeric_series(
    observations: Sequence[ValidatedNumericObservation],
) -> NumericSeriesIntegrity:
    """Classify compatible duplicates and conflicts without reconciling values."""
    grouped: dict[tuple[str, str, str, str, str, str], list[ValidatedNumericObservation]] = {}
    for item in observations:
        scope = (
            item.subject_id, item.subject_fingerprint, normalize(item.metric),
            normalize(item.unit), normalize(item.geography), item.period,
        )
        grouped.setdefault(scope, []).append(item)

    values: dict[str, Decimal] = {}
    by_period: dict[str, tuple[ValidatedNumericObservation, ...]] = {}
    duplicates: list[str] = []
    conflicts: list[str] = []
    period_scopes: dict[str, list[tuple[str, str, str, str, str, str]]] = {}
    for scope in grouped:
        period_scopes.setdefault(scope[-1], []).append(scope)
    for period, scopes in sorted(period_scopes.items()):
        if len(scopes) != 1:
            # Different metric/scope observations are not a single comparable series.
            continue
        members = tuple(sorted(grouped[scopes[0]], key=lambda item: (item.evidence_id, item.source_id)))
        by_period[period] = members
        distinct = {item.value for item in members}
        if len(distinct) > 1:
            conflicts.append(period)
            continue
        values[period] = next(iter(distinct))
        if len(members) > 1:
            duplicates.append(period)
    return NumericSeriesIntegrity(
        values=values,
        observations_by_period=by_period,
        observations_by_scope={
            scope: tuple(sorted(members, key=lambda item: (item.evidence_id, item.source_id)))
            for scope, members in sorted(grouped.items())
        },
        compatible_duplicate_periods=tuple(duplicates),
        conflicting_periods=tuple(conflicts),
    )


def normalize(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").casefold().split())


def same(left: Any, right: Any) -> bool:
    return normalize(left) == normalize(right)
