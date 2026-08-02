"""Add DR-07 review quality gate persistence."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "010_dr07_review_quality_gate"
down_revision = "009_dr06_report_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "reports",
        sa.Column("previous_report_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column("approval_status", sa.String(length=32), nullable=False, server_default="draft"),
    )

    op.create_table(
        "review_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("research_design_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.Column("previous_report_id", sa.String(length=36), nullable=True),
        sa.Column("review_attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("quality_dimensions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("issues", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_method", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_review_results_run_deduplication_key",
        ),
    )
    op.create_index("ix_review_results_project_id", "review_results", ["project_id"])
    op.create_index("ix_review_results_workflow_run_id", "review_results", ["workflow_run_id"])
    op.create_index("ix_review_results_report_id", "review_results", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_review_results_report_id", table_name="review_results")
    op.drop_index("ix_review_results_workflow_run_id", table_name="review_results")
    op.drop_index("ix_review_results_project_id", table_name="review_results")
    op.drop_table("review_results")
    op.drop_column("reports", "approval_status")
    op.drop_column("reports", "previous_report_id")
    op.drop_column("reports", "revision_number")
