"""Deterministic Quant foundation outcomes; no Desk sufficiency or ARK mapping."""

from dataclasses import dataclass
from enum import StrEnum

from domain.quantitative.analysis_execution import (
    AnalysisExecutionManifestStatus, AnalysisItemExecutionStatus,
)
from domain.quantitative.dataset import ValidationStatus


class QuantReadinessState(StrEnum):
    INVALID_DATASET = "INVALID_DATASET"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNSUPPORTED_PROCEDURE = "UNSUPPORTED_PROCEDURE"
    COMPUTATION_FAILURE = "COMPUTATION_FAILURE"
    READY = "READY"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class QuantReadiness:
    state: QuantReadinessState
    reason: str


def assess_foundation(*, dataset, codebook, procedure: str, eligible_n: int | None,
                      minimum_n: int = 1, execution_status=None) -> QuantReadiness:
    if dataset.validation_status is ValidationStatus.BLOCKED or not codebook.approved or codebook.fingerprint != dataset.codebook_fingerprint:
        return QuantReadiness(QuantReadinessState.INVALID_DATASET, "INVALID_OR_STALE_DATASET")
    supported = {"ONE_WAY", "NUMERIC_SUMMARY", "CROSS_TAB", "NPS", "CUSTOM_INDEX",
                 "INDEPENDENT_TWO_PROPORTION_Z_TEST", "INDEPENDENT_WELCH_T_TEST"}
    if procedure not in supported:
        return QuantReadiness(QuantReadinessState.UNSUPPORTED_PROCEDURE, "UNSUPPORTED_PROCEDURE")
    if eligible_n is None:
        return QuantReadiness(QuantReadinessState.COMPUTATION_FAILURE, "ELIGIBLE_BASE_UNAVAILABLE")
    if minimum_n < 1:
        return QuantReadiness(QuantReadinessState.UNSUPPORTED_PROCEDURE, "INVALID_MINIMUM_BASE")
    if eligible_n < minimum_n:
        return QuantReadiness(QuantReadinessState.INSUFFICIENT_DATA, "BASE_BELOW_MINIMUM")
    if execution_status is None:
        return QuantReadiness(QuantReadinessState.READY, "PRECONDITIONS_MET")
    if execution_status in {AnalysisExecutionManifestStatus.COMPLETED,
                            AnalysisExecutionManifestStatus.COMPLETED_WITH_OPTIONAL_FAILURES,
                            AnalysisItemExecutionStatus.EXECUTED_WITH_RESULTS}:
        return QuantReadiness(QuantReadinessState.COMPLETED, "DETERMINISTIC_RESULT_PERSISTED")
    if execution_status is AnalysisItemExecutionStatus.EXECUTED_NO_VALID_RESULT:
        return QuantReadiness(QuantReadinessState.INSUFFICIENT_DATA, "NO_VALID_RESULT")
    return QuantReadiness(QuantReadinessState.COMPUTATION_FAILURE, "EXECUTION_OR_AUTHORITY_FAILURE")
