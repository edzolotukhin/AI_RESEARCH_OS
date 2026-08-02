from __future__ import annotations


class ReviewError(Exception):
    """Review stage failed to complete the quality gate."""


class ReviewConfigurationError(Exception):
    """Review engine or LLM configuration failed."""


class DuplicateReviewError(Exception):
    """Concurrent review persistence conflict."""


class InvalidReviewProvenanceError(Exception):
    """Review references are out of run scope."""
