"""Disposable in-memory PF-03 visual acceptance server."""
from __future__ import annotations

from datetime import datetime, timezone

import uvicorn

from api.app import create_fastapi_app
from api.ui.principal import resolve_ui_principal
from application.persistence.records import ArtifactRecord
from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.findings.insight import Insight
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.research_brief import ResearchBrief
from domain.reviews.quality_dimension import QualityDimension, QualityDimensionName, QualityDimensionStatus
from domain.reviews.review_issue import ReviewIssue, ReviewIssueSeverity, ReviewIssueType
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.sources.source import Source
from tests.api.helpers import build_test_container

RUNNING_RUN_ID = "pf03-running-desk"
COMPLETED_RUN_ID = "pf03-completed-desk"
ATTENTION_RUN_ID = "pf03-attention-desk"


def _brief(title: str) -> ResearchBrief:
    return ResearchBrief(
        title=title,
        business_question="Які фактори визначають привабливість ринку теплових насосів в Україні?",
        objectives=("Оцінити попит і драйвери ринку", "Визначити бар’єри входу", "Порівняти основні сегменти"),
        geography=("Україна",), market="Теплові насоси", timeframe="2024–2026",
        language="uk", context="Рішення щодо виходу постачальника на ринок.",
        deliverables=("Структурований звіт",),
    )


def _create_run(container, owner: str, *, project_id: str, run_id: str, title: str):
    project = container.agency.create_project(title, owner_principal_id=owner, project_id=project_id)
    project.research_brief = _brief(title)
    context = container.agency.start_research(project, run_id=run_id)
    return project, context.workflow_run


def _start(run):
    run.ready(); run.start()


def _complete(run):
    _start(run)
    for task in run.tasks:
        task.ready(); task.start(); task.complete()
    run.complete()


def _seed_materials(container, project, run, *, count: int = 6, downstream: bool = True):
    now = datetime.now(timezone.utc).isoformat()
    source_repo = container.source_service._source_repository
    evidence_repo = container.evidence_service._evidence_repository
    finding_repo = container.finding_service._finding_repository
    insight_repo = container.insight_service._insight_repository
    sources=[]; evidence=[]; findings=[]
    for index in range(1, count + 1):
        source=Source(
            id=f"{run.id}-source-{index}", project_id=project.id,
            url=f"https://example.com/market-source-{index}", canonical_url=f"https://example.com/market-source-{index}",
            title=f"Огляд ринку теплових насосів — джерело {index}", publisher="Галузеве видання",
            retrieved_at=now, published_at="2026-01-15T00:00:00+00:00", language="uk",
            workflow_run_refs=(run.id,), research_design_refs=("fixture-design",),
        ); source_repo.create(source); sources.append(source)
        item=Evidence(
            id=f"{run.id}-evidence-{index}", project_id=project.id, source_id=source.id,
            source_content_checksum=f"checksum-{index}", workflow_run_id=run.id,
            research_design_id="fixture-design", statement=f"Попит у сегменті {index} підтримується оновленням житлового фонду.",
            source_excerpt=f"Джерело {index} фіксує стабільне зростання інтересу та інвестицій у енергоефективність.",
            created_at=now, deduplication_key=f"{run.id}-evidence-{index}",
        ); evidence_repo.create(item); evidence.append(item)
        if not downstream:
            continue
        finding=Finding(
            id=f"{run.id}-finding-{index}", project_id=project.id, workflow_run_id=run.id,
            research_design_id="fixture-design", statement=f"Сегмент {index} має підтверджений потенціал зростання.",
            rationale="Висновок узгоджується з опрацьованим галузевим джерелом.", evidence_refs=(item.id,),
            created_at=now, deduplication_key=f"{run.id}-finding-{index}",
        ); finding_repo.create(finding); findings.append(finding)
    for index, finding in enumerate(findings[:3], 1):
        insight_repo.create(Insight(
            id=f"{run.id}-insight-{index}", project_id=project.id, workflow_run_id=run.id,
            research_design_id="fixture-design", statement=f"Інсайт {index}: пріоритет має локалізована ринкова пропозиція.",
            implication="Вихід на ринок варто поєднати з локальними сервісними партнерами.",
            finding_refs=(finding.id,), created_at=now, deduplication_key=f"{run.id}-insight-{index}",
        ))
    return sources,evidence,findings,now


def _seed_report(container, project, run, findings, now, *, verdict: ReviewVerdict):
    report=Report(
        id=f"{run.id}-report", project_id=project.id, workflow_run_id=run.id,
        research_design_id="fixture-design", title="Ринок теплових насосів в Україні",
        language="uk", executive_summary="Ринок має потенціал зростання, але потребує локальної сервісної моделі та уважної сегментації.",
        sections=(
            ReportSection("section-1","Ринкова ситуація","Попит підтримують енергоефективність, оновлення житла та доступність технологій."),
            ReportSection("section-2","Бар’єри входу","Ключові бар’єри — початкова вартість, сервісна інфраструктура та довіра покупців."),
        ), limitations=("Використано лише вторинні джерела.",), created_at=now,
        generation_method="fixture-replay", finding_refs=tuple(item.id for item in findings),
        insight_refs=tuple(f"{run.id}-insight-{i}" for i in range(1,4)),
        evidence_refs=tuple(ref for item in findings for ref in item.evidence_refs), citation_registry={},
        deduplication_key=f"{run.id}-report", approval_status="approved" if verdict is ReviewVerdict.APPROVE else "draft",
    ); container.report_query_service._report_repository.create(report)
    issue=() if verdict is ReviewVerdict.APPROVE else (ReviewIssue(
        id=f"{run.id}-issue", issue_type=ReviewIssueType.COVERAGE_GAP,
        severity=ReviewIssueSeverity.MAJOR, message="Потрібне ширше охоплення офіційних статистичних джерел.",
    ),)
    review=ReviewResult(
        id=f"{run.id}-review", project_id=project.id, workflow_run_id=run.id,
        research_design_id="fixture-design", report_id=report.id, review_attempt=1, verdict=verdict,
        quality_dimensions=(QualityDimension(QualityDimensionName.EVIDENCE_SUPPORT,QualityDimensionStatus.PASS if verdict is ReviewVerdict.APPROVE else QualityDimensionStatus.FAIL,"Перевірено"),),
        issues=issue, summary="Звіт узгоджений із доказами." if verdict is ReviewVerdict.APPROVE else "Звіт потребує додаткового покриття.",
        review_method="fixture-replay", created_at=now, deduplication_key=f"{run.id}-review",
        artifact_id=f"{run.id}-artifact" if verdict is ReviewVerdict.APPROVE else None,
    ); container.review_query_service._review_repository.create(review)
    if verdict is ReviewVerdict.APPROVE:
        container.artifact_service.save_artifact(ArtifactRecord(
            id=f"{run.id}-artifact", project_id=project.id, artifact_type="report", title=report.title,
            content="", run_id=run.id, status="approved", report_id=report.id,
        ))


def build_app():
    container=build_test_container(background_execution_mode="embedded")
    owner=resolve_ui_principal(container).principal_id
    completed_project,completed=_create_run(container,owner,project_id="pf03-completed-project",run_id=COMPLETED_RUN_ID,title="PF-03 завершене дослідження")
    _,_,completed_findings,now=_seed_materials(container,completed_project,completed)
    _seed_report(container,completed_project,completed,completed_findings,now,verdict=ReviewVerdict.APPROVE)
    _complete(completed); container.workflow_service.save_workflow_run(completed)

    running_project,running=_create_run(container,owner,project_id="pf03-running-project",run_id=RUNNING_RUN_ID,title="PF-03 дослідження у виконанні")
    _seed_materials(container,running_project,running,count=2,downstream=False); _start(running); running.tasks[0].ready(); running.tasks[0].start(); container.workflow_service.save_workflow_run(running)

    attention_project,attention=_create_run(container,owner,project_id="pf03-attention-project",run_id=ATTENTION_RUN_ID,title="PF-03 дослідження, що потребує уваги")
    _,_,attention_findings,attention_now=_seed_materials(container,attention_project,attention,count=4)
    _seed_report(container,attention_project,attention,attention_findings,attention_now,verdict=ReviewVerdict.REJECT)
    _complete(attention); container.workflow_service.save_workflow_run(attention)
    return create_fastapi_app(container=container)


app=build_app()

if __name__ == "__main__":
    uvicorn.run(app,host="127.0.0.1",port=8008)
