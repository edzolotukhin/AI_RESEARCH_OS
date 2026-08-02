from __future__ import annotations

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign

from application.ports.report_ports import ReportSectionCandidate
from application.report.exceptions import InvalidReportProvenanceError


def _validate_refs_in_run(
    *,
    project_id: str,
    workflow_run_id: str,
    research_design_id: str,
) -> None:
    if not project_id or not workflow_run_id or not research_design_id:
        raise InvalidReportProvenanceError("Report provenance scope is incomplete")


def validate_section_candidate(
    candidate: ReportSectionCandidate,
    *,
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
    evidence_by_id: dict[str, Evidence],
    project_id: str,
    workflow_run_id: str,
    research_design_id: str,
    design: ResearchDesign,
) -> ReportSectionCandidate:
    _validate_refs_in_run(
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        research_design_id=research_design_id,
    )
    if not candidate.title.strip():
        raise InvalidReportProvenanceError("Report section title must not be empty")
    if not candidate.content.strip():
        raise InvalidReportProvenanceError("Report section content must not be empty")
    if not candidate.finding_refs and not candidate.insight_refs:
        raise InvalidReportProvenanceError(
            "Report section must reference at least one Finding or Insight",
        )

    allowed_questions = {question.id for question in design.research_questions}

    for finding_id in candidate.finding_refs:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            raise InvalidReportProvenanceError(f"Unknown finding reference: {finding_id}")
        _assert_scope(finding.project_id, finding.workflow_run_id, finding.research_design_id)

    for insight_id in candidate.insight_refs:
        insight = insights_by_id.get(insight_id)
        if insight is None:
            raise InvalidReportProvenanceError(f"Unknown insight reference: {insight_id}")
        _assert_scope(insight.project_id, insight.workflow_run_id, insight.research_design_id)

    for evidence_id in candidate.evidence_refs:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise InvalidReportProvenanceError(f"Unknown evidence reference: {evidence_id}")
        _assert_scope(evidence.project_id, evidence.workflow_run_id, evidence.research_design_id)

    question_refs = tuple(
        ref for ref in candidate.research_question_refs if ref in allowed_questions
    )

    return ReportSectionCandidate(
        title=candidate.title.strip(),
        content=candidate.content.strip(),
        research_question_refs=question_refs,
        finding_refs=tuple(sorted(set(candidate.finding_refs))),
        insight_refs=tuple(sorted(set(candidate.insight_refs))),
        evidence_refs=tuple(sorted(set(candidate.evidence_refs))),
        metadata=dict(candidate.metadata or {}),
    )


def _assert_scope(project_id: str, workflow_run_id: str, research_design_id: str) -> None:
    if not project_id or not workflow_run_id or not research_design_id:
        raise InvalidReportProvenanceError("Referenced record has incomplete provenance scope")


def collect_evidence_refs_for_section(
    section: ReportSectionCandidate,
    *,
    findings_by_id: dict[str, Finding],
    insights_by_id: dict[str, Insight],
) -> tuple[str, ...]:
    evidence_refs: set[str] = set(section.evidence_refs)
    for finding_id in section.finding_refs:
        finding = findings_by_id.get(finding_id)
        if finding is not None:
            evidence_refs.update(finding.evidence_refs)
    for insight_id in section.insight_refs:
        insight = insights_by_id.get(insight_id)
        if insight is None:
            continue
        for finding_id in insight.finding_refs:
            finding = findings_by_id.get(finding_id)
            if finding is not None:
                evidence_refs.update(finding.evidence_refs)
    return tuple(sorted(evidence_refs))
