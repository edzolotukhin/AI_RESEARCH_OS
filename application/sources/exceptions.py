from __future__ import annotations


class SearchProviderError(RuntimeError):
    """Raised when a search provider request fails."""


class SourceAcquisitionError(RuntimeError):
    """Raised when source acquisition cannot satisfy the minimum contract."""


class SearchConfigurationError(RuntimeError):
    """Raised when search capability is invoked without required configuration."""


class DuplicateSourceError(Exception):
    """Raised when a source already exists for project_id + canonical_url."""
