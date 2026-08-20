from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class QuantitativeReportSectionType(str, Enum):
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    KEY_FINDINGS = "KEY_FINDINGS"
    SEGMENT_RESULTS = "SEGMENT_RESULTS"
    KPI_RESULTS = "KPI_RESULTS"
    LIMITATIONS = "LIMITATIONS"


class QuantitativeReportValidationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    SUPPORTED = "SUPPORTED"


@dataclass(frozen=True)
class QuantitativeReportSupportReference:
    authority_id: str
    validation_fingerprint: str


@dataclass(frozen=True)
class QuantitativeReportSection:
    section_id: str
    section_type: QuantitativeReportSectionType
    title: str
    narrative: str
    finding_refs: tuple[QuantitativeReportSupportReference, ...] = ()
    insight_refs: tuple[QuantitativeReportSupportReference, ...] = ()
    referenced_display_values: tuple[str, ...] = ()
    authoritative_result_refs: tuple[str, ...] = ()
    authoritative_table_refs: tuple[str, ...] = ()
    weighting_status: str | None = None
    filter_definition: str | None = None
    base_definition: str | None = None
    direction: str | None = None


@dataclass(frozen=True)
class QuantitativeReport:
    report_id: str
    title: str
    sections: tuple[QuantitativeReportSection, ...]
    supporting_finding_refs: tuple[QuantitativeReportSupportReference, ...]
    supporting_insight_refs: tuple[QuantitativeReportSupportReference, ...]
    methodology: str = "QUANTITATIVE"
    analytical_support_fingerprint: str = ""
    validation_status: QuantitativeReportValidationStatus = QuantitativeReportValidationStatus.UNVALIDATED
    validation_fingerprint: str = ""
    generation_metadata: Mapping[str, Any] | None = None
    generation_version: str = "qk-1"


@dataclass(frozen=True)
class QuantitativeReportRejection:
    proposal_payload: Mapping[str, Any]
    reason: str
    rejection_fingerprint: str


@dataclass(frozen=True)
class QuantitativeReportCompositionResult:
    composition_id: str
    input_support_bundle_fingerprint: str
    generator_identity: str
    prompt_version: str
    prompt_fingerprint: str
    proposed_report: QuantitativeReport | None
    accepted_report: QuantitativeReport | None
    rejected_reports: tuple[QuantitativeReportRejection, ...]
    composition_metadata: Mapping[str, Any]
    composition_fingerprint: str
