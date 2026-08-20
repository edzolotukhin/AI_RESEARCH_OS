"""Add protected Quantitative safe-metadata records."""
from alembic import op
import sqlalchemy as sa

revision = "011_q1_15_quantitative_state"
down_revision = "010_dr07_review_quality_gate"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("quantitative_state_records",
        sa.Column("record_id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("record_type", sa.String(256), nullable=False),
        sa.Column("dataset_version_id", sa.String(128), nullable=True),
        sa.Column("parent_record_id", sa.String(128), nullable=True),
        sa.Column("authority_fingerprint", sa.String(128), nullable=False),
        sa.Column("payload_checksum", sa.String(128), nullable=False),
        sa.Column("codec_version", sa.String(32), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "record_id", name="uq_quantitative_state_project_record"))
    for name in ("project_id", "run_id", "record_type", "dataset_version_id", "authority_fingerprint"):
        op.create_index(f"ix_quantitative_state_records_{name}", "quantitative_state_records", [name])

def downgrade() -> None:
    for name in reversed(("project_id", "run_id", "record_type", "dataset_version_id", "authority_fingerprint")):
        op.drop_index(f"ix_quantitative_state_records_{name}", table_name="quantitative_state_records")
    op.drop_table("quantitative_state_records")
