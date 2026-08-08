from __future__ import annotations

from application.exceptions.structured_output_error import StructuredOutputError
from application.research_quality.sufficiency_diagnostics import (
    SufficiencyFailureDiagnostics,
)
from infrastructure.research_quality.sufficiency_structured_output import (
    StructuredOutputAttemptTelemetry,
    SufficiencyGenerationTelemetry,
)


def build_sufficiency_failure_diagnostics(
    *,
    structured_error: StructuredOutputError,
    telemetry: SufficiencyGenerationTelemetry | None,
    information_need_id: str | None = None,
    allowed_aspect_ids: tuple[str, ...] = (),
    attempt_record: StructuredOutputAttemptTelemetry | None = None,
) -> SufficiencyFailureDiagnostics:
    return SufficiencyFailureDiagnostics(
        structured_output_message=_structured_output_base_message(structured_error),
        stage=structured_error.stage,
        is_truncated=structured_error.is_truncated,
        attempts=(
            telemetry.attempts
            if telemetry is not None
            else structured_error.attempts
        ),
        finish_reason=_first_present(
            telemetry.finish_reason if telemetry else None,
            structured_error.finish_reason,
        ),
        output_tokens=_first_present(
            telemetry.output_tokens if telemetry else None,
            structured_error.output_tokens,
        ),
        max_output_tokens=_first_present(
            telemetry.max_output_tokens if telemetry else None,
            structured_error.max_output_tokens,
        ),
        reasoning_tokens=_first_present(
            telemetry.reasoning_tokens if telemetry else None,
            structured_error.reasoning_tokens,
        ),
        visible_output_length=_first_present(
            telemetry.visible_output_length if telemetry else None,
            structured_error.visible_output_length,
        ),
        parse_failure_category=(
            telemetry.parse_failure_category if telemetry is not None else None
        ),
        contract_failure_category=(
            telemetry.contract_failure_category if telemetry is not None else None
        ),
        contract_rejection_code=(
            attempt_record.contract_rejection_code if attempt_record is not None else None
        ),
        information_need_id=information_need_id,
        allowed_aspect_ids=(
            attempt_record.allowed_aspect_ids
            if attempt_record is not None and attempt_record.allowed_aspect_ids
            else allowed_aspect_ids
        ),
        returned_supported_aspects=(
            attempt_record.returned_supported_aspects if attempt_record is not None else ()
        ),
        returned_missing_aspects=(
            attempt_record.returned_missing_aspects if attempt_record is not None else ()
        ),
        unknown_aspect_ids=(
            attempt_record.unknown_aspect_ids if attempt_record is not None else ()
        ),
    )


def _structured_output_base_message(error: StructuredOutputError) -> str:
    text = str(error)
    if " (" in text:
        return text.split(" (", 1)[0]
    return text


def _first_present(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None
