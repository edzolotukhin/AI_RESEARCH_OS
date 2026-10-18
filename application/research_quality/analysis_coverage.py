from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.research_quality.gap_type import GapType
from domain.research_quality.research_readiness_result import ResearchReadinessResult
from domain.research_quality.sufficiency_status import SufficiencyStatus


COVERAGE_SNAPSHOT_VERSION = "desk_coverage_v1"


@dataclass(frozen=True)
class AnalysisCoverageSnapshot:
    complete_design_ready: bool
    eligible_information_need_ids: tuple[str, ...]
    supported_aspects_by_information_need: dict[str, tuple[str, ...]]
    partial_information_need_ids: tuple[str, ...]
    insufficient_information_need_ids: tuple[str, ...]
    missing_information_need_ids: tuple[str, ...]
    blocked_information_need_ids: tuple[str, ...]
    missing_aspects_by_information_need: dict[str, tuple[str, ...]]
    contradictions_by_information_need: dict[str, tuple[str, ...]]
    source_diversity_limited_information_need_ids: tuple[str, ...]
    version: str = COVERAGE_SNAPSHOT_VERSION

    @property
    def analysis_ready(self) -> bool:
        return bool(self.eligible_information_need_ids)

    @property
    def report_scope(self) -> str:
        return "complete" if self.complete_design_ready else "limited"

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_snapshot_version": self.version,
            "report_scope": self.report_scope,
            "complete_design_ready": self.complete_design_ready,
            "analysis_ready": self.analysis_ready,
            "covered_information_need_ids": list(self.eligible_information_need_ids),
            "analysis_eligible_information_need_ids": list(self.eligible_information_need_ids),
            "covered_required_aspect_refs": {
                key: list(value)
                for key, value in sorted(self.supported_aspects_by_information_need.items())
            },
            "partial_information_need_ids": list(self.partial_information_need_ids),
            "insufficient_information_need_ids": list(self.insufficient_information_need_ids),
            "missing_information_need_ids": list(self.missing_information_need_ids),
            "blocked_information_need_ids": list(self.blocked_information_need_ids),
            "missing_required_aspect_refs": {
                key: list(value)
                for key, value in sorted(self.missing_aspects_by_information_need.items())
            },
            "contradictions": {
                key: list(value)
                for key, value in sorted(self.contradictions_by_information_need.items())
            },
            "source_diversity_limited_information_need_ids": list(
                self.source_diversity_limited_information_need_ids
            ),
        }


def build_analysis_coverage_snapshot(
    result: ResearchReadinessResult,
) -> AnalysisCoverageSnapshot:
    needs = sorted(
        (
            need
            for rq in result.research_question_assessments
            for need in rq.information_need_assessments
        ),
        key=lambda item: item.information_need_id,
    )
    eligible = set(result.analysis_eligible_information_need_ids)
    supported = {
        need.information_need_id: tuple(sorted(need.supported_aspects))
        for need in needs
        if need.information_need_id in eligible and need.supported_aspects
    }
    missing_aspects = {
        need.information_need_id: tuple(sorted(need.missing_aspects))
        for need in needs
        if need.missing_aspects
    }
    contradictions = {
        need.information_need_id: tuple(sorted(need.contradictions))
        for need in needs
        if need.contradictions
    }
    return AnalysisCoverageSnapshot(
        complete_design_ready=bool(result.complete_design_ready),
        eligible_information_need_ids=tuple(sorted(eligible)),
        supported_aspects_by_information_need=supported,
        partial_information_need_ids=tuple(
            need.information_need_id for need in needs
            if need.status == SufficiencyStatus.PARTIAL
        ),
        insufficient_information_need_ids=tuple(
            need.information_need_id for need in needs
            if need.status == SufficiencyStatus.INSUFFICIENT
        ),
        missing_information_need_ids=tuple(
            need.information_need_id for need in needs
            if need.status == SufficiencyStatus.MISSING
        ),
        blocked_information_need_ids=tuple(
            need.information_need_id for need in needs
            if need.status == SufficiencyStatus.BLOCKED or not need.assessment_current
        ),
        missing_aspects_by_information_need=missing_aspects,
        contradictions_by_information_need=contradictions,
        source_diversity_limited_information_need_ids=tuple(
            need.information_need_id for need in needs
            if GapType.INSUFFICIENT_DIVERSITY in need.gap_types
        ),
    )


def coverage_snapshot_from_payload(payload: Any) -> AnalysisCoverageSnapshot | None:
    if not isinstance(payload, dict):
        return None
    try:
        result = ResearchReadinessResult.from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None
    return build_analysis_coverage_snapshot(result)
