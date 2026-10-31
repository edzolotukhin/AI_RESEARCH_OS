"""Deterministic, bounded coverage planning for the H3 claim boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign


@dataclass(frozen=True)
class H3CoverageSlot:
    information_need_id: str
    research_question_id: str
    finding_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    insight_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "information_need_id": self.information_need_id,
            "research_question_id": self.research_question_id,
            "finding_ids": list(self.finding_ids),
            "evidence_ids": list(self.evidence_ids),
            "insight_ids": list(self.insight_ids),
        }


@dataclass(frozen=True)
class H3UnfillableInformationNeed:
    information_need_id: str
    research_question_id: str
    authority_layer_required: str
    evidence_count: int
    finding_count: int
    reason_code: str = "required_information_need_unfillable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "information_need_id": self.information_need_id,
            "research_question_id": self.research_question_id,
            "coverability": "UNFILLABLE",
            "authority_layer_required": self.authority_layer_required,
            "evidence_count": self.evidence_count,
            "finding_count": self.finding_count,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class H3CoveragePlan:
    required_information_need_ids: tuple[str, ...]
    coverable_slots: tuple[H3CoverageSlot, ...]
    unfillable_required_information_needs: tuple[H3UnfillableInformationNeed, ...]

    @property
    def is_fully_fillable(self) -> bool:
        return not self.unfillable_required_information_needs

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "desk_h3_coverage_plan_v1",
            "required_information_need_ids": list(self.required_information_need_ids),
            "coverable_slots": [item.to_dict() for item in self.coverable_slots],
            "unfillable_required_information_needs": [
                item.to_dict() for item in self.unfillable_required_information_needs
            ],
        }


def build_h3_coverage_plan(
    *, design: ResearchDesign, required_information_need_ids: tuple[str, ...],
    findings: tuple[Finding, ...], evidence_by_id: dict[str, Evidence],
    insights: tuple[Insight, ...],
) -> H3CoveragePlan:
    """Build slots from existing Finding authority only.

    Evidence without a Finding is deliberately never promoted to a slot.
    """
    finding_by_need: dict[str, list[Finding]] = {item: [] for item in required_information_need_ids}
    for finding in findings:
        for need_id in finding.information_need_refs:
            if need_id in finding_by_need:
                finding_by_need[need_id].append(finding)
    slots: list[H3CoverageSlot] = []
    gaps: list[H3UnfillableInformationNeed] = []
    for need in design.information_needs:
        if need.id not in finding_by_need:
            continue
        matching = tuple(sorted(finding_by_need[need.id], key=lambda item: item.id))
        finding_ids = tuple(item.id for item in matching)
        evidence_ids = tuple(sorted({
            evidence_id for item in matching for evidence_id in item.evidence_refs
            if evidence_id in evidence_by_id
        }))
        insight_ids = tuple(sorted({
            insight.id for insight in insights
            if any(finding.id in insight.finding_refs for finding in matching)
        }))
        if not matching:
            evidence_count = sum(
                1 for item in evidence_by_id.values() if need.id in item.information_need_refs
            )
            gaps.append(H3UnfillableInformationNeed(
                need.id, need.research_question_id, "finding", evidence_count, 0,
            ))
            continue
        slots.append(H3CoverageSlot(
            need.id, need.research_question_id, finding_ids, evidence_ids, insight_ids,
        ))
    return H3CoveragePlan(
        tuple(sorted(required_information_need_ids)), tuple(slots), tuple(gaps),
    )
