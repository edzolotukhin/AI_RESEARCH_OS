"""Add durable research sources for DR-03 source acquisition."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "006_dr03_sources"
down_revision = "005_pf08_auth_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("query_refs", sa.JSON(), nullable=False, server_default="[]"),
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
        sa.Column("workflow_run_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "research_design_refs",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("retrieval_status", sa.String(length=32), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_checksum", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "canonical_url",
            name="uq_sources_project_canonical_url",
        ),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])
    op.create_index("ix_sources_retrieval_status", "sources", ["retrieval_status"])


def downgrade() -> None:
    op.drop_index("ix_sources_retrieval_status", table_name="sources")
    op.drop_index("ix_sources_project_id", table_name="sources")
    op.drop_table("sources")
