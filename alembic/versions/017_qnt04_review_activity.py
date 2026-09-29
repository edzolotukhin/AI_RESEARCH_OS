"""Allow source-verified Quant Review and approved-revision Activity events."""

from alembic import op
import sqlalchemy as sa

revision = "017_qnt04_review_activity"
down_revision = "016_prf06f_pptx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_project_activity_type", "project_activity", type_="check")
    op.create_check_constraint(
        "ck_project_activity_type", "project_activity",
        "event_type IN ('PROJECT_CREATED', 'DESIGN_APPROVED', 'METHOD_ACTIVATED', "
        "'DESK_REPORT_DRAFT_CREATED', 'DESK_REVIEW_ATTENTION', "
        "'QUANT_REVIEW_ATTENTION', 'QUANT_REVIEW_APPROVED', "
        "'QUANT_APPROVED_REVISION_CREATED')")
    op.drop_constraint("ck_project_activity_attention_verdict", "project_activity", type_="check")
    op.create_check_constraint(
        "ck_project_activity_attention_verdict", "project_activity",
        "(event_type IN ('DESK_REVIEW_ATTENTION', 'QUANT_REVIEW_ATTENTION')) = "
        "(verdict IS NOT NULL)")
    op.drop_constraint("ck_project_activity_source_kind", "project_activity", type_="check")
    op.create_check_constraint(
        "ck_project_activity_source_kind", "project_activity",
        "source_kind IN ('project', 'design', 'run', 'study', 'report', 'review', 'revision')")


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(sa.text(
        "SELECT COUNT(*) FROM project_activity WHERE event_type IN "
        "('QUANT_REVIEW_ATTENTION', 'QUANT_REVIEW_APPROVED', "
        "'QUANT_APPROVED_REVISION_CREATED')"
    )).scalar_one()
    if count:
        raise ValueError("Quant Activity rows must be preserved; downgrade refused")
    op.drop_constraint("ck_project_activity_source_kind", "project_activity", type_="check")
    op.create_check_constraint(
        "ck_project_activity_source_kind", "project_activity",
        "source_kind IN ('project', 'design', 'run', 'study', 'report', 'review')")
    op.drop_constraint("ck_project_activity_attention_verdict", "project_activity", type_="check")
    op.create_check_constraint(
        "ck_project_activity_attention_verdict", "project_activity",
        "(event_type = 'DESK_REVIEW_ATTENTION') = (verdict IS NOT NULL)")
    op.drop_constraint("ck_project_activity_type", "project_activity", type_="check")
    op.create_check_constraint(
        "ck_project_activity_type", "project_activity",
        "event_type IN ('PROJECT_CREATED', 'DESIGN_APPROVED', 'METHOD_ACTIVATED', "
        "'DESK_REPORT_DRAFT_CREATED', 'DESK_REVIEW_ATTENTION')")
