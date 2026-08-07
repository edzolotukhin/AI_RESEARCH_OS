"""Technical failures during semantic sufficiency assessment."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from application.research_quality.sufficiency_diagnostics import (
        SufficiencyFailureDiagnostics,
    )


class SemanticSufficiencyAssessmentError(Exception):
    """Raised when semantic sufficiency assessment fails for technical reasons."""

    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        diagnostics: SufficiencyFailureDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.diagnostics = diagnostics
