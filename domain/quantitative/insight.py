from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class QuantitativeInsightType(str, Enum):
    SYNTHESIS = "SYNTHESIS"
    SEGMENT_CONTRAST = "SEGMENT_CONTRAST"
    KPI_INTERPRETATION = "KPI_INTERPRETATION"
    LIMITATION = "LIMITATION"


class QuantitativeInsightValidationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    SUPPORTED = "SUPPORTED"


@dataclass(frozen=True)
class QuantitativeFindingReference:
    finding_id: str
    support_validation_fingerprint: str


@dataclass(frozen=True)
class QuantitativeInsight:
    insight_id: str
    insight_text: str
    insight_type: QuantitativeInsightType
    supporting_finding_refs: tuple[QuantitativeFindingReference, ...]
    referenced_display_values: tuple[str, ...] = ()
    direction: str | None = None
    limitation_note: str | None = None
    methodology: str = "QUANTITATIVE"
    support_context_fingerprint: str = ""
    validation_status: QuantitativeInsightValidationStatus = QuantitativeInsightValidationStatus.UNVALIDATED
    validation_fingerprint: str = ""
    validation_version: str = "qj-1"


@dataclass(frozen=True)
class QuantitativeInsightRejection:
    proposal_ordinal: int
    proposal_payload: Mapping[str, Any]
    reason: str
    rejection_fingerprint: str


@dataclass(frozen=True)
class QuantitativeInsightGenerationResult:
    generation_id: str
    input_finding_bundle_fingerprint: str
    generator_identity: str
    prompt_version: str
    prompt_fingerprint: str
    proposed_insights: tuple[QuantitativeInsight, ...]
    accepted_insights: tuple[QuantitativeInsight, ...]
    rejected_insights: tuple[QuantitativeInsightRejection, ...]
    generation_metadata: Mapping[str, Any]
    acceptance_summary: Mapping[str, int]
    generation_fingerprint: str
