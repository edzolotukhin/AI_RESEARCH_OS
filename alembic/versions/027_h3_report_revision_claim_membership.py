"""Add immutable ReportClaim membership across report revisions."""

from alembic import op
import sqlalchemy as sa

revision = "027_h3_claim_membership"
down_revision = "026_approved_delivery_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_report_claims_contract_version", "report_claims", type_="check")
    op.create_check_constraint(
        "ck_report_claims_contract_version", "report_claims",
        "contract_version IN ('desk_report_claim_v1', 'desk_h3_structural_claim_v1')",
    )
    op.create_table(
        "report_revision_claims",
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("report_revision", sa.Integer(), nullable=False),
        sa.Column("report_claim_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["report_claim_id"], ["report_claims.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("report_id", "report_revision", "report_claim_id"),
        sa.CheckConstraint("report_revision > 0", name="ck_report_revision_claims_positive_revision"),
    )
    op.create_index(
        "ix_report_revision_claims_report_revision",
        "report_revision_claims", ["report_id", "report_revision"],
    )
    op.create_index(
        "ix_report_revision_claims_claim",
        "report_revision_claims", ["report_claim_id"],
    )
    op.execute("""
        INSERT INTO report_revision_claims (report_id, report_revision, report_claim_id)
        SELECT report_id, report_revision, id FROM report_claims
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        CREATE FUNCTION reject_report_revision_claim_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'report_revision_claims are immutable'; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_report_revision_claims_immutable
        BEFORE UPDATE OR DELETE ON report_revision_claims
        FOR EACH ROW EXECUTE FUNCTION reject_report_revision_claim_mutation()
    """)
    op.execute("""
        CREATE FUNCTION ensure_report_claim_membership() RETURNS trigger AS $$
        BEGIN
          INSERT INTO report_revision_claims (report_id, report_revision, report_claim_id)
          VALUES (NEW.report_id, NEW.report_revision, NEW.id)
          ON CONFLICT DO NOTHING;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_report_claims_membership_compatibility
        AFTER INSERT ON report_claims
        FOR EACH ROW EXECUTE FUNCTION ensure_report_claim_membership()
    """)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("""
        SELECT EXISTS (
          SELECT 1 FROM report_revision_claims rrc
          GROUP BY rrc.report_claim_id HAVING COUNT(*) > 1
        )
    """)).scalar() or connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM report_claims WHERE contract_version = 'desk_h3_structural_claim_v1')"
    )).scalar():
        raise RuntimeError("Refusing downgrade after H3 or multi-revision ReportClaim membership")
    op.execute("DROP TRIGGER IF EXISTS trg_report_claims_membership_compatibility ON report_claims")
    op.execute("DROP FUNCTION IF EXISTS ensure_report_claim_membership()")
    op.execute("DROP TRIGGER IF EXISTS trg_report_revision_claims_immutable ON report_revision_claims")
    op.execute("DROP FUNCTION IF EXISTS reject_report_revision_claim_mutation()")
    op.drop_index("ix_report_revision_claims_claim", table_name="report_revision_claims")
    op.drop_index("ix_report_revision_claims_report_revision", table_name="report_revision_claims")
    op.drop_table("report_revision_claims")
    op.drop_constraint("ck_report_claims_contract_version", "report_claims", type_="check")
    op.create_check_constraint(
        "ck_report_claims_contract_version", "report_claims",
        "contract_version = 'desk_report_claim_v1'",
    )
