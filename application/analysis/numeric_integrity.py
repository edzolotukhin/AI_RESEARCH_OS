"""Shared fail-closed authority for structured numeric observations and series."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from application.evidence.semantic_assignment import semantic_assignment
from domain.planning.derivation import InformationNeedKind
from domain.planning.evidence_nature import EvidenceNature


MAX_NUMERIC_QUALIFICATION_ITEMS = 100


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


@dataclass(frozen=True)
class NumericQualificationResult:
    """Bounded F1/F2 result for one authoritative numeric ACQUIRED need."""

    information_need_id: str
    available: bool
    accepted_evidence: tuple[Any, ...]
    observations: tuple[ValidatedNumericObservation, ...]
    rejections: tuple[tuple[str, str], ...]
    rejection_reason_counts: Mapping[str, int]
    qualified_periods: tuple[str, ...]
    missing_periods: tuple[str, ...]
    compatible_duplicate_periods: tuple[str, ...]
    conflicting_periods: tuple[str, ...]
    established_lineage_ids: tuple[str, ...]
    unknown_lineage_count: int
    truncated: bool = False


@dataclass(frozen=True)
class NumericEvidenceProjection:
    evidence: tuple[Any, ...]
    qualifications: Mapping[str, NumericQualificationResult]


class NumericIntegrityError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def is_numeric_acquired_need(need: Any) -> bool:
    expectation = getattr(need, "evidence_expectation", None)
    confirmed_intent = getattr(need, "numeric_observation_required", None)
    return bool(
        getattr(need, "kind", None) == InformationNeedKind.ACQUIRED
        and (
            confirmed_intent is True
            or (
                confirmed_intent is None
                and expectation is not None
                and (
                    expectation.nature == EvidenceNature.QUANTITATIVE
                    or expectation.requires_quantitative_evidence
                )
            )
        )
    )


def qualify_numeric_information_need(
    *,
    design: Any,
    information_need: Any,
    evidence: Sequence[Any],
    source_repository: Any,
    temporal_decisions: Mapping[tuple[str, str], str],
    allowed_workflow_run_ids: Sequence[str],
    max_items: int = MAX_NUMERIC_QUALIFICATION_ITEMS,
) -> NumericQualificationResult:
    """Apply canonical F1 then F2 using requirements owned by Research Design."""
    need_id = str(getattr(information_need, "id", ""))
    mapped = tuple(sorted(
        (item for item in evidence if need_id in tuple(item.information_need_refs)),
        key=lambda item: item.id,
    ))
    coverage = getattr(information_need, "evidence_coverage", None)
    subject = getattr(design, "research_subject", None)
    required_periods = tuple(getattr(coverage, "required_periods", ()) or ())
    required_metric = str(getattr(coverage, "required_metric", "") or "").strip()
    required_unit = str(getattr(coverage, "required_unit", "") or "").strip()
    required_geography = str(
        getattr(coverage, "geography", "")
        or getattr(information_need, "geography", "")
        or ""
    ).strip()
    allowed_runs = tuple(dict.fromkeys(str(item) for item in allowed_workflow_run_ids if str(item)))
    requirements_available = bool(
        is_numeric_acquired_need(information_need)
        and coverage is not None
        and subject is not None
        and required_metric
        and required_unit
        and required_geography
        and required_periods
        and allowed_runs
        and source_repository is not None
    )
    if not requirements_available:
        return _numeric_unavailable(need_id, mapped, "numeric_requirements_unavailable")
    if len(mapped) > max_items:
        return _numeric_unavailable(
            need_id, mapped, "numeric_input_bound_exceeded", truncated=True,
        )

    requirements = NumericObservationRequirements(
        allowed_information_need_ids=(need_id,),
        subject_id=subject.subject_id,
        subject_fingerprint=subject.semantic_fingerprint,
        research_design_id=design.id,
        allowed_workflow_run_ids=allowed_runs,
        metric=required_metric,
        unit=required_unit,
        geography=required_geography,
        required_periods=required_periods,
    )
    observations: list[ValidatedNumericObservation] = []
    evidence_by_id: dict[str, Any] = {}
    rejections: Counter[str] = Counter()
    rejected_items: list[tuple[str, str]] = []
    for item in mapped:
        assignment = semantic_assignment(item)
        assignment_need = str(assignment.get("information_need_id", "")) if assignment else ""
        temporal_eligible = (
            temporal_decisions.get((item.id, assignment_need))
            == "applicable_satisfied"
        )
        try:
            source = source_repository.get_by_id(item.source_id)
            observation = validate_numeric_observation(
                item, source, requirements, temporal_eligible=temporal_eligible,
            )
        except (NumericIntegrityError, KeyError, LookupError, AttributeError) as exc:
            code = exc.code if isinstance(exc, NumericIntegrityError) else "numeric_source_missing"
            rejections[code] += 1
            rejected_items.append((item.id, code))
            continue
        observations.append(observation)
        evidence_by_id[item.id] = item

    series = evaluate_numeric_series(observations)
    conflicting = set(series.conflicting_periods)
    accepted_observations = tuple(
        item for item in observations if item.period not in conflicting
    )
    accepted_ids = {item.evidence_id for item in accepted_observations}
    for period in series.conflicting_periods:
        for item in series.observations_by_period.get(period, ()):
            rejections["conflicting_numeric_observations"] += 1
            rejected_items.append((item.evidence_id, "conflicting_numeric_observations"))
    accepted_evidence = tuple(
        evidence_by_id[item_id] for item_id in sorted(accepted_ids)
    )
    established: set[str] = set()
    unknown = 0
    from application.evidence.lineage_identity import canonical_lineage_identity
    for item in accepted_evidence:
        identity = canonical_lineage_identity(item.metadata.get("data_lineage"))
        if identity:
            established.add(identity)
        else:
            unknown += 1
    qualified_periods = tuple(
        period for period in required_periods if period in series.values
    )
    return NumericQualificationResult(
        information_need_id=need_id,
        available=True,
        accepted_evidence=accepted_evidence,
        observations=accepted_observations,
        rejections=tuple(sorted(rejected_items)),
        rejection_reason_counts=MappingProxyType(dict(sorted(rejections.items()))),
        qualified_periods=qualified_periods,
        missing_periods=tuple(period for period in required_periods if period not in series.values),
        compatible_duplicate_periods=series.compatible_duplicate_periods,
        conflicting_periods=series.conflicting_periods,
        established_lineage_ids=tuple(sorted(established)),
        unknown_lineage_count=unknown,
    )


def project_numeric_evidence_for_design(
    *, design: Any, evidence: Sequence[Any], source_repository: Any,
    temporal_decisions: Mapping[tuple[str, str], str],
    allowed_workflow_run_ids: Sequence[str],
) -> NumericEvidenceProjection:
    """Remove only rejected numeric need refs; preserve every nonnumeric ref."""
    numeric_needs = tuple(
        need for need in design.information_needs if is_numeric_acquired_need(need)
    )
    results = {
        need.id: qualify_numeric_information_need(
            design=design, information_need=need, evidence=evidence,
            source_repository=source_repository, temporal_decisions=temporal_decisions,
            allowed_workflow_run_ids=allowed_workflow_run_ids,
        )
        for need in numeric_needs
    }
    accepted = {
        need_id: {item.id for item in result.accepted_evidence}
        for need_id, result in results.items()
    }
    projected = []
    for item in evidence:
        refs = tuple(
            ref for ref in item.information_need_refs
            if ref not in results or item.id in accepted[ref]
        )
        if refs:
            projected.append(item if refs == item.information_need_refs else replace(
                item, information_need_refs=refs,
            ))
    return NumericEvidenceProjection(
        evidence=tuple(projected),
        qualifications=MappingProxyType(results),
    )


def _numeric_unavailable(
    need_id: str, evidence: Sequence[Any], reason: str, *, truncated: bool = False,
) -> NumericQualificationResult:
    count = len(tuple(evidence))
    return NumericQualificationResult(
        information_need_id=need_id, available=False, accepted_evidence=(),
        observations=(),
        rejections=tuple((item.id, reason) for item in tuple(evidence)[:MAX_NUMERIC_QUALIFICATION_ITEMS]),
        rejection_reason_counts=MappingProxyType({reason: count or 1}),
        qualified_periods=(), missing_periods=(), compatible_duplicate_periods=(),
        conflicting_periods=(), established_lineage_ids=(), unknown_lineage_count=0,
        truncated=truncated,
    )


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
