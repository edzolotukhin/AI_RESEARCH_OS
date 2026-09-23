"""PRF-05B persistence, history and atomicity on a disposable PostgreSQL DB."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from domain.factories.project_factory import ProjectFactory
from domain.planning.research_design import ResearchDesign, ResearchQuestion
from domain.reviews.review_verdict import ReviewVerdict
from domain.research_brief import ResearchBrief
from domain.workflow_run import WorkflowRun
from domain.workflow_template import WorkflowTemplate
from application.composition_root import create_application_container
from infrastructure.persistence.postgresql.mappers.project_mapper import project_to_model
from infrastructure.persistence.postgresql.mappers.report_mapper import report_to_model
from infrastructure.persistence.postgresql.mappers.review_mapper import review_to_model
from infrastructure.persistence.postgresql.models.project_activity_model import ProjectActivityModel
from infrastructure.persistence.postgresql.models.project_model import ProjectModel
from sqlalchemy.orm import Session
from infrastructure.persistence.postgresql.repositories.postgresql_project_repository import PostgreSQLProjectRepository
from infrastructure.persistence.postgresql.repositories.postgresql_report_repository import PostgreSQLReportRepository
from infrastructure.persistence.postgresql.repositories.postgresql_review_repository import PostgreSQLReviewRepository
from infrastructure.persistence.postgresql.repositories.postgresql_workflow_run_repository import PostgreSQLWorkflowRunRepository
from infrastructure.persistence.postgresql.project_activity import record_activity
from infrastructure.persistence.postgresql.project_activity_reader import PostgreSQLProjectActivityReader
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.integration.postgresql.test_report_concurrency import _sample_report
from tests.integration.postgresql.test_review_concurrency import _sample_review


@unittest.skipUnless(integration_tests_enabled(), "Disposable PostgreSQL database required")
class ProjectActivityPersistenceTests(PostgreSQLIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.projects = PostgreSQLProjectRepository(self.session_factory)
        self.reader = PostgreSQLProjectActivityReader(self.session_factory)

    def _project(self):
        project = ProjectFactory().create("Activity test")
        project.owner_principal_id = "owner"
        self.projects.create(project)
        return project

    def _types(self, project_id):
        with self.session_factory.session() as session:
            return session.scalars(select(ProjectActivityModel.event_type).where(
                ProjectActivityModel.project_id == project_id,
            )).all()

    def test_project_created_once_and_rollback_on_activity_failure(self):
        project = self._project()
        self.assertEqual(self._types(project.id), ["PROJECT_CREATED"])
        timeline = self.reader.list_for_project(project.id)
        self.assertFalse(timeline.history_incomplete)
        self.assertEqual(len(timeline.events), 1)  # canonical + historical projection deduplicate
        second = ProjectFactory().create("Fail activity")
        with patch("infrastructure.persistence.postgresql.repositories.postgresql_project_repository.record_activity", side_effect=RuntimeError("activity failed")):
            with self.assertRaisesRegex(RuntimeError, "activity failed"):
                self.projects.create(second)
        self.assertIsNone(self.projects.get_by_id(second.id))

    def test_design_revision_reapproval_is_distinct_but_repeat_is_not(self):
        project = self._project()
        project.current_research_design = ResearchDesign("design-a", (ResearchQuestion("rq", "Q?"),))
        project.research_design_status = "APPROVED"
        project.research_design_approved_at = datetime.now(UTC).isoformat()
        self.projects.save(project)
        self.projects.save(project)
        self.assertEqual(self._types(project.id).count("DESIGN_APPROVED"), 1)
        project.current_research_design = ResearchDesign("design-b", (ResearchQuestion("rq", "Q?"),))
        self.projects.save(project)
        self.assertEqual(self._types(project.id).count("DESIGN_APPROVED"), 2)

    def test_design_event_failure_rolls_back_approval(self):
        project = self._project()
        project.current_research_design = ResearchDesign("design-fail", (ResearchQuestion("rq", "Q?"),))
        project.research_design_status = "APPROVED"
        project.research_design_approved_at = datetime.now(UTC).isoformat()
        with patch("infrastructure.persistence.postgresql.repositories.postgresql_project_repository.record_activity", side_effect=RuntimeError("activity failed")):
            with self.assertRaisesRegex(RuntimeError, "activity failed"):
                self.projects.save(project)
        loaded = self.projects.get_by_id(project.id)
        self.assertIsNone(loaded.current_research_design)
        self.assertEqual(self._types(project.id), ["PROJECT_CREATED"])

    def test_design_commit_failure_rolls_back_approval_and_event(self):
        project = self._project()
        project.current_research_design = ResearchDesign("design-commit", (ResearchQuestion("rq", "Q?"),))
        project.research_design_status = "APPROVED"
        project.research_design_approved_at = datetime.now(UTC).isoformat()
        with patch.object(Session, "commit", side_effect=RuntimeError("commit failure")):
            with self.assertRaisesRegex(RuntimeError, "commit failure"):
                self.projects.save(project)
        self.assertIsNone(self.projects.get_by_id(project.id).current_research_design)
        self.assertEqual(self._types(project.id), ["PROJECT_CREATED"])

    def test_desk_report_and_attention_share_authoritative_commit(self):
        project = self._project()
        runs = PostgreSQLWorkflowRunRepository(self.session_factory)
        runs.create(WorkflowRun(id="activity-run", project_id=project.id), project_id=project.id)
        report = _sample_report(project_id=project.id, run_id="activity-run", dedup_key="report-key", title="Draft")
        reports = PostgreSQLReportRepository(self.session_factory)
        reports.create(report)
        self.assertIn("DESK_REPORT_DRAFT_CREATED", self._types(project.id))
        review = _sample_review(project_id=project.id, run_id="activity-run", report_id=report.id, dedup_key="review-key")
        review = replace(review, verdict=ReviewVerdict.REVISE)
        reviews = PostgreSQLReviewRepository(self.session_factory)
        reviews.create(review)
        self.assertIn("DESK_REVIEW_ATTENTION", self._types(project.id))
        labels = [item.label for item in self.reader.list_for_project(project.id).events]
        self.assertIn("Перевірка звіту виявила зауваження", labels)
        failed = _sample_report(project_id=project.id, run_id="activity-run", dedup_key="other-key", title="Failure")
        with patch("infrastructure.persistence.postgresql.repositories.postgresql_report_repository.record_activity", side_effect=RuntimeError("activity failed")):
            with self.assertRaisesRegex(RuntimeError, "activity failed"):
                reports.create(failed)
        self.assertIsNone(reports.get_by_id(failed.id))
        failed_review = replace(review, id="review-failure", deduplication_key="other-review-key", verdict=ReviewVerdict.REJECT)
        with patch("infrastructure.persistence.postgresql.repositories.postgresql_review_repository.record_activity", side_effect=RuntimeError("activity failed")):
            with self.assertRaisesRegex(RuntimeError, "activity failed"):
                reviews.create(failed_review)
        self.assertIsNone(reviews.get_by_id(failed_review.id))
        self.assertEqual(self._types(project.id).count("DESK_REPORT_DRAFT_CREATED"), 1)
        self.assertEqual(self._types(project.id).count("DESK_REVIEW_ATTENTION"), 1)

    def test_commit_failure_rolls_back_authoritative_and_activity_rows(self):
        project = ProjectFactory().create("Commit failure")
        with patch.object(Session, "commit", side_effect=RuntimeError("commit failure")):
            with self.assertRaisesRegex(RuntimeError, "commit failure"):
                self.projects.create(project)
        self.assertIsNone(self.projects.get_by_id(project.id))

        project = self._project()
        runs = PostgreSQLWorkflowRunRepository(self.session_factory)
        runs.create(WorkflowRun(id="commit-run", project_id=project.id), project_id=project.id)
        report = _sample_report(project_id=project.id, run_id="commit-run", dedup_key="commit-report", title="Demo")
        reports = PostgreSQLReportRepository(self.session_factory)
        with patch.object(Session, "commit", side_effect=RuntimeError("commit failure")):
            with self.assertRaisesRegex(RuntimeError, "commit failure"):
                reports.create(report)
        self.assertIsNone(reports.get_by_id(report.id))
        self.assertEqual(self._types(project.id), ["PROJECT_CREATED"])

        reports.create(report)
        review = replace(_sample_review(project_id=project.id, run_id="commit-run", report_id=report.id,
                                        dedup_key="commit-review"), verdict=ReviewVerdict.REJECT)
        reviews = PostgreSQLReviewRepository(self.session_factory)
        with patch.object(Session, "commit", side_effect=RuntimeError("commit failure")):
            with self.assertRaisesRegex(RuntimeError, "commit failure"):
                reviews.create(review)
        self.assertIsNone(reviews.get_by_id(review.id))
        self.assertEqual(self._types(project.id).count("DESK_REVIEW_ATTENTION"), 0)

    def test_desk_activation_only_for_real_design_template(self):
        project = self._project()
        from infrastructure.persistence.postgresql.repositories.postgresql_workflow_template_repository import PostgreSQLWorkflowTemplateRepository
        templates = PostgreSQLWorkflowTemplateRepository(self.session_factory)
        template = WorkflowTemplate(
            id="desk-template", name="Desk",
            research_brief_snapshot=ResearchBrief(title="Desk", business_question="Question?"),
            research_design_snapshot=ResearchDesign("desk-design", (ResearchQuestion("rq", "Question?"),)),
        )
        templates.save_snapshot(template, project_id=project.id)
        runs = PostgreSQLWorkflowRunRepository(self.session_factory)
        runs.create(WorkflowRun(id="desk-run", project_id=project.id, workflow_template_id=template.id), project_id=project.id)
        self.assertEqual(self._types(project.id).count("METHOD_ACTIVATED"), 1)
        labels = [item.label for item in self.reader.list_for_project(project.id).events]
        self.assertIn("Кабінетне дослідження активовано", labels)

    def test_semantic_uniqueness_rejects_duplicate(self):
        project = self._project()
        with self.assertRaises(IntegrityError):
            with self.session_factory.session() as session:
                record_activity(session, project_id=project.id, semantic_key="project-created",
                                event_type="PROJECT_CREATED", source_kind="project", source_id=project.id)
        self.assertEqual(self._types(project.id), ["PROJECT_CREATED"])

    def test_schema_constraints_and_project_order_index(self):
        schema = inspect(self.engine)
        checks = {item["name"] for item in schema.get_check_constraints("project_activity")}
        self.assertIn("ck_project_activity_type", checks)
        self.assertIn("ck_project_activity_source_kind", checks)
        self.assertIn("ck_project_activity_attention_verdict", checks)
        indexes = {item["name"] for item in schema.get_indexes("project_activity")}
        self.assertIn("ix_project_activity_project_order", indexes)
        uniques = {item["name"] for item in schema.get_unique_constraints("project_activity")}
        self.assertIn("uq_project_activity_semantic", uniques)

    def test_historical_project_projects_only_provable_rows_and_marks_gap(self):
        project = ProjectFactory().create("Before Activity")
        project.created_at = "2026-01-01T12:00:00+00:00"
        with self.session_factory.session() as session:
            session.add(project_to_model(project, version=0))
        timeline = self.reader.list_for_project(project.id)
        self.assertTrue(timeline.history_incomplete)
        self.assertEqual([item.label for item in timeline.events], ["Проєкт створено"])
        self.assertEqual(timeline.message, "Історія за попередній період недоступна")
        with self.session_factory.session() as session:
            stored = session.get(ProjectModel, project.id)
            stored.created_at = "invalid"
        timeline = self.reader.list_for_project(project.id)
        self.assertEqual(timeline.events, ())
        self.assertTrue(timeline.history_incomplete)

    def test_historical_current_approval_requires_revision_and_valid_time(self):
        project = ProjectFactory().create("Historical approval")
        project.current_research_design = ResearchDesign("historical-design", (ResearchQuestion("rq", "Q?"),))
        project.research_design_status = "APPROVED"
        project.research_design_approved_at = "2025-02-01T12:00:00+00:00"
        with self.session_factory.session() as session:
            session.add(project_to_model(project, version=0))
        labels = [item.label for item in self.reader.list_for_project(project.id).events]
        self.assertIn("Дизайн дослідження затверджено", labels)
        with self.session_factory.session() as session:
            stored = session.get(ProjectModel, project.id)
            stored.planning_design_approved_at = "not-a-date"
        labels = [item.label for item in self.reader.list_for_project(project.id).events]
        self.assertNotIn("Дизайн дослідження затверджено", labels)

    def test_identical_timestamps_use_stable_identity_tiebreaker(self):
        project = self._project()
        runs = PostgreSQLWorkflowRunRepository(self.session_factory)
        runs.create(WorkflowRun(id="tie-run", project_id=project.id), project_id=project.id)
        report = _sample_report(project_id=project.id, run_id="tie-run", dedup_key="tie-report", title="Draft")
        PostgreSQLReportRepository(self.session_factory).create(report)
        review = replace(_sample_review(project_id=project.id, run_id="tie-run", report_id=report.id,
                                        dedup_key="tie-review"), verdict=ReviewVerdict.REVISE,
                         created_at=report.created_at)
        PostgreSQLReviewRepository(self.session_factory).create(review)
        timestamp = datetime.fromisoformat(report.created_at)
        with self.session_factory.session() as session:
            rows = session.scalars(select(ProjectActivityModel).where(
                ProjectActivityModel.project_id == project.id,
                ProjectActivityModel.occurred_at == timestamp,
            ).order_by(ProjectActivityModel.event_id.desc())).all()
        expected = [{"DESK_REPORT_DRAFT_CREATED": "Сформовано чернетку звіту",
                     "DESK_REVIEW_ATTENTION": "Перевірка звіту виявила зауваження"}[row.event_type] for row in rows]
        actual = [event.label for event in self.reader.list_for_project(project.id).events if event.label in expected]
        self.assertEqual(actual, expected)

    def test_historical_report_revise_reject_and_later_approval(self):
        project = ProjectFactory().create("Historical reviews")
        project.created_at = "2025-01-01T12:00:00+00:00"
        with self.session_factory.session() as session:
            session.add(project_to_model(project, version=0))
        runs = PostgreSQLWorkflowRunRepository(self.session_factory)
        runs.create(WorkflowRun(id="historical-run", project_id=project.id), project_id=project.id)
        report = _sample_report(project_id=project.id, run_id="historical-run", dedup_key="historical-report", title="Old draft")
        reviews = [
            replace(_sample_review(project_id=project.id, run_id="historical-run", report_id=report.id,
                                   dedup_key=f"old-review-{attempt}"),
                    review_attempt=attempt, verdict=verdict,
                    created_at=f"2025-01-0{attempt}T12:00:00+00:00")
            for attempt, verdict in enumerate((ReviewVerdict.REVISE, ReviewVerdict.REJECT, ReviewVerdict.APPROVE), 1)
        ]
        with self.session_factory.session() as session:
            session.add(report_to_model(report, version=1))
            session.flush()
            for review in reviews:
                session.add(review_to_model(review, version=1))
        timeline = self.reader.list_for_project(project.id)
        labels = [item.label for item in timeline.events]
        self.assertEqual(labels.count("Перевірка звіту виявила зауваження"), 2)
        self.assertEqual(labels.count("Сформовано чернетку звіту"), 1)
        self.assertTrue(timeline.history_incomplete)
        self.assertEqual(timeline.message, "Історія за попередній період недоступна")

    def test_bounded_order_and_cross_project_source_rejection(self):
        project = self._project()
        foreign = self._project()
        with self.session_factory.session() as session:
            session.add(ProjectActivityModel(
                event_id="11111111-1111-1111-1111-111111111111", project_id=project.id,
                semantic_key="foreign-run", event_type="METHOD_ACTIVATED",
                occurred_at=datetime.now(UTC), method="DESK", run_id="foreign-run",
                source_kind="run", source_id="foreign-run",
            ))
            session.add(ProjectActivityModel(
                event_id="22222222-2222-2222-2222-222222222222", project_id=foreign.id,
                semantic_key="foreign-only", event_type="DESIGN_APPROVED",
                occurred_at=datetime.now(UTC), source_kind="design", source_id="foreign-design",
            ))
        timeline = self.reader.list_for_project(project.id, limit=1)
        self.assertEqual(len(timeline.events), 1)
        self.assertNotIn("Дизайн дослідження затверджено", [item.label for item in timeline.events])

    def test_quantitative_activation_is_canonical_and_idempotent(self):
        container = create_application_container(config=postgresql_application_config())
        self.addCleanup(container.shutdown)
        project = container.project_service.create_project(
            "Quantitative activity", owner_principal_id="owner", selected_methods=("QUANTITATIVE",),
        )
        quant = container.quantitative_ui_service
        study = quant.create_quantitative_study_for_project(
            project_id=project.id, owner_id="owner", title="Demo", description="",
            submission_key="activity-key",
        )
        replay = quant.create_quantitative_study_for_project(
            project_id=project.id, owner_id="owner", title="Demo", description="",
            submission_key="activity-key",
        )
        self.assertEqual(study.study_id, replay.study_id)
        self.assertEqual(self._types(project.id).count("METHOD_ACTIVATED"), 1)
        self.assertIn("Кількісне дослідження активовано", [item.label for item in self.reader.list_for_project(project.id).events])
