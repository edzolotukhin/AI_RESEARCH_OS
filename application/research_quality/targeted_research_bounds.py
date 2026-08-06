from __future__ import annotations

from dataclasses import dataclass

from application.config import ApplicationConfig


@dataclass(frozen=True)
class TargetedResearchBounds:
    max_gap_rounds_per_run: int = 2
    max_attempts_per_gap: int = 2
    max_queries_per_gap: int = 2
    max_sources_per_gap: int = 3

    @classmethod
    def from_config(cls, config: ApplicationConfig) -> TargetedResearchBounds:
        return cls(
            max_gap_rounds_per_run=config.research_max_gap_rounds_per_run,
            max_attempts_per_gap=config.targeted_max_attempts_per_gap,
            max_queries_per_gap=config.targeted_max_queries_per_gap,
            max_sources_per_gap=config.targeted_max_sources_per_gap,
        )
