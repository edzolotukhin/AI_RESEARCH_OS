from __future__ import annotations

from domain.findings.finding import Finding
from domain.findings.insight import Insight

from api.schemas.findings import FindingResponse, InsightResponse


def finding_to_response(finding: Finding) -> FindingResponse:
    return FindingResponse(
        id=finding.id,
        project_id=finding.project_id,
        workflow_run_id=finding.workflow_run_id,
        research_design_id=finding.research_design_id,
        research_question_refs=list(finding.research_question_refs),
        information_need_refs=list(finding.information_need_refs),
        statement=finding.statement,
        rationale=finding.rationale,
        evidence_refs=list(finding.evidence_refs),
        finding_type=finding.finding_type.value,
        confidence=finding.confidence,
        analysis_method=finding.analysis_method,
        created_at=finding.created_at,
        metadata=dict(finding.metadata),
    )


def insight_to_response(insight: Insight) -> InsightResponse:
    return InsightResponse(
        id=insight.id,
        project_id=insight.project_id,
        workflow_run_id=insight.workflow_run_id,
        research_design_id=insight.research_design_id,
        research_question_refs=list(insight.research_question_refs),
        statement=insight.statement,
        implication=insight.implication,
        finding_refs=list(insight.finding_refs),
        confidence=insight.confidence,
        created_at=insight.created_at,
        metadata=dict(insight.metadata),
    )
