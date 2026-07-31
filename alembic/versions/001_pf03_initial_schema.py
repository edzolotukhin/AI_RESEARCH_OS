"""initial PF-03 schema

Revision ID: 001_pf03_initial
Revises:
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_pf03_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("client_request", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("qualification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("brief", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("research_design", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("snapshot_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", name="uq_workflow_templates_id"),
    )
    op.create_index(
        "ix_workflow_templates_project_id",
        "workflow_templates",
        ["project_id"],
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_template_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("dependency_graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "task_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_runs_project_id",
        "workflow_runs",
        ["project_id"],
    )

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("definition_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("executor_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("executor_type", sa.String(length=64), nullable=False),
        sa.Column(
            "depends_on",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "task_id",
            name="uq_workflow_tasks_run_task",
        ),
    )
    op.create_index(
        "ix_workflow_tasks_workflow_run_id",
        "workflow_tasks",
        ["workflow_run_id"],
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("artifact_type", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="Draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])

    op.create_table(
        "knowledge_items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_items_project_id",
        "knowledge_items",
        ["project_id"],
    )

    op.create_table(
        "execution_log_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_execution_log_entries_event_id"),
    )
    op.create_index(
        "ix_execution_log_entries_run_id",
        "execution_log_entries",
        ["run_id"],
    )
    op.create_index(
        "ix_execution_log_entries_run_id_task_id",
        "execution_log_entries",
        ["run_id", "task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_log_entries_run_id_task_id",
        table_name="execution_log_entries",
    )
    op.drop_index(
        "ix_execution_log_entries_run_id",
        table_name="execution_log_entries",
    )
    op.drop_table("execution_log_entries")
    op.drop_index("ix_knowledge_items_project_id", table_name="knowledge_items")
    op.drop_table("knowledge_items")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_index("ix_artifacts_project_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_workflow_tasks_workflow_run_id", table_name="workflow_tasks")
    op.drop_table("workflow_tasks")
    op.drop_index("ix_workflow_runs_project_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_workflow_templates_project_id", table_name="workflow_templates")
    op.drop_table("workflow_templates")
    op.drop_table("projects")
