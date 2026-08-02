"""Add durable findings and insights for DR-05 analysis."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "008_dr05_analysis_findings"
down_revision = "007_dr04_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("research_design_id", sa.String(length=36), nullable=False),
        sa.Column(
            "research_question_refs",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "information_need_refs",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("analysis_method", sa.String(length=64), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_findings_run_deduplication_key",
        ),
    )
    op.create_index("ix_findings_project_id", "findings", ["project_id"])
    op.create_index("ix_findings_workflow_run_id", "findings", ["workflow_run_id"])

    op.create_table(
        "insights",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("research_design_id", sa.String(length=36), nullable=False),
        sa.Column(
            "research_question_refs",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("implication", sa.Text(), nullable=False),
        sa.Column("finding_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_insights_run_deduplication_key",
        ),
    )
    op.create_index("ix_insights_project_id", "insights", ["project_id"])
    op.create_index("ix_insights_workflow_run_id", "insights", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_index("ix_insights_workflow_run_id", table_name="insights")
    op.drop_index("ix_insights_project_id", table_name="insights")
    op.drop_table("insights")
    op.drop_index("ix_findings_workflow_run_id", table_name="findings")
    op.drop_index("ix_findings_project_id", table_name="findings")
    op.drop_table("findings")
