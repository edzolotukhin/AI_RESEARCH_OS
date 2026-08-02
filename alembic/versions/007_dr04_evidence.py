"""Add durable research evidence for DR-04 evidence extraction."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "007_dr04_evidence"
down_revision = "006_dr03_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_content_checksum", sa.String(length=64), nullable=False),
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
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=False),
        sa.Column("source_locator", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("extraction_method", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("quality_signals", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_evidence_run_deduplication_key",
        ),
    )
    op.create_index("ix_evidence_project_id", "evidence", ["project_id"])
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"])
    op.create_index("ix_evidence_workflow_run_id", "evidence", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_workflow_run_id", table_name="evidence")
    op.drop_index("ix_evidence_source_id", table_name="evidence")
    op.drop_index("ix_evidence_project_id", table_name="evidence")
    op.drop_table("evidence")
