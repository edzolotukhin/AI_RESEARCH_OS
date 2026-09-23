"""Bounded Activity read with conservative historical projection."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from application.query.project_activity_views import ActivityEventView, ActivityTimeline
from infrastructure.persistence.postgresql.models.project_activity_model import ProjectActivityModel
from infrastructure.persistence.postgresql.models.project_model import ProjectModel
from infrastructure.persistence.postgresql.models.quantitative_state_model import QuantitativeStateModel
from infrastructure.persistence.postgresql.models.report_model import ReportModel
from infrastructure.persistence.postgresql.models.review_model import ReviewModel
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.project_activity import utc_timestamp


LABELS = {
    "PROJECT_CREATED": "Проєкт створено",
    "DESIGN_APPROVED": "Дизайн дослідження затверджено",
    "DESK_REPORT_DRAFT_CREATED": "Сформовано чернетку звіту",
    "DESK_REVIEW_ATTENTION": "Перевірка звіту виявила зауваження",
}
METHOD_LABELS = {"DESK": "Кабінетне дослідження", "QUANTITATIVE": "Кількісне дослідження"}


class PostgreSQLProjectActivityReader:
    def __init__(self, sessions) -> None:
        self.sessions = sessions

    def list_for_project(self, project_id: str, limit: int = 20, cursor=None) -> ActivityTimeline:
        if cursor is not None:
            raise ValueError("Project Activity pagination is not enabled")
        if limit < 1:
            raise ValueError("Project Activity limit must be positive")
        limit = min(limit, 50)
        with self.sessions.session() as session:
            project = session.get(ProjectModel, project_id)
            if project is None:
                raise ValueError("Project not found")
            canonical = session.scalars(
                select(ProjectActivityModel)
                .where(ProjectActivityModel.project_id == project_id)
                .order_by(ProjectActivityModel.occurred_at.desc(), ProjectActivityModel.event_id.desc())
                .limit(50)
            ).all()
            creation_event = session.scalar(
                select(ProjectActivityModel).where(
                    ProjectActivityModel.project_id == project_id,
                    ProjectActivityModel.event_type == "PROJECT_CREATED",
                    ProjectActivityModel.semantic_key == "project-created",
                ).limit(1)
            )
            complete = bool(creation_event and self._valid_canonical(session, creation_event))
            # New projects always have PROJECT_CREATED. Old projects retain a gap.
            events: dict[str, tuple[datetime, str, str, str | None]] = {}

            def add(key: str, event_type: str, when, method: str | None = None) -> None:
                timestamp = utc_timestamp(when)
                if timestamp is None:
                    return
                identity = str(uuid5(NAMESPACE_URL, f"project-activity:{project_id}:{key}"))
                events.setdefault(key, (timestamp, identity, event_type, method))

            for row in canonical:
                if not self._valid_canonical(session, row):
                    continue
                add(row.semantic_key, row.event_type, row.occurred_at, row.method)

            # Project creation is the only historical event proven by the project row itself.
            add("project-created", "PROJECT_CREATED", project.created_at)
            design = project.planning_design or {}
            if project.planning_design_status == "APPROVED" and isinstance(design, dict) and design.get("id"):
                add(f"design-approved:{design['id']}", "DESIGN_APPROVED", project.planning_design_approved_at)

            reports = session.execute(
                select(ReportModel, WorkflowRunModel)
                .join(WorkflowRunModel, ReportModel.workflow_run_id == WorkflowRunModel.id)
                .where(ReportModel.project_id == project_id, WorkflowRunModel.project_id == project_id)
                .order_by(ReportModel.created_at.desc(), ReportModel.id.desc()).limit(50)
            ).all()
            for report, run in reports:
                add(f"desk-report:{report.id}", "DESK_REPORT_DRAFT_CREATED", report.created_at, "DESK")

            reviews = session.execute(
                select(ReviewModel, ReportModel, WorkflowRunModel)
                .join(ReportModel, ReviewModel.report_id == ReportModel.id)
                .join(WorkflowRunModel, ReviewModel.workflow_run_id == WorkflowRunModel.id)
                .where(
                    ReviewModel.project_id == project_id,
                    ReportModel.project_id == project_id,
                    WorkflowRunModel.project_id == project_id,
                    ReportModel.workflow_run_id == ReviewModel.workflow_run_id,
                    ReviewModel.verdict.in_(("revise", "reject")),
                )
                .order_by(ReviewModel.created_at.desc(), ReviewModel.id.desc()).limit(50)
            ).all()
            for review, report, run in reviews:
                add(f"desk-review:{review.id}", "DESK_REVIEW_ATTENTION", review.created_at, "DESK")

            ordered = sorted(events.values(), key=lambda row: (row[0], row[1]), reverse=True)[:limit]
            return ActivityTimeline(
                events=tuple(ActivityEventView(
                    label=(METHOD_LABELS[method] + " активовано" if event_type == "METHOD_ACTIVATED" and method
                           else LABELS[event_type]),
                    date_time=when.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC"),
                    method=(METHOD_LABELS[method] if method else None),
                ) for when, identity, event_type, method in ordered),
                history_incomplete=not complete,
            )

    @staticmethod
    def _valid_canonical(session, row: ProjectActivityModel) -> bool:
        if row.event_type == "PROJECT_CREATED":
            return row.source_kind == "project" and row.source_id == row.project_id
        if row.event_type == "DESIGN_APPROVED":
            return row.source_kind == "design" and bool(row.source_id)
        if row.run_id is None:
            return False
        run = session.get(WorkflowRunModel, row.run_id)
        if run is None or run.project_id != row.project_id:
            return False
        if row.event_type == "METHOD_ACTIVATED":
            if row.method == "DESK":
                return row.source_kind == "run" and row.source_id == run.id
            if row.method == "QUANTITATIVE" and row.source_kind == "study":
                return bool(session.scalar(select(QuantitativeStateModel.record_id).where(
                    QuantitativeStateModel.project_id == row.project_id,
                    QuantitativeStateModel.run_id == run.id,
                    QuantitativeStateModel.record_type.like("%.QuantitativeStudyProjection"),
                    QuantitativeStateModel.payload["fields"]["study_id"].as_string() == row.source_id,
                ).limit(1)))
            return False
        if row.event_type == "DESK_REPORT_DRAFT_CREATED":
            report = session.get(ReportModel, row.source_id)
            return bool(row.source_kind == "report" and report and report.project_id == row.project_id
                        and report.workflow_run_id == run.id)
        if row.event_type == "DESK_REVIEW_ATTENTION":
            review = session.get(ReviewModel, row.source_id)
            report = session.get(ReportModel, review.report_id) if review else None
            return bool(row.source_kind == "review" and review and report
                        and review.project_id == row.project_id and review.workflow_run_id == run.id
                        and report.project_id == row.project_id and report.workflow_run_id == run.id
                        and review.verdict in ("revise", "reject"))
        return False
