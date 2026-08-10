"""PostgreSQL-backed offline replay for persisted live desk-research runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from domain.evidence.evidence import Evidence
from domain.evidence.evidence_type import EvidenceType
from domain.factories.project_factory import ProjectFactory
from domain.factories.task_factory import TaskFactory
from domain.factories.workflow_run_factory import WorkflowRunFactory
from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.project import Project
from domain.research_brief import ResearchBrief
from domain.sources.source import Source
from domain.reviews.review_result import ReviewResult
from domain.task_definition import TaskDefinition
from domain.value_objects.executor_type import ExecutorType
from domain.workflow_template import WorkflowTemplate

from application.ports.review_ports import SemanticReviewInput
from application.report.report_service import ReportService
from application.report.substantive_coverage import (
    compute_rq_coverage_metrics,
    validate_two_dimensional_coverage,
)
from application.review.deterministic_pre_review import run_deterministic_pre_review
from application.review.issue_clustering import deduplicate_and_cluster_review_issues
from application.review.review_service import ReviewService
from application.review.structural_review import compute_verdict, run_structural_review
from infrastructure.persistence.postgresql.repositories.postgresql_artifact_repository import (
    PostgreSQLArtifactRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_evidence_repository import (
    PostgreSQLEvidenceRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_finding_repository import (
    PostgreSQLFindingRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_insight_repository import (
    PostgreSQLInsightRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import (
    PostgreSQLProjectRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import (
    PostgreSQLReportRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_review_repository import (
    PostgreSQLReviewRepository,
)
from infrastructure.persistence.postgresql.repositories.postgresql_source_repository import (
    PostgreSQLSourceRepository,
)
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from infrastructure.report.deterministic_report_engine import DeterministicReportEngine
from infrastructure.review.deterministic_review_engine import (
    build_rq_batch_inputs,
    build_section_inputs,
    candidates_to_issues,
)
from infrastructure.review.llm_review_engine import LlmReviewEngine
from runtime.workflow_context import WorkflowContext

DEFAULT_SOURCE_RUN_ID = "ed6d88a8-dd0e-4aad-b035-31b31bbe433e"


@dataclass
class ReplayMetrics:
    source_run_id: str
    replay_run_id: str
    replay_project_id: str
    source_section_count: int
    replay_section_count: int
    source_issue_count: int
    replay_issue_count: int
    source_major_issue_count: int
    replay_major_issue_count: int
    source_review_verdict: str | None
    replay_review_verdict: str
    semantic_review_calls: int
    rq_coverage: tuple[dict[str, Any], ...] = ()
    coverage_errors: tuple[str, ...] = ()
    contradiction_acknowledged: bool = False
    unsupported_kpi_blocked: bool = True
    sections_within_max: bool = True
    review_calls_within_max: bool = True
    issues_below_original: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_run_id": self.source_run_id,
            "replay_run_id": self.replay_run_id,
            "replay_project_id": self.replay_project_id,
            "source_section_count": self.source_section_count,
            "replay_section_count": self.replay_section_count,
            "source_issue_count": self.source_issue_count,
            "replay_issue_count": self.replay_issue_count,
            "source_major_issue_count": self.source_major_issue_count,
            "replay_major_issue_count": self.replay_major_issue_count,
            "source_review_verdict": self.source_review_verdict,
            "replay_review_verdict": self.replay_review_verdict,
            "semantic_review_calls": self.semantic_review_calls,
            "rq_coverage": list(self.rq_coverage),
            "coverage_errors": list(self.coverage_errors),
            "contradiction_acknowledged": self.contradiction_acknowledged,
            "unsupported_kpi_blocked": self.unsupported_kpi_blocked,
            "sections_within_max": self.sections_within_max,
            "review_calls_within_max": self.review_calls_within_max,
            "issues_below_original": self.issues_below_original,
            "details": self.details,
        }


def _engine(url: str) -> Engine:
    return create_engine(url, future=True)


def _fetch_one(conn, sql: str, **params):
    return conn.execute(text(sql), params).mappings().first()


def _fetch_all(conn, sql: str, **params):
    return conn.execute(text(sql), params).mappings().all()


def _design_from_snapshot(snapshot: dict) -> ResearchDesign:
    design_payload = snapshot.get("research_design_snapshot") or snapshot.get("research_design")
    if design_payload is None:
        raise KeyError("research_design_snapshot missing from template snapshot")
    design = ResearchDesign.from_dict(design_payload)
    assert design is not None
    return design


def _brief_from_snapshot(snapshot: dict) -> ResearchBrief:
    brief_payload = snapshot.get("research_brief_snapshot") or snapshot.get("research_brief")
    if brief_payload is None:
        raise KeyError("research_brief_snapshot missing from template snapshot")
    brief = ResearchBrief.from_dict(brief_payload)
    assert brief is not None
    return brief


def _finding_from_row(row: dict) -> Finding:
    return Finding.from_dict(
        {
            **row,
            "finding_type": row.get("finding_type", FindingType.SYNTHESIS.value),
        },
    )


def _insight_from_row(row: dict) -> Insight:
    return Insight.from_dict(row)


def _evidence_from_row(row: dict) -> Evidence:
    return Evidence.from_dict(
        {
            **row,
            "evidence_type": row.get("evidence_type", EvidenceType.DIRECT_EXCERPT.value),
        },
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    payload = dict(row)
    for key, value in list(payload.items()):
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    if "metadata_json" in payload:
        payload["metadata"] = payload.pop("metadata_json") or {}
    return payload


def load_source_snapshot(
    engine: Engine,
    source_run_id: str,
) -> dict[str, Any]:
    with engine.connect() as conn:
        run = _fetch_one(
            conn,
            "SELECT id, project_id, workflow_template_id, status FROM workflow_runs WHERE id = :run_id",
            run_id=source_run_id,
        )
        if run is None:
            raise LookupError(f"Source run not found: {source_run_id}")
        template = _fetch_one(
            conn,
            "SELECT snapshot_data FROM workflow_templates WHERE id = :id",
            id=run["workflow_template_id"],
        )
        snapshot = (template or {}).get("snapshot_data") or {}
        findings = [
            _row_to_dict(row)
            for row in _fetch_all(
                conn,
                "SELECT * FROM findings WHERE workflow_run_id = :run_id",
                run_id=source_run_id,
            )
        ]
        insights = [
            _row_to_dict(row)
            for row in _fetch_all(
                conn,
                "SELECT * FROM insights WHERE workflow_run_id = :run_id",
                run_id=source_run_id,
            )
        ]
        evidence = [
            _row_to_dict(row)
            for row in _fetch_all(
                conn,
                "SELECT * FROM evidence WHERE workflow_run_id = :run_id",
                run_id=source_run_id,
            )
        ]
        sources = [
            _row_to_dict(row)
            for row in _fetch_all(
                conn,
                """
                SELECT * FROM sources
                WHERE workflow_run_refs::jsonb ? :run_id
                """,
                run_id=source_run_id,
            )
        ]
        report = _fetch_one(
            conn,
            """
            SELECT id, sections, limitations, executive_summary, citation_registry,
                   generation_method, revision_number
            FROM reports
            WHERE workflow_run_id = :run_id
            ORDER BY revision_number DESC
            LIMIT 1
            """,
            run_id=source_run_id,
        )
        review = _fetch_one(
            conn,
            """
            SELECT id, verdict, issues, review_method, review_attempt
            FROM review_results
            WHERE workflow_run_id = :run_id
            ORDER BY review_attempt DESC
            LIMIT 1
            """,
            run_id=source_run_id,
        )
    return {
        "run": dict(run),
        "snapshot": snapshot,
        "findings": findings,
        "insights": insights,
        "evidence": evidence,
        "sources": sources,
        "report": dict(report) if report else None,
        "review": dict(review) if review else None,
    }


def _clone_with_run(
    payload: dict[str, Any],
    *,
    replay_run_id: str,
    replay_project_id: str,
) -> dict[str, Any]:
    cloned = dict(payload)
    cloned["id"] = str(uuid4())
    cloned["project_id"] = replay_project_id
    cloned["workflow_run_id"] = replay_run_id
    if "deduplication_key" in cloned and cloned["deduplication_key"]:
        cloned["deduplication_key"] = f"replay-{uuid4().hex}"[:64]
    return cloned


def seed_replay_run(
    session_factory: DatabaseSessionFactory,
    *,
    source: dict[str, Any],
    replay_run_id: str,
    replay_project_id: str,
) -> WorkflowContext:
    design = _design_from_snapshot(source["snapshot"])
    brief = _brief_from_snapshot(source["snapshot"])
    project = ProjectFactory().create("Offline Replay Project")
    project = Project(
        id=replay_project_id,
        name=project.name,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
    PostgreSQLProjectRepository(session_factory).create(project)

    template = WorkflowTemplate(
        id=f"template-replay-{replay_run_id[:8]}",
        name="Offline Replay",
        task_definitions=[
            TaskDefinition(
                id="task-write-report",
                name="Write Report",
                executor_id="report",
                executor_type=ExecutorType.AGENT,
            ),
            TaskDefinition(
                id="task-review-report",
                name="Review Report",
                executor_id="review",
                executor_type=ExecutorType.AGENT,
            ),
        ],
        research_design_snapshot=design,
        research_brief_snapshot=brief,
    )
    run = WorkflowRunFactory(task_factory=TaskFactory()).create(
        template=template,
        run_id=replay_run_id,
    )
    run.project_id = replay_project_id
    context = WorkflowContext(
        project=project,
        workflow_run=run,
        workflow_template=template,
        current_task=run.tasks[0],
    )

    source_repo = PostgreSQLSourceRepository(session_factory)
    evidence_repo = PostgreSQLEvidenceRepository(session_factory)
    finding_repo = PostgreSQLFindingRepository(session_factory)
    insight_repo = PostgreSQLInsightRepository(session_factory)

    source_id_map: dict[str, str] = {}
    for row in source["sources"]:
        cloned = _clone_with_run(
            row,
            replay_run_id=replay_run_id,
            replay_project_id=replay_project_id,
        )
        old_id = row["id"]
        cloned["workflow_run_refs"] = tuple(
            replay_run_id if ref == source["run"]["id"] else ref
            for ref in (cloned.get("workflow_run_refs") or [])
        )
        source_id_map[old_id] = cloned["id"]
        source_repo.create(Source.from_dict(cloned))

    evidence_id_map: dict[str, str] = {}
    for row in source["evidence"]:
        cloned = _clone_with_run(
            row,
            replay_run_id=replay_run_id,
            replay_project_id=replay_project_id,
        )
        old_id = row["id"]
        if cloned.get("source_id") in source_id_map:
            cloned["source_id"] = source_id_map[cloned["source_id"]]
        evidence_id_map[old_id] = cloned["id"]
        evidence_repo.create(_evidence_from_row(cloned))

    finding_id_map: dict[str, str] = {}
    for row in source["findings"]:
        cloned = _clone_with_run(
            row,
            replay_run_id=replay_run_id,
            replay_project_id=replay_project_id,
        )
        old_id = row["id"]
        cloned["evidence_refs"] = [
            evidence_id_map.get(ref, ref) for ref in (cloned.get("evidence_refs") or [])
        ]
        finding_id_map[old_id] = cloned["id"]
        finding_repo.create(_finding_from_row(cloned))

    for row in source["insights"]:
        cloned = _clone_with_run(
            row,
            replay_run_id=replay_run_id,
            replay_project_id=replay_project_id,
        )
        cloned["finding_refs"] = [
            finding_id_map.get(ref, ref) for ref in (cloned.get("finding_refs") or [])
        ]
        insight_repo.create(_insight_from_row(cloned))

    return context


def _mock_llm_engine(*, max_review_calls: int = 7) -> LlmReviewEngine:
    from unittest.mock import Mock

    from domain.ai.llm_response import LLMResponse

    mock_llm = Mock()
    mock_llm.generate.return_value = LLMResponse(content='{"issues":[]}')
    return LlmReviewEngine(
        llm_client=mock_llm,
        max_review_calls=max_review_calls,
        structured_output_max_attempts=1,
    )


def execute_offline_replay(
    *,
    source_engine: Engine,
    replay_session_factory: DatabaseSessionFactory,
    source_run_id: str = DEFAULT_SOURCE_RUN_ID,
    report_max_sections: int = 12,
    review_max_calls: int = 7,
) -> ReplayMetrics:
    source = load_source_snapshot(source_engine, source_run_id)
    replay_run_id = f"replay-{source_run_id[:8]}-{uuid4().hex[:8]}"
    replay_project_id = str(uuid4())

    context = seed_replay_run(
        replay_session_factory,
        source=source,
        replay_run_id=replay_run_id,
        replay_project_id=replay_project_id,
    )
    design = _design_from_snapshot(source["snapshot"])
    brief = _brief_from_snapshot(source["snapshot"])

    report_service = ReportService(
        report_engine=DeterministicReportEngine(),
        finding_repository=PostgreSQLFindingRepository(replay_session_factory),
        insight_repository=PostgreSQLInsightRepository(replay_session_factory),
        evidence_repository=PostgreSQLEvidenceRepository(replay_session_factory),
        source_repository=PostgreSQLSourceRepository(replay_session_factory),
        report_repository=PostgreSQLReportRepository(replay_session_factory),
        artifact_repository=PostgreSQLArtifactRepository(replay_session_factory),
        max_findings_per_batch=20,
        max_chars_per_batch=12000,
        max_sections=report_max_sections,
    )
    semantic_engine = _mock_llm_engine(max_review_calls=review_max_calls)
    review_service = ReviewService(
        semantic_review_engine=semantic_engine,
        finding_repository=PostgreSQLFindingRepository(replay_session_factory),
        insight_repository=PostgreSQLInsightRepository(replay_session_factory),
        evidence_repository=PostgreSQLEvidenceRepository(replay_session_factory),
        report_repository=PostgreSQLReportRepository(replay_session_factory),
        artifact_repository=PostgreSQLArtifactRepository(replay_session_factory),
        review_repository=PostgreSQLReviewRepository(replay_session_factory),
        report_service=report_service,
        max_revision_attempts=0,
    )

    report_service.write_for_context(context)
    report = report_service._report_repository.list_for_project(
        replay_project_id,
        workflow_run_id=replay_run_id,
    )[-1]
    findings = report_service._finding_repository.list_for_project(
        replay_project_id,
        workflow_run_id=replay_run_id,
    )
    insights = report_service._insight_repository.list_for_project(
        replay_project_id,
        workflow_run_id=replay_run_id,
    )

    section_batch_map = {
        section.id: (section.metadata or {}).get("primary_research_question_id")
        for section in report.sections
    }
    coverage_errors = validate_two_dimensional_coverage(
        report.sections,
        findings=findings,
        insights=insights,
        design=design,
        section_batch_map=section_batch_map,
    )
    rq_coverage = tuple(
        compute_rq_coverage_metrics(
            question=question,
            sections=report.sections,
            findings=findings,
            insights=insights,
            evidence_count=sum(
                len(f.evidence_refs)
                for f in findings
                if question.id in f.research_question_refs
            ),
            section_batch_map=section_batch_map,
        ).__dict__
        for question in design.research_questions
    )

    pre_issues = run_deterministic_pre_review(
        report=report,
        design=design,
        findings=findings,
        insights=insights,
    )
    structural = run_structural_review(
        report=report,
        brief=brief,
        design=design,
        findings=findings,
        artifact=None,
    )
    section_inputs = build_section_inputs(report)
    semantic_input = SemanticReviewInput(
        project_id=replay_project_id,
        workflow_run_id=replay_run_id,
        research_design_id=design.id,
        report=report,
        brief_objectives=brief.objectives,
        research_questions=tuple(q.question for q in design.research_questions),
        section_inputs=section_inputs,
        existing_issues=pre_issues + structural,
    )
    semantic_candidates = semantic_engine.review_report(semantic_input)
    semantic_calls = semantic_engine.llm_call_count
    batches = build_rq_batch_inputs(report, max_batches=review_max_calls).batches

    all_issues = deduplicate_and_cluster_review_issues(
        pre_issues + structural + candidates_to_issues(semantic_candidates),
    )
    verdict = compute_verdict(all_issues)

    source_report = source.get("report") or {}
    source_review = source.get("review") or {}
    source_issues = source_review.get("issues") or []
    source_major = sum(1 for item in source_issues if item.get("severity") == "major")

    from application.report.report_assembly import CONTRADICTION_SECTION_TITLE

    contradiction_ack = any(
        section.title == CONTRADICTION_SECTION_TITLE for section in report.sections
    )
    unsupported_blocked = "[unsupported:" not in " ".join(
        section.content for section in report.sections
    )

    replay_major = sum(1 for item in all_issues if item.severity.value == "major")

    metrics = ReplayMetrics(
        source_run_id=source_run_id,
        replay_run_id=replay_run_id,
        replay_project_id=replay_project_id,
        source_section_count=len(source_report.get("sections") or []),
        replay_section_count=len(report.sections),
        source_issue_count=len(source_issues),
        replay_issue_count=len(all_issues),
        source_major_issue_count=source_major,
        replay_major_issue_count=replay_major,
        source_review_verdict=source_review.get("verdict"),
        replay_review_verdict=verdict.value,
        semantic_review_calls=semantic_calls,
        rq_coverage=rq_coverage,
        coverage_errors=coverage_errors,
        contradiction_acknowledged=contradiction_ack,
        unsupported_kpi_blocked=unsupported_blocked,
        sections_within_max=len(report.sections) <= report_max_sections,
        review_calls_within_max=semantic_calls <= review_max_calls,
        issues_below_original=len(all_issues) < len(source_issues),
        details={
            "batch_count": len(batches),
            "finding_count": len(findings),
            "insight_count": len(insights),
            "evidence_count": len(source["evidence"]),
            "source_count": len(source["sources"]),
        },
    )

    review_service._persist_review(
        ReviewResult(
            id=str(uuid4()),
            project_id=replay_project_id,
            workflow_run_id=replay_run_id,
            research_design_id=design.id,
            report_id=report.id,
            artifact_id=None,
            previous_report_id=None,
            review_attempt=1,
            verdict=verdict,
            quality_dimensions=(),
            issues=all_issues,
            summary=f"offline replay verdict: {verdict.value}",
            review_method="llm-mock",
            created_at=datetime.now(timezone.utc).isoformat(),
            deduplication_key=f"replay-review-{replay_run_id}",
        ),
        workflow_run_id=replay_run_id,
    )

    return metrics


def main() -> None:
    source_url = os.environ.get("DATABASE_URL")
    replay_url = os.environ.get("DATABASE_URL_TEST") or os.environ.get("DATABASE_URL")
    source_run_id = os.environ.get("SOURCE_RUN_ID", DEFAULT_SOURCE_RUN_ID)
    if not source_url or not replay_url:
        raise SystemExit("DATABASE_URL and DATABASE_URL_TEST (or DATABASE_URL) are required")

    source_engine = _engine(source_url)
    replay_engine = _engine(replay_url)
    replay_session_factory = DatabaseSessionFactory(replay_engine)

    metrics = execute_offline_replay(
        source_engine=source_engine,
        replay_session_factory=replay_session_factory,
        source_run_id=source_run_id,
    )
    print(json.dumps(metrics.to_dict(), indent=2))


if __name__ == "__main__":
    main()
