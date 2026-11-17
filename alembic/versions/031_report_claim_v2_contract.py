"""Allow persisted desk ReportClaim v2 contracts."""

from alembic import op
import sqlalchemy as sa


revision = "031_report_claim_v2_contract"
down_revision = "030_source_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_report_claims_contract_version", "report_claims", type_="check")
    op.create_check_constraint(
        "ck_report_claims_contract_version",
        "report_claims",
        "contract_version IN ("
        "'desk_report_claim_v1', "
        "'desk_h3_structural_claim_v1', "
        "'desk_report_claim_v2'"
        ")",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT EXISTS ("
        "SELECT 1 FROM report_claims "
        "WHERE contract_version = 'desk_report_claim_v2'"
        ")"
    )).scalar():
        raise RuntimeError(
            "Refusing downgrade while persisted desk_report_claim_v2 rows exist"
        )
    op.drop_constraint("ck_report_claims_contract_version", "report_claims", type_="check")
    op.create_check_constraint(
        "ck_report_claims_contract_version",
        "report_claims",
        "contract_version IN ("
        "'desk_report_claim_v1', "
        "'desk_h3_structural_claim_v1'"
        ")",
    )
