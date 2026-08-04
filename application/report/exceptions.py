from __future__ import annotations


class ReportError(Exception):
    """Base report stage error."""


class ReportConfigurationError(ReportError):
    """Invalid report writer configuration."""


class DuplicateReportError(ReportError):
    """Concurrent or replayed report persistence conflict."""


class DuplicateArtifactError(ReportError):
    """Concurrent or replayed artifact persistence conflict."""


class InvalidReportProvenanceError(ReportError):
    """Report candidate references invalid analytical provenance."""

    def __init__(self, message: str, *, category: str | None = None) -> None:
        super().__init__(message)
        self.category = category
