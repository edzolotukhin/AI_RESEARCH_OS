from __future__ import annotations


class AnalysisError(Exception):
    """Base error for analysis stage failures."""


class AnalysisConfigurationError(AnalysisError):
    """Raised when analysis cannot run due to missing configuration."""


class DuplicateFindingError(AnalysisError):
    """Raised when a finding deduplication key already exists."""


class DuplicateInsightError(AnalysisError):
    """Raised when an insight deduplication key already exists."""


class InvalidAnalysisProvenanceError(AnalysisError):
    """Raised when candidate references fail run-scoped provenance validation."""

    def __init__(self, message: str, *, category: str | None = None) -> None:
        super().__init__(message)
        self.category = category


class FindingEntailmentError(AnalysisError):
    """Raised when Finding↔Evidence semantic entailment validation fails closed."""
