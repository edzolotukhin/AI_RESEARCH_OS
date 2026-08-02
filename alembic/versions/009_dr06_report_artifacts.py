"""Add durable reports and artifact content metadata for DR-06."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "009_dr06_report_artifacts"
down_revision = "008_dr05_analysis_findings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("research_design_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_method", sa.String(length=64), nullable=False),
        sa.Column("finding_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("insight_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("citation_registry", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_reports_run_deduplication_key",
        ),
    )
    op.create_index("ix_reports_project_id", "reports", ["project_id"])
    op.create_index("ix_reports_workflow_run_id", "reports", ["workflow_run_id"])

    op.add_column(
        "artifacts",
        sa.Column("media_type", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "artifacts",
        sa.Column("filename", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "artifacts",
        sa.Column("content_checksum", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "artifacts",
        sa.Column("deduplication_key", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "artifacts",
        sa.Column("report_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_artifacts_report_id", "artifacts", ["report_id"])
    op.create_unique_constraint(
        "uq_artifacts_run_deduplication_key",
        "artifacts",
        ["run_id", "deduplication_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_artifacts_run_deduplication_key", "artifacts", type_="unique")
    op.drop_index("ix_artifacts_report_id", table_name="artifacts")
    op.drop_column("artifacts", "report_id")
    op.drop_column("artifacts", "deduplication_key")
    op.drop_column("artifacts", "content_checksum")
    op.drop_column("artifacts", "filename")
    op.drop_column("artifacts", "media_type")
    op.drop_index("ix_reports_workflow_run_id", table_name="reports")
    op.drop_index("ix_reports_project_id", table_name="reports")
    op.drop_table("reports")
