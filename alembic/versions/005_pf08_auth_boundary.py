"""Add API keys and project ownership for PF-08 authentication boundary."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "005_pf08_auth_boundary"
down_revision = "004_pf07_submission_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("principal_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_prefix", name="uq_api_keys_key_prefix"),
    )
    op.create_index("ix_api_keys_principal_id", "api_keys", ["principal_id"])

    op.add_column(
        "projects",
        sa.Column("owner_principal_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_projects_owner_principal_id",
        "projects",
        ["owner_principal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_owner_principal_id", table_name="projects")
    op.drop_column("projects", "owner_principal_id")
    op.drop_index("ix_api_keys_principal_id", table_name="api_keys")
    op.drop_table("api_keys")
