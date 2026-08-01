"""Add research_submissions table for external idempotent submission."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003_pf07_research_submissions"
down_revision = "002_pf06_worker_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_submissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=256), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_research_submissions_project_key",
        ),
        sa.UniqueConstraint("run_id", name="uq_research_submissions_run_id"),
    )
    op.create_index(
        "ix_research_submissions_project_id",
        "research_submissions",
        ["project_id"],
    )
    op.create_index(
        "ix_research_submissions_run_id",
        "research_submissions",
        ["run_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_research_submissions_run_id", table_name="research_submissions")
    op.drop_index("ix_research_submissions_project_id", table_name="research_submissions")
    op.drop_table("research_submissions")
