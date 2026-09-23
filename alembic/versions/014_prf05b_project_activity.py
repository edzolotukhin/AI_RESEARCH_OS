"""Add canonical Project Activity without backfilling historical rows."""

from alembic import op
import sqlalchemy as sa

revision = "014_prf05b_activity"
down_revision = "013_pf02_method_design"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_activity",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("semantic_key", sa.String(192), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(16)), sa.Column("run_id", sa.String(64)),
        sa.Column("actor_id", sa.String(64)), sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64)), sa.Column("verdict", sa.String(16)),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("project_id", "semantic_key", name="uq_project_activity_semantic"),
        sa.CheckConstraint(
            "event_type IN ('PROJECT_CREATED', 'DESIGN_APPROVED', 'METHOD_ACTIVATED', "
            "'DESK_REPORT_DRAFT_CREATED', 'DESK_REVIEW_ATTENTION')", name="ck_project_activity_type"),
        sa.CheckConstraint("method IS NULL OR method IN ('DESK', 'QUANTITATIVE')", name="ck_project_activity_method"),
        sa.CheckConstraint("verdict IS NULL OR verdict IN ('REVISE', 'REJECT')", name="ck_project_activity_verdict"),
        sa.CheckConstraint("source_kind IN ('project', 'design', 'run', 'study', 'report', 'review')", name="ck_project_activity_source_kind"),
        sa.CheckConstraint("event_version > 0", name="ck_project_activity_version"),
        sa.CheckConstraint("(event_type = 'DESK_REVIEW_ATTENTION') = (verdict IS NOT NULL)", name="ck_project_activity_attention_verdict"),
        sa.CheckConstraint("event_type <> 'METHOD_ACTIVATED' OR (method IS NOT NULL AND run_id IS NOT NULL)", name="ck_project_activity_activation_shape"),
    )
    op.create_index("ix_project_activity_project_order", "project_activity", ["project_id", "occurred_at", "event_id"])


def downgrade() -> None:
    op.drop_index("ix_project_activity_project_order", table_name="project_activity")
    op.drop_table("project_activity")
