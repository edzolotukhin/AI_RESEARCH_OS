"""Disposable PostgreSQL PRF-05B demonstration. Use only the dedicated demo DB."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import uvicorn
from alembic import command
from alembic.config import Config

from api.app import create_fastapi_app
from application.composition_root import create_application_container
from application.config import ApplicationConfig, ApplicationOverrides
from application.query.project_activity_views import ActivityTimeline
from domain.factories.project_factory import ProjectFactory
from domain.research_brief import ResearchBrief
from domain.reviews.review_verdict import ReviewVerdict
from tests.api.auth_helpers import bootstrap_test_api_key
from tests.fixtures.prf05b_visual_helpers import insert_historical_project
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.integration.postgresql.test_report_concurrency import _sample_report
from tests.integration.postgresql.test_review_concurrency import _sample_review


CANONICAL = "prf05b-canonical-desk"
HISTORICAL = "prf05b-historical-partial"
RESOLVED = "prf05b-resolved-review"
QUANTITATIVE = "prf05b-quantitative"
UNAVAILABLE = "prf05b-unavailable-fixture"
READ_FAILURE = "prf05b-read-failure-fixture"
FOREIGN = "prf05b-foreign-project"


class DemoActivityReader:
    def __init__(self, real_reader):
        self.real_reader = real_reader

    def list_for_project(self, project_id: str, limit: int = 20, cursor=None):
        if project_id == UNAVAILABLE:
            return ActivityTimeline(state="unavailable")
        if project_id == READ_FAILURE:
            raise RuntimeError("synthetic Activity read failure")
        return self.real_reader.list_for_project(project_id, limit=limit, cursor=cursor)


def _planned_project(container, owner: str, project_id: str, method: str, title: str):
    projects = container.project_service
    try:
        project = projects.get_project(project_id)
    except Exception:
        project = projects.create_project(
            title, owner_principal_id=owner, project_id=project_id,
            selected_methods=(method,),
        )
    planner = container.project_planning_service
    if project.current_research_design is None:
        planner.save_brief(project, ResearchBrief(
            title="Демонстраційне дослідження", business_question="Який стан демонстраційного сценарію?",
            objectives=("Показати структуру подій",), language="uk",
        ))
        planner.generate_design(projects.get_project(project_id))
        project = projects.get_project(project_id)
    if project.research_design_status != "APPROVED":
        planner.approve_design(
            project, actor_id=owner,
            expected_design_id=project.current_research_design.id,
        )
    return projects.get_project(project_id)


def _desk_with_reviews(container, owner: str, project_id: str, title: str, *, resolved: bool):
    project = _planned_project(container, owner, project_id, "DESK", title)
    run = container.project_planning_service.activate_desk(project)
    reports = container.report_query_service._report_repository
    reviews = container.review_query_service._review_repository
    report = reports.get_by_deduplication_key(run.id, f"{project_id}-report")
    if report is None:
        report = replace(
            _sample_report(project_id=project.id, run_id=run.id,
                           dedup_key=f"{project_id}-report", title="Синтетична чернетка"),
            research_design_id=project.current_research_design.id,
        )
        reports.create(report)
    attention = reviews.get_by_deduplication_key(run.id, f"{project_id}-attention")
    if attention is None:
        attention = replace(
            _sample_review(project_id=project.id, run_id=run.id, report_id=report.id,
                           dedup_key=f"{project_id}-attention"),
            research_design_id=project.current_research_design.id,
            verdict=ReviewVerdict.REVISE,
            summary="Синтетична перевірка: потрібне доопрацювання.",
        )
        reviews.create(attention)
    if resolved and reviews.get_by_deduplication_key(run.id, f"{project_id}-approved") is None:
        approved = replace(
            _sample_review(project_id=project.id, run_id=run.id, report_id=report.id,
                           dedup_key=f"{project_id}-approved"),
            research_design_id=project.current_research_design.id,
            review_attempt=2, verdict=ReviewVerdict.APPROVE,
            created_at=(datetime.now(UTC) + timedelta(seconds=2)).isoformat(),
            summary="Синтетичний звіт схвалено після попередніх зауважень.",
        )
        reviews.create(approved)


def build_app():
    url = os.environ.get("PRF05B_DEMO_DATABASE_URL", "")
    if "prf05b_demo" not in url.rsplit("/", 1)[-1]:
        raise RuntimeError("PRF-05B demo requires the dedicated prf05b_demo database")
    os.environ["DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    container = create_application_container(
        config=ApplicationConfig(
            persistence_backend="postgresql", database_url=url,
            background_execution_mode="external", deterministic_stage_executors=True,
            search_provider="deterministic", evidence_extractor="deterministic",
            analysis_engine="deterministic", report_engine="deterministic",
            review_engine="deterministic", research_sufficiency_assessor="deterministic",
        ),
        overrides=ApplicationOverrides(llm_client=create_brief_aligned_llm_mock()),
    )
    bootstrap_test_api_key(container)
    owner = container.authentication_service.authenticate_api_key(container._test_api_key_plaintext).principal_id
    _desk_with_reviews(container, owner, CANONICAL, "PRF-05B нова канонічна активність", resolved=False)
    _desk_with_reviews(container, owner, RESOLVED, "PRF-05B зауваження згодом усунуті", resolved=True)
    quant = _planned_project(container, owner, QUANTITATIVE, "QUANTITATIVE", "PRF-05B кількісна активація")
    container.project_planning_service.activate_quantitative(quant, owner_id=owner)
    projects = container.project_service
    try:
        projects.get_project(HISTORICAL)
    except Exception:
        historical = ProjectFactory().create("PRF-05B синтетична неповна історія", project_id=HISTORICAL)
        historical.owner_principal_id = owner
        historical.created_at = "2025-01-01T12:00:00+00:00"
        historical.selected_methods = ("DESK",)
        insert_historical_project(container.activity_reader.sessions, historical)
    for project_id, title, project_owner in (
        (UNAVAILABLE, "Симуляція недоступного файлового режиму", owner),
        (READ_FAILURE, "Симуляція помилки читання активності", owner),
        (FOREIGN, "Недоступний чужий проєкт", "other-principal"),
    ):
        try:
            projects.get_project(project_id)
        except Exception:
            projects.create_project(title, owner_principal_id=project_owner,
                                    project_id=project_id, selected_methods=("DESK",))
    container.activity_reader = DemoActivityReader(container.activity_reader)
    return create_fastapi_app(container=container)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8010)
