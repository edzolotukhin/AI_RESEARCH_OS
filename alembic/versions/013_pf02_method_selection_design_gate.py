"""Add PF-02 Project method selection and current design gate."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013_pf02_method_design"
down_revision = "012_p1_25b_project_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("selected_methods", postgresql.JSONB(), nullable=True))
    op.add_column("projects", sa.Column("planning_design", postgresql.JSONB(), nullable=True))
    op.add_column("projects", sa.Column("planning_design_status", sa.String(32), nullable=True))
    op.add_column("projects", sa.Column("planning_design_input_fingerprint", sa.String(128), nullable=True))
    op.add_column("projects", sa.Column("planning_design_approved_by", sa.String(64), nullable=True))
    op.add_column("projects", sa.Column("planning_design_approved_at", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_projects_selected_methods_array",
        "projects",
        "selected_methods IS NULL OR jsonb_typeof(selected_methods) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_projects_selected_methods_array", "projects", type_="check")
    op.drop_column("projects", "planning_design_approved_at")
    op.drop_column("projects", "planning_design_approved_by")
    op.drop_column("projects", "planning_design_input_fingerprint")
    op.drop_column("projects", "planning_design_status")
    op.drop_column("projects", "planning_design")
    op.drop_column("projects", "selected_methods")
