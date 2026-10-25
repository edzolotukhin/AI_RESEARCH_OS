"""Durable structured Desk finalization provenance and retry states."""

from alembic import op
import sqlalchemy as sa

revision = "025_desk_structured_finalization"
down_revision = "024_desk_report_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("presentation_jobs", "state", existing_type=sa.String(16),
                    type_=sa.String(32), existing_nullable=False)
    op.drop_constraint("ck_presentation_job_state", "presentation_jobs", type_="check")
    op.create_check_constraint(
        "ck_presentation_job_state", "presentation_jobs",
        "state IN ('pending','processing','completed','failed','review_approved',"
        "'pdf_generating','pdf_complete','pptx_pending','pptx_processing',"
        "'retry_wait','pptx_complete','finalization_complete','failed_terminal')",
    )
    op.add_column("presentation_jobs", sa.Column("report_revision", sa.Integer()))
    op.add_column("presentation_jobs", sa.Column("review_id", sa.String(64)))
    op.add_column("presentation_jobs", sa.Column("source_run_id", sa.String(64)))
    op.add_column("presentation_jobs", sa.Column("claim_set_digest", sa.String(64)))
    op.add_column("presentation_jobs", sa.Column("coverage_contract_digest", sa.String(64)))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM presentation_jobs WHERE report_revision IS NOT NULL)"
    )).scalar():
        raise RuntimeError("Refusing downgrade while structured Desk finalization exists")
    for name in ("coverage_contract_digest", "claim_set_digest", "source_run_id", "review_id", "report_revision"):
        op.drop_column("presentation_jobs", name)
    op.drop_constraint("ck_presentation_job_state", "presentation_jobs", type_="check")
    op.create_check_constraint(
        "ck_presentation_job_state", "presentation_jobs",
        "state IN ('pending','processing','completed','failed')",
    )
    op.alter_column("presentation_jobs", "state", existing_type=sa.String(32),
                    type_=sa.String(16), existing_nullable=False)
