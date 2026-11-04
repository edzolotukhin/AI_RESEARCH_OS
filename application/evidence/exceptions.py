from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from application.evidence.evidence_extraction_service import EvidenceExtractionSummary


class EvidenceExtractionError(RuntimeError):
    """Raised when evidence extraction cannot satisfy the minimum contract."""

    def __init__(
        self,
        message: str,
        *,
        summary: EvidenceExtractionSummary | None = None,
    ) -> None:
        super().__init__(message)
        self.summary = summary


class DuplicateEvidenceError(Exception):
    """Raised when evidence already exists for run + deduplication key."""


class UngroundedEvidenceError(ValueError):
    """Raised when an excerpt cannot be verified against source content."""


class EvidenceConfigurationError(RuntimeError):
    """Raised when evidence extraction is invoked without required configuration."""

    def __init__(
        self,
        message: str,
        *,
        original_exception_class: str | None = None,
        failure_category: str = "provider_exception",
        failure_phase: str = "unknown",
        retry_ambiguous: bool = False,
        operation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.original_exception_class = original_exception_class
        self.failure_category = failure_category
        self.failure_phase = failure_phase
        self.retry_ambiguous = retry_ambiguous
        self.operation_id = operation_id


class EvidenceResponseOutcomeError(ValueError):
    """Raised when an Evidence LLM response outcome is fail-closed."""

    def __init__(
        self,
        message: str,
        *,
        classification: str,
    ) -> None:
        super().__init__(message)
        self.classification = classification
