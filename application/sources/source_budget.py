"""Product-level latency and workload bounds for source acquisition."""

from __future__ import annotations

import os
from dataclasses import dataclass

from application.config import ApplicationConfig


@dataclass(frozen=True)
class SourceAcquisitionBudget:
    """
    Bounded v1 source acquisition limits for live desk-research use.

    Defaults target ~15 minute wall-clock cap with coverage-aware early exit,
    not merely a minimum source count.
    """

    max_candidates_per_query: int = 5
    max_candidates_per_information_need: int = 5
    max_sources_per_run: int = 30
    http_timeout_seconds: float = 10.0
    max_redirects: int = 5
    max_body_bytes: int = 512_000
    acquisition_max_seconds: float = 900.0
    min_successful_sources: int = 3
    min_information_need_coverage_ratio: float = 1.0
    dns_timeout_seconds: float = 5.0

    @classmethod
    def from_config(cls, config: ApplicationConfig) -> SourceAcquisitionBudget:
        return cls(
            max_candidates_per_query=config.source_max_candidates_per_query,
            max_candidates_per_information_need=(
                config.source_max_candidates_per_information_need
            ),
            max_sources_per_run=config.source_max_sources_per_run,
            http_timeout_seconds=config.source_http_timeout_seconds,
            max_redirects=config.source_max_redirects,
            max_body_bytes=config.source_max_body_bytes,
            acquisition_max_seconds=config.source_acquisition_max_seconds,
            min_successful_sources=config.source_min_successful_sources,
            min_information_need_coverage_ratio=(
                config.source_min_information_need_coverage_ratio
            ),
            dns_timeout_seconds=config.source_dns_timeout_seconds,
        )

    @classmethod
    def from_env(cls) -> SourceAcquisitionBudget:
        return cls(
            max_candidates_per_query=int(
                os.environ.get("SOURCE_MAX_CANDIDATES_PER_QUERY", "5"),
            ),
            max_candidates_per_information_need=int(
                os.environ.get("SOURCE_MAX_CANDIDATES_PER_INFORMATION_NEED", "5"),
            ),
            max_sources_per_run=int(
                os.environ.get("SOURCE_MAX_SOURCES_PER_RUN", "30"),
            ),
            http_timeout_seconds=float(
                os.environ.get("SOURCE_HTTP_TIMEOUT_SECONDS", "10"),
            ),
            max_redirects=int(os.environ.get("SOURCE_MAX_REDIRECTS", "5")),
            max_body_bytes=int(
                os.environ.get("SOURCE_MAX_BODY_BYTES", "512000"),
            ),
            acquisition_max_seconds=float(
                os.environ.get("SOURCE_ACQUISITION_MAX_SECONDS", "900"),
            ),
            min_successful_sources=int(
                os.environ.get("SOURCE_MIN_SUCCESSFUL_SOURCES", "3"),
            ),
            min_information_need_coverage_ratio=float(
                os.environ.get("SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO", "1.0"),
            ),
            dns_timeout_seconds=float(
                os.environ.get("SOURCE_DNS_TIMEOUT_SECONDS", "5"),
            ),
        )
