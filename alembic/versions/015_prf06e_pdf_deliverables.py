"""Store immutable completed PDF bytes atomically with metadata."""

from alembic import op
import sqlalchemy as sa

revision = "015_prf06e_pdf"
down_revision = "014_prf05b_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pdf_deliverables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("study_id", sa.String(64)),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("source_version", sa.String(192), nullable=False),
        sa.Column("status_snapshot", sa.String(96), nullable=False),
        sa.Column("renderer_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("storage_key", sa.String(128), unique=True, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(160), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("project_id", "method", "source_id", "source_version", "renderer_version",
                            name="uq_pdf_deliverable_source_renderer"),
        sa.CheckConstraint("byte_size > 0 AND byte_size <= 5000000", name="ck_pdf_deliverable_size"),
        sa.CheckConstraint("method IN ('DESK', 'QUANTITATIVE')", name="ck_pdf_deliverable_method"),
        sa.CheckConstraint("state = 'completed' AND media_type = 'application/pdf'", name="ck_pdf_deliverable_state"),
    )
    op.create_index("ix_pdf_deliverable_project", "pdf_deliverables", ["project_id", "method"])
    op.execute("""
    CREATE FUNCTION prevent_pdf_deliverable_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'completed PDF deliverables are immutable';
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER trg_pdf_deliverable_immutable
    BEFORE UPDATE OR DELETE ON pdf_deliverables
    FOR EACH ROW EXECUTE FUNCTION prevent_pdf_deliverable_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pdf_deliverable_immutable ON pdf_deliverables")
    op.execute("DROP FUNCTION IF EXISTS prevent_pdf_deliverable_mutation()")
    op.execute("DROP INDEX IF EXISTS ix_pdf_deliverable_project")
    op.drop_table("pdf_deliverables")
