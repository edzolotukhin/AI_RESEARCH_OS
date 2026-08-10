"""Deterministic bounded Review support-context builder (P1-08).

Resolves Report → Finding / Insight / Evidence projections for semantic
claim-support review. Does not validate Finding↔Evidence Analysis entailment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reviews.review_issue import (
    ReviewIssue,
    ReviewIssueSeverity,
    ReviewIssueType,
)


DEFAULT_MAX_CHARS_PER_FINDING = 800
DEFAULT_MAX_CHARS_PER_INSIGHT = 600
DEFAULT_MAX_CHARS_PER_EVIDENCE = 800
DEFAULT_MAX_SUPPORT_CHARS_PER_SECTION = 4000


@dataclass(frozen=True)
class FindingSupportProjection:
    id: str
    statement: str
    rationale: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class InsightSupportProjection:
    id: str
    statement: str
    implication: str
    finding_refs: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceSupportProjection:
    id: str
    statement: str
    source_excerpt: str
    source_id: str


@dataclass(frozen=True)
class SectionSupportContext:
    section_id: str
    section_index: int
    findings: tuple[FindingSupportProjection, ...]
    insights: tuple[InsightSupportProjection, ...]
    evidence: tuple[EvidenceSupportProjection, ...]
    missing_finding_refs: tuple[str, ...] = ()
    missing_insight_refs: tuple[str, ...] = ()
    missing_evidence_refs: tuple[str, ...] = ()
    foreign_finding_refs: tuple[str, ...] = ()
    foreign_insight_refs: tuple[str, ...] = ()
    foreign_evidence_refs: tuple[str, ...] = ()
    omitted_finding_refs: tuple[str, ...] = ()
    omitted_insight_refs: tuple[str, ...] = ()
    omitted_evidence_refs: tuple[str, ...] = ()
    truncated: bool = False
    support_chars: int = 0


@dataclass(frozen=True)
class ReviewSupportContext:
    """Run/design-scoped support graph for one Review attempt."""

    project_id: str
    workflow_run_id: str
    research_design_id: str
    report_id: str
    report_revision: int
    sections: tuple[SectionSupportContext, ...]
    coverage_complete: bool
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def section_for_index(self, section_index: int) -> SectionSupportContext | None:
        for section in self.sections:
            if section.section_index == section_index:
                return section
        return None

    def render_for_section_indices(
        self,
        section_indices: tuple[int, ...],
        *,
        max_chars: int,
    ) -> str:
        """Deterministic support text for one RQ batch."""
        parts: list[str] = []
        for index in section_indices:
            section = self.section_for_index(index)
            if section is None:
                continue
            parts.append(f"[section_id={section.section_id} index={section.section_index}]")
            for finding in section.findings:
                parts.append(
                    "FINDING "
                    f"id={finding.id} statement={finding.statement} "
                    f"rationale={finding.rationale} "
                    f"evidence_refs={list(finding.evidence_refs)}"
                )
            for insight in section.insights:
                parts.append(
                    "INSIGHT "
                    f"id={insight.id} statement={insight.statement} "
                    f"implication={insight.implication} "
                    f"finding_refs={list(insight.finding_refs)}"
                )
            for evidence in section.evidence:
                parts.append(
                    "EVIDENCE "
                    f"id={evidence.id} statement={evidence.statement} "
                    f"source_excerpt={evidence.source_excerpt} "
                    f"source_id={evidence.source_id}"
                )
            if section.missing_finding_refs or section.missing_insight_refs or section.missing_evidence_refs:
                parts.append(
                    "MISSING_REFS "
                    f"findings={list(section.missing_finding_refs)} "
                    f"insights={list(section.missing_insight_refs)} "
                    f"evidence={list(section.missing_evidence_refs)}"
                )
            if section.foreign_finding_refs or section.foreign_insight_refs or section.foreign_evidence_refs:
                parts.append(
                    "FOREIGN_REFS "
                    f"findings={list(section.foreign_finding_refs)} "
                    f"insights={list(section.foreign_insight_refs)} "
                    f"evidence={list(section.foreign_evidence_refs)}"
                )
            if section.truncated:
                parts.append(
                    "SUPPORT_TRUNCATED "
                    f"omitted_findings={list(section.omitted_finding_refs)} "
                    f"omitted_insights={list(section.omitted_insight_refs)} "
                    f"omitted_evidence={list(section.omitted_evidence_refs)}"
                )
        text = "\n".join(parts)
        return text[:max_chars]


def _truncate(text: str, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit]


def _is_in_scope(
    *,
    project_id: str,
    workflow_run_id: str,
    research_design_id: str,
    candidate_project_id: str,
    candidate_run_id: str,
    candidate_design_id: str,
) -> bool:
    return (
        candidate_project_id == project_id
        and candidate_run_id == workflow_run_id
        and candidate_design_id == research_design_id
    )


def build_review_support_context(
    *,
    report: Report,
    findings: list[Finding] | tuple[Finding, ...],
    insights: list[Insight] | tuple[Insight, ...],
    evidence_items: list[Evidence] | tuple[Evidence, ...],
    max_chars_per_finding: int = DEFAULT_MAX_CHARS_PER_FINDING,
    max_chars_per_insight: int = DEFAULT_MAX_CHARS_PER_INSIGHT,
    max_chars_per_evidence: int = DEFAULT_MAX_CHARS_PER_EVIDENCE,
    max_support_chars_per_section: int = DEFAULT_MAX_SUPPORT_CHARS_PER_SECTION,
) -> ReviewSupportContext:
    """Build run/design-scoped bounded support projections for Review."""
    findings_by_id = {item.id: item for item in findings}
    insights_by_id = {item.id: item for item in insights}
    evidence_by_id = {item.id: item for item in evidence_items}

    sections: list[SectionSupportContext] = []
    total_missing = 0
    total_foreign = 0
    total_truncated_sections = 0
    total_findings = 0
    total_insights = 0
    total_evidence = 0

    for index, section in enumerate(report.sections):
        selected_findings: list[FindingSupportProjection] = []
        selected_insights: list[InsightSupportProjection] = []
        selected_evidence: list[EvidenceSupportProjection] = []
        missing_findings: list[str] = []
        missing_insights: list[str] = []
        missing_evidence: list[str] = []
        foreign_findings: list[str] = []
        foreign_insights: list[str] = []
        foreign_evidence: list[str] = []
        omitted_findings: list[str] = []
        omitted_insights: list[str] = []
        omitted_evidence: list[str] = []
        used_chars = 0
        truncated = False

        def _budget_allows(size: int) -> bool:
            return used_chars + size <= max_support_chars_per_section

        # Priority 2: directly referenced Findings (stable ID order)
        for finding_id in sorted(section.finding_refs):
            finding = findings_by_id.get(finding_id)
            if finding is None:
                missing_findings.append(finding_id)
                continue
            if not _is_in_scope(
                project_id=report.project_id,
                workflow_run_id=report.workflow_run_id,
                research_design_id=report.research_design_id,
                candidate_project_id=finding.project_id,
                candidate_run_id=finding.workflow_run_id,
                candidate_design_id=finding.research_design_id,
            ):
                foreign_findings.append(finding_id)
                continue
            half = max(1, max_chars_per_finding // 2)
            projection = FindingSupportProjection(
                id=finding.id,
                statement=_truncate(finding.statement, half),
                rationale=_truncate(finding.rationale, half),
                evidence_refs=tuple(finding.evidence_refs),
            )
            size = len(projection.statement) + len(projection.rationale) + len(projection.id)
            if not _budget_allows(size):
                truncated = True
                omitted_findings.append(finding_id)
                continue
            selected_findings.append(projection)
            used_chars += size

        # Priority 3: directly referenced Insights
        for insight_id in sorted(section.insight_refs):
            insight = insights_by_id.get(insight_id)
            if insight is None:
                missing_insights.append(insight_id)
                continue
            if not _is_in_scope(
                project_id=report.project_id,
                workflow_run_id=report.workflow_run_id,
                research_design_id=report.research_design_id,
                candidate_project_id=insight.project_id,
                candidate_run_id=insight.workflow_run_id,
                candidate_design_id=insight.research_design_id,
            ):
                foreign_insights.append(insight_id)
                continue
            half = max(1, max_chars_per_insight // 2)
            projection = InsightSupportProjection(
                id=insight.id,
                statement=_truncate(insight.statement, half),
                implication=_truncate(insight.implication, half),
                finding_refs=tuple(insight.finding_refs),
            )
            size = len(projection.statement) + len(projection.implication) + len(projection.id)
            if not _budget_allows(size):
                truncated = True
                omitted_insights.append(insight_id)
                continue
            selected_insights.append(projection)
            used_chars += size

        # Priority 4+5: Evidence from section refs, then Finding.evidence_refs
        evidence_ids: list[str] = []
        seen_evidence: set[str] = set()
        for evidence_id in sorted(section.evidence_refs):
            if evidence_id not in seen_evidence:
                seen_evidence.add(evidence_id)
                evidence_ids.append(evidence_id)
        for finding in selected_findings:
            for evidence_id in sorted(finding.evidence_refs):
                if evidence_id not in seen_evidence:
                    seen_evidence.add(evidence_id)
                    evidence_ids.append(evidence_id)

        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                missing_evidence.append(evidence_id)
                continue
            if not _is_in_scope(
                project_id=report.project_id,
                workflow_run_id=report.workflow_run_id,
                research_design_id=report.research_design_id,
                candidate_project_id=evidence.project_id,
                candidate_run_id=evidence.workflow_run_id,
                candidate_design_id=evidence.research_design_id,
            ):
                foreign_evidence.append(evidence_id)
                continue
            half = max(1, max_chars_per_evidence // 2)
            projection = EvidenceSupportProjection(
                id=evidence.id,
                statement=_truncate(evidence.statement, half),
                source_excerpt=_truncate(evidence.source_excerpt, half),
                source_id=evidence.source_id,
            )
            size = (
                len(projection.statement)
                + len(projection.source_excerpt)
                + len(projection.id)
            )
            if not _budget_allows(size):
                truncated = True
                omitted_evidence.append(evidence_id)
                continue
            selected_evidence.append(projection)
            used_chars += size

        if truncated:
            total_truncated_sections += 1
        total_missing += (
            len(missing_findings) + len(missing_insights) + len(missing_evidence)
        )
        total_foreign += (
            len(foreign_findings) + len(foreign_insights) + len(foreign_evidence)
        )
        total_findings += len(selected_findings)
        total_insights += len(selected_insights)
        total_evidence += len(selected_evidence)

        sections.append(
            SectionSupportContext(
                section_id=section.id,
                section_index=index,
                findings=tuple(selected_findings),
                insights=tuple(selected_insights),
                evidence=tuple(selected_evidence),
                missing_finding_refs=tuple(missing_findings),
                missing_insight_refs=tuple(missing_insights),
                missing_evidence_refs=tuple(missing_evidence),
                foreign_finding_refs=tuple(foreign_findings),
                foreign_insight_refs=tuple(foreign_insights),
                foreign_evidence_refs=tuple(foreign_evidence),
                omitted_finding_refs=tuple(omitted_findings),
                omitted_insight_refs=tuple(omitted_insights),
                omitted_evidence_refs=tuple(omitted_evidence),
                truncated=truncated,
                support_chars=used_chars,
            ),
        )

    coverage_complete = total_missing == 0 and total_foreign == 0 and total_truncated_sections == 0
    diagnostics = {
        "report_revision": report.revision_number,
        "sections_reviewed": len(sections),
        "findings_included": total_findings,
        "insights_included": total_insights,
        "evidence_included": total_evidence,
        "missing_refs": total_missing,
        "foreign_refs": total_foreign,
        "truncated_support_sections": total_truncated_sections,
        "support_coverage_complete": coverage_complete,
    }
    return ReviewSupportContext(
        project_id=report.project_id,
        workflow_run_id=report.workflow_run_id,
        research_design_id=report.research_design_id,
        report_id=report.id,
        report_revision=report.revision_number,
        sections=tuple(sections),
        coverage_complete=coverage_complete,
        diagnostics=diagnostics,
    )


def support_reference_issues(
    support: ReviewSupportContext,
) -> tuple[ReviewIssue, ...]:
    """Fail-closed major issues for missing/foreign/truncated support.

    Uses existing ReviewIssueType values only:
    - UNSUPPORTED_CLAIM for missing/foreign claim support refs
    - STRUCTURE_ISSUE for truncated support unavailable to semantic review
    """
    issues: list[ReviewIssue] = []
    for section in support.sections:
        if section.missing_finding_refs:
            issues.append(
                _issue(
                    ReviewIssueType.UNSUPPORTED_CLAIM,
                    (
                        "Referenced Finding(s) missing from run/design scope: "
                        f"{list(section.missing_finding_refs)}"
                    ),
                    report_section_id=section.section_id,
                    finding_refs=section.missing_finding_refs,
                    metadata={"support_failure": "missing_finding"},
                ),
            )
        if section.missing_insight_refs:
            issues.append(
                _issue(
                    ReviewIssueType.UNSUPPORTED_CLAIM,
                    (
                        "Referenced Insight(s) missing from run/design scope: "
                        f"{list(section.missing_insight_refs)}"
                    ),
                    report_section_id=section.section_id,
                    insight_refs=section.missing_insight_refs,
                    metadata={"support_failure": "missing_insight"},
                ),
            )
        if section.missing_evidence_refs:
            issues.append(
                _issue(
                    ReviewIssueType.UNSUPPORTED_CLAIM,
                    (
                        "Referenced Evidence missing from run/design scope: "
                        f"{list(section.missing_evidence_refs)}"
                    ),
                    report_section_id=section.section_id,
                    evidence_refs=section.missing_evidence_refs,
                    metadata={"support_failure": "missing_evidence"},
                ),
            )
        if section.foreign_finding_refs:
            issues.append(
                _issue(
                    ReviewIssueType.UNSUPPORTED_CLAIM,
                    (
                        "Foreign Finding reference(s) rejected for claim support: "
                        f"{list(section.foreign_finding_refs)}"
                    ),
                    report_section_id=section.section_id,
                    finding_refs=section.foreign_finding_refs,
                    metadata={"support_failure": "foreign_finding"},
                ),
            )
        if section.foreign_insight_refs:
            issues.append(
                _issue(
                    ReviewIssueType.UNSUPPORTED_CLAIM,
                    (
                        "Foreign Insight reference(s) rejected for claim support: "
                        f"{list(section.foreign_insight_refs)}"
                    ),
                    report_section_id=section.section_id,
                    insight_refs=section.foreign_insight_refs,
                    metadata={"support_failure": "foreign_insight"},
                ),
            )
        if section.foreign_evidence_refs:
            issues.append(
                _issue(
                    ReviewIssueType.UNSUPPORTED_CLAIM,
                    (
                        "Foreign Evidence reference(s) rejected for claim support: "
                        f"{list(section.foreign_evidence_refs)}"
                    ),
                    report_section_id=section.section_id,
                    evidence_refs=section.foreign_evidence_refs,
                    metadata={"support_failure": "foreign_evidence"},
                ),
            )
        if section.truncated and (
            section.omitted_finding_refs
            or section.omitted_insight_refs
            or section.omitted_evidence_refs
        ):
            issues.append(
                _issue(
                    ReviewIssueType.STRUCTURE_ISSUE,
                    (
                        "Referenced support truncated and unavailable to semantic "
                        "review for claim validation; cannot APPROVE incomplete "
                        f"support coverage for section {section.section_id}"
                    ),
                    report_section_id=section.section_id,
                    finding_refs=section.omitted_finding_refs,
                    insight_refs=section.omitted_insight_refs,
                    evidence_refs=section.omitted_evidence_refs,
                    metadata={
                        "support_failure": "truncated_support",
                        "omitted_finding_refs": list(section.omitted_finding_refs),
                        "omitted_insight_refs": list(section.omitted_insight_refs),
                        "omitted_evidence_refs": list(section.omitted_evidence_refs),
                    },
                ),
            )
    return tuple(issues)


def incomplete_review_coverage_issue(
    *,
    omitted_batch_ids: tuple[str, ...],
    max_batches: int,
) -> ReviewIssue:
    """Fail-closed when Review call envelope cannot cover all RQ groups."""
    return _issue(
        ReviewIssueType.STRUCTURE_ISSUE,
        (
            "Review call envelope insufficient for complete semantic coverage; "
            f"omitted_batches={list(omitted_batch_ids)} max_batches={max_batches}. "
            "Cannot APPROVE a partially reviewed report."
        ),
        metadata={
            "support_failure": "incomplete_review_coverage",
            "omitted_batch_ids": list(omitted_batch_ids),
            "max_batches": max_batches,
        },
    )


def _issue(
    issue_type: ReviewIssueType,
    message: str,
    *,
    report_section_id: str | None = None,
    finding_refs: tuple[str, ...] = (),
    insight_refs: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> ReviewIssue:
    return ReviewIssue(
        id=str(uuid4()),
        issue_type=issue_type,
        severity=ReviewIssueSeverity.MAJOR,
        message=message,
        report_section_id=report_section_id,
        finding_refs=finding_refs,
        insight_refs=insight_refs,
        evidence_refs=evidence_refs,
        suggested_action="Resolve support references or revise the report claim",
        metadata=dict(metadata or {}),
    )
