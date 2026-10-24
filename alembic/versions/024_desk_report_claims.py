"""Add immutable structured Desk ReportClaims."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "024_desk_report_claims"
down_revision = "023_ux01a_identity_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("report_revision", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_workflow_run_id", sa.String(36), nullable=False),
        sa.Column("report_workflow_run_id", sa.String(36), nullable=False),
        sa.Column("research_design_id", sa.String(36), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("claim_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("authority_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "report_revision", "id", name="uq_report_claims_revision_identity"),
        sa.CheckConstraint("report_revision > 0", name="ck_report_claims_positive_revision"),
        sa.CheckConstraint("contract_version = 'desk_report_claim_v1'", name="ck_report_claims_contract_version"),
    )
    op.create_index("ix_report_claims_source_workflow_run_id", "report_claims", ["source_workflow_run_id"])
    op.create_index("ix_report_claims_report_workflow_run_id", "report_claims", ["report_workflow_run_id"])
    op.create_index("ix_report_claims_report_revision", "report_claims", ["report_id", "report_revision"])
    op.execute("""
        CREATE FUNCTION reject_report_claim_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'report_claims are immutable'; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER trg_report_claims_immutable BEFORE UPDATE OR DELETE ON report_claims FOR EACH ROW EXECUTE FUNCTION reject_report_claim_mutation()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_report_claims_immutable ON report_claims")
    op.execute("DROP FUNCTION IF EXISTS reject_report_claim_mutation()")
    op.drop_index("ix_report_claims_report_revision", table_name="report_claims")
    op.drop_index("ix_report_claims_report_workflow_run_id", table_name="report_claims")
    op.drop_index("ix_report_claims_source_workflow_run_id", table_name="report_claims")
    op.drop_table("report_claims")
