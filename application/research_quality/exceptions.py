"""Technical failures during semantic sufficiency assessment."""

from __future__ import annotations


class SemanticSufficiencyAssessmentError(Exception):
    """Raised when semantic sufficiency assessment fails for technical reasons."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause
