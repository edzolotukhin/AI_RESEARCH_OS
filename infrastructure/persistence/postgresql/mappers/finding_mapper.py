from __future__ import annotations

from datetime import datetime

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight

from infrastructure.persistence.postgresql.models.finding_model import FindingModel, InsightModel


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def finding_to_model(finding: Finding, *, version: int) -> FindingModel:
    return FindingModel(
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
        deduplication_key=finding.deduplication_key,
        created_at=_parse_datetime(finding.created_at),
        metadata_json=dict(finding.metadata),
        version=version,
    )


def finding_from_model(model: FindingModel) -> Finding:
    return Finding(
        id=model.id,
        project_id=model.project_id,
        workflow_run_id=model.workflow_run_id,
        research_design_id=model.research_design_id,
        research_question_refs=tuple(
            str(item) for item in (model.research_question_refs or [])
        ),
        information_need_refs=tuple(
            str(item) for item in (model.information_need_refs or [])
        ),
        statement=model.statement,
        rationale=model.rationale,
        evidence_refs=tuple(str(item) for item in (model.evidence_refs or [])),
        finding_type=FindingType(model.finding_type),
        confidence=model.confidence,
        analysis_method=model.analysis_method,
        deduplication_key=model.deduplication_key,
        created_at=model.created_at.isoformat(),
        metadata=dict(model.metadata_json or {}),
        version=model.version,
    )


def insight_to_model(insight: Insight, *, version: int) -> InsightModel:
    return InsightModel(
        id=insight.id,
        project_id=insight.project_id,
        workflow_run_id=insight.workflow_run_id,
        research_design_id=insight.research_design_id,
        research_question_refs=list(insight.research_question_refs),
        statement=insight.statement,
        implication=insight.implication,
        finding_refs=list(insight.finding_refs),
        confidence=insight.confidence,
        deduplication_key=insight.deduplication_key,
        created_at=_parse_datetime(insight.created_at),
        metadata_json=dict(insight.metadata),
        version=version,
    )


def insight_from_model(model: InsightModel) -> Insight:
    return Insight(
        id=model.id,
        project_id=model.project_id,
        workflow_run_id=model.workflow_run_id,
        research_design_id=model.research_design_id,
        research_question_refs=tuple(
            str(item) for item in (model.research_question_refs or [])
        ),
        statement=model.statement,
        implication=model.implication,
        finding_refs=tuple(str(item) for item in (model.finding_refs or [])),
        confidence=model.confidence,
        deduplication_key=model.deduplication_key,
        created_at=model.created_at.isoformat(),
        metadata=dict(model.metadata_json or {}),
        version=model.version,
    )
