"""Add exact approved-delivery provenance to durable outputs."""

from alembic import op
import sqlalchemy as sa


revision = "026_approved_delivery_provenance"
down_revision = "025_desk_structured_finalization"
branch_labels = None
depends_on = None


def _delivery_columns(prefix: str = "approved_") -> tuple[sa.Column, ...]:
    return (
        sa.Column(f"{prefix}revision_number", sa.Integer()),
        sa.Column(f"{prefix}authority_digest", sa.String(64)),
        sa.Column(f"{prefix}presentation_digest", sa.String(64)),
        sa.Column(f"{prefix}review_id", sa.String(64)),
        sa.Column(f"{prefix}source_workflow_run_id", sa.String(64)),
        sa.Column(f"{prefix}claim_set_digest", sa.String(64)),
        sa.Column(f"{prefix}coverage_contract_digest", sa.String(64)),
    )


def upgrade() -> None:
    for table in ("artifacts", "pdf_deliverables"):
        for column in _delivery_columns():
            op.add_column(table, column)
        op.create_check_constraint(
            f"ck_{table}_approved_revision_positive",
            table,
            "approved_revision_number IS NULL OR approved_revision_number > 0",
        )
    op.add_column("presentation_jobs", sa.Column("authority_digest", sa.String(64)))
    op.add_column("presentation_jobs", sa.Column("presentation_digest", sa.String(64)))


def downgrade() -> None:
    op.drop_column("presentation_jobs", "presentation_digest")
    op.drop_column("presentation_jobs", "authority_digest")
    for table in ("pdf_deliverables", "artifacts"):
        op.drop_constraint(f"ck_{table}_approved_revision_positive", table, type_="check")
        for column in reversed(_delivery_columns()):
            op.drop_column(table, column.name)
