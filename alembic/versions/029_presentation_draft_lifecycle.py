"""Allow durable P8 draft presentation lifecycle states."""

from alembic import op


revision = "029_presentation_draft_lifecycle"
down_revision = "028_research_authority_extension"
branch_labels = None
depends_on = None


_STATES = (
    "'pending','processing','completed','failed','review_approved',"
    "'pdf_generating','pdf_complete','pptx_pending','pptx_processing',"
    "'retry_wait','pptx_complete','finalization_complete','failed_terminal',"
    "'draft_pending','ready_for_review','draft_failed'"
)


def upgrade() -> None:
    op.drop_constraint("ck_presentation_job_state", "presentation_jobs", type_="check")
    op.create_check_constraint(
        "ck_presentation_job_state",
        "presentation_jobs",
        f"state IN ({_STATES})",
    )


def downgrade() -> None:
    raise RuntimeError(
        "029_presentation_draft_lifecycle is forward-only; refusing to "
        "downgrade while draft lifecycle states may be persisted"
    )
