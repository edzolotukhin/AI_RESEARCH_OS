"""Bounded, read-only evidence coverage diagnostics."""

from __future__ import annotations

from collections import Counter
from datetime import date
import re
from typing import Any, Mapping, Sequence

from application.evidence.citation_integrity import citation_is_valid
from application.evidence.semantic_assignment import semantic_assignment
from application.analysis.numeric_integrity import (
    NumericIntegrityError,
    NumericObservationRequirements,
    evaluate_numeric_series,
    validate_numeric_observation,
)
from application.research_quality.deterministic_sufficiency_evaluator import (
    _deduplicate_evidence, _independent_lineages,
)
from domain.planning.research_design import EvidenceCoverageContract
from domain.planning.derivation import InformationNeedKind


DIAGNOSTIC_VERSION = "evidence_coverage_diagnostics_v1"
MAX_PERIODS = 32
MAX_LOOP_ATTEMPTS = 16
_PERIOD = re.compile(r"(?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])|-Q[1-4])?")
_READINESS_STATUSES = {"sufficient", "partial", "insufficient", "missing", "blocked", "unknown"}
_GAP_TYPES = {"no_evidence", "insufficient_depth", "insufficient_diversity", "missing_quantitative_data", "stale_evidence", "conflicting_evidence", "insufficient_source_quality", "unresolvable", "unknown"}
_STRATEGIES = {"direct", "semantic_expansion", "source_diversification", "proxy_indicators", "unknown"}
_TEMPORAL_OUT = {"applicable_failed", "out_of_period"}
_REJECTIONS = {"invalid_citation", "temporal_out_of_period", "temporal_unresolved", "numeric_binding_unverified", "conflicting_numeric_observations", "undeclared_period", "unknown"}


def build_evidence_coverage_diagnostics(
    *, information_need_id: str, workflow_run_id: str, research_design_id: str,
    information_need_kind: InformationNeedKind | str,
    research_subject_id: str | None, research_subject_fingerprint: str | None,
    allowed_dependency_information_need_ids: Sequence[str],
    required_numeric_unit: str | None,
    coverage_contract: EvidenceCoverageContract, sources: Sequence[Any], evidence: Sequence[Any],
    temporal_qualification_by_evidence_and_need: Mapping[tuple[str, str], str],
    readiness_snapshot: Any, sources_complete: bool | None, evidence_complete: bool | None,
    research_loop_history: Sequence[Any] = (), max_periods: int = MAX_PERIODS,
    max_loop_attempts: int = MAX_LOOP_ATTEMPTS,
) -> dict[str, Any]:
    """Build a safe diagnostic; unknown collection completeness fails closed."""
    need_id = str(information_need_id or "").strip()
    run_id = str(workflow_run_id or "").strip()
    design_id = str(research_design_id or "").strip()
    subject_id = str(research_subject_id or "").strip()
    subject_fingerprint = str(research_subject_fingerprint or "").strip()
    numeric_unit = str(required_numeric_unit or "").strip()
    dependencies = tuple(dict.fromkeys(
        str(value).strip() for value in allowed_dependency_information_need_ids
        if str(value).strip()
    ))
    try:
        need_kind = InformationNeedKind(information_need_kind)
    except (TypeError, ValueError):
        return _unavailable(need_id, "information_need_kind_invalid")
    if need_kind == InformationNeedKind.ACQUIRED:
        if dependencies:
            return _unavailable(need_id, "dependency_context_inconsistent")
        allowed_assignment_needs = (need_id,)
    elif need_kind == InformationNeedKind.DERIVED:
        if not dependencies or need_id in dependencies:
            return _unavailable(need_id, "dependency_context_inconsistent")
        allowed_assignment_needs = dependencies
    else:
        return _unavailable(need_id, "numeric_coverage_not_applicable")
    if (not need_id or not run_id or not design_id or not subject_id or not subject_fingerprint or not numeric_unit
            or not isinstance(coverage_contract, EvidenceCoverageContract)):
        return _unavailable(need_id, "invalid_input")
    if sources_complete is not True or evidence_complete is not True:
        return _unavailable(need_id, "collections_incomplete")
    readiness = _readiness_projection(readiness_snapshot, need_id)
    if readiness is None:
        return _unavailable(need_id, "information_need_mismatch")
    if not readiness["assessment_current"]:
        return _unavailable(need_id, "readiness_not_current")

    source_ids = [str(getattr(item, "id", "")) for item in sources]
    evidence_ids = [str(getattr(item, "id", "")) for item in evidence]
    if not all(source_ids) or len(source_ids) != len(set(source_ids)):
        return _unavailable(need_id, "source_collection_inconsistent")
    if not all(evidence_ids) or len(evidence_ids) != len(set(evidence_ids)):
        return _unavailable(need_id, "evidence_collection_inconsistent")
    source_by_id = dict(zip(source_ids, sources))
    relevant_need_ids = set(allowed_assignment_needs)
    in_scope = sorted(
        (item for item in evidence if relevant_need_ids.intersection(
            tuple(getattr(item, "information_need_refs", ()))
        )),
        key=lambda item: str(getattr(item, "id", "")),
    )
    if any(str(getattr(item, "source_id", "")) not in source_by_id for item in in_scope):
        return _unavailable(need_id, "source_collection_inconsistent")
    if any(str(getattr(item, "workflow_run_id", "")) != run_id or str(getattr(item, "research_design_id", "")) != design_id for item in in_scope):
        return _unavailable(need_id, "evidence_collection_inconsistent")

    numeric_requirements = NumericObservationRequirements(
        allowed_information_need_ids=allowed_assignment_needs,
        subject_id=subject_id,
        subject_fingerprint=subject_fingerprint,
        research_design_id=design_id,
        allowed_workflow_run_ids=(run_id,),
        metric=coverage_contract.required_metric,
        unit=numeric_unit,
        geography=coverage_contract.geography,
        required_periods=tuple(coverage_contract.required_periods),
    )

    period_limit = max(1, min(int(max_periods), MAX_PERIODS))
    loop_limit = max(1, min(int(max_loop_attempts), MAX_LOOP_ATTEMPTS))
    declared, unmapped = _declared_periods(coverage_contract.required_periods)
    visible = declared[:period_limit]
    periods_truncated = len(declared) > len(visible)
    states = {period: {"validated": [], "claims": 0, "unknown": False, "rejections": Counter()} for period in visible}
    rejections: Counter[str] = Counter()
    citation_valid: list[Any] = []
    temporal_eligible: list[Any] = []
    numeric_verified: list[Any] = []

    for item in in_scope:
        source = source_by_id[str(item.source_id)]
        metadata = getattr(item, "metadata", {}) or {}
        period = _canonical_period(metadata.get("observation_period"))
        bucket = states.get(period) if period is not None else None
        reason = None
        if not citation_is_valid(item, source):
            reason = "invalid_citation"
        else:
            citation_valid.append(item)
            assignment = semantic_assignment(item)
            assignment_need = (
                str(assignment.get("information_need_id", ""))
                if assignment is not None else ""
            )
            temporal = str(temporal_qualification_by_evidence_and_need.get(
                (str(item.id), assignment_need), "",
            )).strip()
            if temporal in _TEMPORAL_OUT:
                reason = "temporal_out_of_period"
            elif temporal == "applicable_satisfied" or (temporal == "not_applicable" and metadata.get("observation_period") in (None, "")):
                temporal_eligible.append(item)
                if period is None:
                    reason = "temporal_unresolved"
                elif bucket is None:
                    reason = "undeclared_period"
                else:
                    try:
                        observation = validate_numeric_observation(
                            item, source, numeric_requirements,
                            temporal_eligible=(temporal == "applicable_satisfied"),
                        )
                    except NumericIntegrityError:
                        observation = None
                    if observation is not None:
                        numeric_verified.append(item)
                        bucket["validated"].append((item, observation))
                        continue
                    bucket["claims"] += 1
                    bucket["unknown"] = True
                    reason = "numeric_binding_unverified"
            else:
                reason = "temporal_unresolved"
        if reason:
            safe = reason if reason in _REJECTIONS else "unknown"
            rejections[safe] += 1
            if bucket is not None:
                bucket["rejections"][safe] += 1
                if safe in {"temporal_unresolved", "numeric_binding_unverified", "unknown"}:
                    bucket["unknown"] = True

    unique_temporal, _ = _deduplicate_evidence(list(temporal_eligible))
    if need_kind == InformationNeedKind.ACQUIRED and readiness["evidence_count"] != len(unique_temporal):
        return _unavailable(need_id, "readiness_evidence_count_mismatch")
    independent, _ = _independent_lineages(unique_temporal)
    rows = []
    missing: list[str] = []
    unknown: list[str] = []
    confirmed_total = 0
    for period in visible:
        state = states[period]
        unique_items, _ = _deduplicate_evidence([item for item, _ in state["validated"]])
        unique_ids = {item.id for item in unique_items}
        observations = [observation for item, observation in state["validated"] if item.id in unique_ids]
        series = evaluate_numeric_series(observations)
        if series.conflicting_periods:
            confirmed = []
            state["unknown"] = True
            state["rejections"]["conflicting_numeric_observations"] += 1
            rejections["conflicting_numeric_observations"] += 1
        else:
            confirmed = unique_items
        confirmed_sources, _ = _independent_lineages(confirmed)
        confirmed_total += len(confirmed)
        if confirmed:
            status = "confirmed"
        elif state["unknown"]:
            status = "unknown"; unknown.append(period)
        else:
            status = "missing"; missing.append(period)
        rows.append({"period": period, "status": status, "confirmed_observation_count": len(confirmed),
                     "qualified_claim_count": state["claims"], "independent_source_count": len(confirmed_sources),
                     "rejection_reason_counts": _counter_dict(state["rejections"])})

    loop, loop_truncated = _loop_projection(research_loop_history, need_id, loop_limit)
    truncated = periods_truncated or loop_truncated
    dimensions = [name for enabled, name in (
        (coverage_contract.required_metric, "metric"), (coverage_contract.required_periods, "period"),
        (coverage_contract.required_observations, "observation"), (coverage_contract.geography, "geography"),
        (coverage_contract.required_authority_kinds or coverage_contract.required_authority_kind_groups, "authority"),
        (coverage_contract.minimum_independent_sources > 1, "independent_sources"),
    ) if enabled]
    return {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "availability": "partial" if truncated or unmapped or unknown else "available",
        "truncated": truncated, "information_need_id": need_id,
        "requirements": {"required_dimensions": dimensions, "required_periods": visible,
                         "required_period_count": len(coverage_contract.required_periods),
                         "unmapped_required_period_count": unmapped,
                         "required_observation_count": len(coverage_contract.required_observations),
                         "minimum_independent_sources": coverage_contract.minimum_independent_sources},
        "qualification": {"persisted_evidence_count": len(in_scope),
                          "coverage_basis": ("current_information_need" if need_kind == InformationNeedKind.ACQUIRED else "declared_dependencies"),
                          "citation_valid_evidence_count": len(citation_valid),
                          "temporally_eligible_evidence_count": len(unique_temporal),
                          "numeric_binding_verified_evidence_count": len(numeric_verified),
                          "confirmed_observation_count": confirmed_total,
                          "independent_source_count": len(independent),
                          "rejection_reason_counts": _counter_dict(rejections)},
        "period_coverage": rows,
        "unresolved_gaps": {"missing_periods": missing, "unknown_periods": unknown,
                            "missing_period_count": len(missing), "unknown_period_count": len(unknown)},
        "readiness": readiness, "loop_progress": loop,
    }


def _unavailable(need_id: str, reason: str) -> dict[str, Any]:
    return {"diagnostic_version": DIAGNOSTIC_VERSION, "availability": "unavailable", "truncated": False,
            "information_need_id": need_id, "unavailable_reason": reason}


def _canonical_period(value: Any) -> str | None:
    if not isinstance(value, str) or not _PERIOD.fullmatch(value.strip()):
        return None
    candidate = value.strip()
    if len(candidate) == 10:
        try: date.fromisoformat(candidate)
        except ValueError: return None
    return candidate


def _declared_periods(values: Sequence[str]) -> tuple[list[str], int]:
    result: list[str] = []; unmapped = 0
    for value in values:
        period = _canonical_period(value)
        if period is None: unmapped += 1
        elif period not in result: result.append(period)
    return result, unmapped


def _same(left: Any, right: Any) -> bool:
    return " ".join(str(left or "").casefold().split()) == " ".join(str(right or "").casefold().split())


def _readiness_projection(snapshot: Any, need_id: str) -> dict[str, Any] | None:
    if hasattr(snapshot, "to_dict"): snapshot = snapshot.to_dict()
    if not isinstance(snapshot, dict) or str(snapshot.get("information_need_id", "")) != need_id: return None
    status = str(snapshot.get("status", "unknown")).casefold()
    gaps: Counter[str] = Counter()
    for raw in snapshot.get("gap_types", ()) or ():
        gap = str(getattr(raw, "value", raw)).casefold(); gaps[gap if gap in _GAP_TYPES else "unknown"] += 1
    return {"status": status if status in _READINESS_STATUSES else "unknown",
            "assessment_current": bool(snapshot.get("assessment_current", False)),
            "analysis_eligible": bool(snapshot.get("analysis_eligible", False)),
            "evidence_count": max(0, int(snapshot.get("evidence_count", 0) or 0)),
            "independent_source_count": max(0, int(snapshot.get("independent_source_count", 0) or 0)),
            "missing_aspect_count": len(tuple(snapshot.get("missing_aspects", ()) or ())),
            "gap_type_counts": _counter_dict(gaps)}


def _loop_projection(history: Sequence[Any], need_id: str, limit: int) -> tuple[dict[str, Any], bool]:
    selected = []
    for raw in history:
        item = raw.to_dict() if hasattr(raw, "to_dict") else raw
        if isinstance(item, dict) and need_id in tuple(item.get("targeted_need_ids", ()) or ()): selected.append(item)
    selected.sort(key=lambda item: (int(item.get("round_number", 0) or 0), int(item.get("attempt", 0) or 0)))
    attempts = []; strategies: Counter[str] = Counter(); delta_total = 0
    for item in selected[:limit]:
        raw_strategy = str(item.get("strategy_id") or "unknown")
        strategy = raw_strategy if raw_strategy in _STRATEGIES else "unknown"; strategies[strategy] += 1
        diagnostic = item.get("remediation_attempt_diagnostics")
        diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
        delta = max(0, int(diagnostic.get("target_qualifying_delta", 0) or 0)); delta_total += delta
        before = str(diagnostic.get("status_before") or "unknown").casefold(); after = str(diagnostic.get("status_after") or "unknown").casefold()
        attempts.append({"round_number": max(0, int(item.get("round_number", 0) or 0)), "attempt": max(0, int(item.get("attempt", 0) or 0)),
                         "strategy": strategy, "improved": bool(item.get("improved", False)), "target_qualifying_delta": delta,
                         "status_before": before if before in _READINESS_STATUSES else "unknown",
                         "status_after": after if after in _READINESS_STATUSES else "unknown"})
    return ({"attempt_count": len(selected), "visible_attempt_count": len(attempts),
             "improved_attempt_count": sum(bool(item.get("improved", False)) for item in selected),
             "visible_target_qualifying_delta": delta_total, "strategy_counts": _counter_dict(strategies), "attempts": attempts},
            len(selected) > limit)


def _counter_dict(values: Counter[str]) -> dict[str, int]:
    return {key: int(values[key]) for key in sorted(values) if values[key]}
