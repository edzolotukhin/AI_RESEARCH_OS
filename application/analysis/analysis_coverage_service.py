"""Deterministic post-analysis coverage assessment.

This module is deliberately side-effect free.  It qualifies persisted Evidence
through the canonical citation/temporal boundary and then verifies that every
required Information Need is supported by at least one persisted Finding whose
Evidence references remain wholly resolvable inside that qualified authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from application.evidence.temporal_scope import qualifying_evidence
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.research_brief import ResearchBrief
from domain.planning.research_design import ResearchDesign


ANALYSIS_COVERAGE_DIAGNOSTIC_VERSION = "analysis_coverage_v1"


class UnknownInformationNeedError(ValueError):
    """Raised when a caller supplies an IN outside the immutable design."""


@dataclass(frozen=True)
class AnalysisCoverageResult:
    required_information_need_ids: tuple[str, ...]
    covered_information_need_ids: tuple[str, ...]
    missing_information_need_ids: tuple[str, ...]
    evidence_without_finding: tuple[str, ...]
    fully_covered: bool
    diagnostic_version: str = ANALYSIS_COVERAGE_DIAGNOSTIC_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_information_need_ids": list(self.required_information_need_ids),
            "covered_information_need_ids": list(self.covered_information_need_ids),
            "missing_information_need_ids": list(self.missing_information_need_ids),
            "evidence_without_finding": list(self.evidence_without_finding),
            "fully_covered": self.fully_covered,
            "diagnostic_version": self.diagnostic_version,
        }


def assess_analysis_coverage(
    *,
    project_id: str,
    design: ResearchDesign,
    findings: Sequence[Finding],
    evidence: Sequence[Evidence],
    brief: ResearchBrief | None,
    source_repository,
    required_information_need_ids: Iterable[str] | None = None,
) -> AnalysisCoverageResult:
    """Return exact required-IN coverage without mutating persisted authority.

    A Finding covers an Information Need only when all of its Evidence refs are
    present in the canonically qualified Evidence set and at least one cited
    Evidence item supports that same Information Need.  Cross-project and
    cross-design references fail closed.
    """

    design_need_ids = {item.id for item in design.information_needs}
    requested = (
        design_need_ids
        if required_information_need_ids is None
        else {str(item) for item in required_information_need_ids}
    )
    unknown = tuple(sorted(requested - design_need_ids))
    if unknown:
        raise UnknownInformationNeedError(
            f"Required Information Needs are outside the Research Design: {unknown}"
        )
    required = tuple(sorted(requested))

    qualified = qualifying_evidence(
        design=design,
        evidence=evidence,
        brief=brief,
        source_repository=source_repository,
    )
    evidence_by_id = {
        item.id: item
        for item in qualified
        if item.project_id == project_id and item.research_design_id == design.id
    }

    covered: set[str] = set()
    for finding in findings:
        if finding.project_id != project_id or finding.research_design_id != design.id or not finding.evidence_refs:
            continue
        cited = tuple(evidence_by_id.get(item) for item in finding.evidence_refs)
        if any(item is None for item in cited):
            continue
        resolved = tuple(item for item in cited if item is not None)
        if any(item.project_id != project_id for item in resolved):
            continue
        for need_id in set(finding.information_need_refs) & set(required):
            if any(need_id in item.information_need_refs for item in resolved):
                covered.add(need_id)

    missing = tuple(sorted(set(required) - covered))
    evidence_without_finding = tuple(sorted({
        item.id
        for item in evidence_by_id.values()
        if set(item.information_need_refs).intersection(missing)
    }))
    covered_ids = tuple(sorted(covered))
    return AnalysisCoverageResult(
        required_information_need_ids=required,
        covered_information_need_ids=covered_ids,
        missing_information_need_ids=missing,
        evidence_without_finding=evidence_without_finding,
        fully_covered=not missing,
    )
