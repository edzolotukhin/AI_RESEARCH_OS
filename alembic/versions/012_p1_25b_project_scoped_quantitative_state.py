"""Scope quantitative-state relational identity by project."""

from alembic import op
import sqlalchemy as sa

revision = "012_p1_25b_project_scope"
down_revision = "011_q1_15_quantitative_state"
branch_labels = None
depends_on = None

_TABLE = "quantitative_state_records"
_OLD_PRIMARY_KEY = "quantitative_state_records_pkey"
_OLD_UNIQUE = "uq_quantitative_state_project_record"


def upgrade() -> None:
    op.drop_constraint(_OLD_PRIMARY_KEY, _TABLE, type_="primary")
    op.drop_constraint(_OLD_UNIQUE, _TABLE, type_="unique")
    op.create_primary_key(_OLD_PRIMARY_KEY, _TABLE, ["project_id", "record_id"])


def downgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT record_id FROM quantitative_state_records "
            "GROUP BY record_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise RuntimeError(
            "cannot downgrade quantitative_state_records to globally unique "
            f"record_id; cross-project duplicate exists: {duplicate!r}"
        )
    op.drop_constraint(_OLD_PRIMARY_KEY, _TABLE, type_="primary")
    op.create_primary_key(_OLD_PRIMARY_KEY, _TABLE, ["record_id"])
    op.create_unique_constraint(_OLD_UNIQUE, _TABLE, ["project_id", "record_id"])
