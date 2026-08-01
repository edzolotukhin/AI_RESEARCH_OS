"""Add worker lease columns to workflow_runs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "002_pf06_worker_leases"
down_revision = "001_pf03_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_workflow_runs_runnable_lease",
        "workflow_runs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_runnable_lease", table_name="workflow_runs")
    op.drop_column("workflow_runs", "heartbeat_at")
    op.drop_column("workflow_runs", "lease_expires_at")
    op.drop_column("workflow_runs", "claimed_by")
