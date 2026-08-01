"""Add explicit status to research_submissions for idempotency lifecycle."""

from __future__ import annotations

from alembic import op

revision = "004_pf07_submission_status"
down_revision = "003_pf07_research_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE research_submissions "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'pending'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE research_submissions DROP COLUMN IF EXISTS status")
