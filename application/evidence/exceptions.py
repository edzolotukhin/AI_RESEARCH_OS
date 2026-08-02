from __future__ import annotations


class EvidenceExtractionError(RuntimeError):
    """Raised when evidence extraction cannot satisfy the minimum contract."""


class DuplicateEvidenceError(Exception):
    """Raised when evidence already exists for run + deduplication key."""


class UngroundedEvidenceError(ValueError):
    """Raised when an excerpt cannot be verified against source content."""


class EvidenceConfigurationError(RuntimeError):
    """Raised when evidence extraction is invoked without required configuration."""
