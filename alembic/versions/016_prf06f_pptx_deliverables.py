"""Extend immutable deliverables and add durable presentation jobs."""

from alembic import op
import sqlalchemy as sa

revision = "016_prf06f_pptx"
down_revision = "015_prf06e_pdf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("pdf_deliverables", "media_type", existing_type=sa.String(32),
                    type_=sa.String(100), existing_nullable=False)
    op.add_column("pdf_deliverables", sa.Column("format", sa.String(8), nullable=False,
                                               server_default="PDF"))
    op.add_column("pdf_deliverables", sa.Column("template_version", sa.String(64), nullable=False,
                                               server_default="pdf-v1"))
    op.drop_constraint("uq_pdf_deliverable_source_renderer", "pdf_deliverables", type_="unique")
    op.create_unique_constraint("uq_project_deliverable_identity", "pdf_deliverables",
                                ["project_id", "method", "source_id", "source_version",
                                 "format", "template_version", "renderer_version"])
    op.drop_constraint("ck_pdf_deliverable_size", "pdf_deliverables", type_="check")
    op.create_check_constraint("ck_pdf_deliverable_size", "pdf_deliverables",
                               "byte_size > 0 AND ((format = 'PDF' AND byte_size <= 5000000) "
                               "OR (format = 'PPTX' AND byte_size <= 10000000))")
    op.drop_constraint("ck_pdf_deliverable_state", "pdf_deliverables", type_="check")
    op.create_check_constraint("ck_pdf_deliverable_state", "pdf_deliverables",
                               "state = 'completed' AND ((format = 'PDF' AND media_type = 'application/pdf') "
                               "OR (format = 'PPTX' AND media_type = "
                               "'application/vnd.openxmlformats-officedocument.presentationml.presentation'))")
    op.create_table(
        "presentation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("study_id", sa.String(64)),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("source_version", sa.String(192), nullable=False),
        sa.Column("status_snapshot", sa.String(96), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("renderer_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("claimed_by", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_deliverable_id", sa.String(36), sa.ForeignKey("pdf_deliverables.id")),
        sa.Column("failure_code", sa.String(64)),
        sa.UniqueConstraint("project_id", "method", "source_id", "source_version",
                            "template_version", "renderer_version", name="uq_presentation_job_identity"),
        sa.CheckConstraint("state IN ('pending', 'processing', 'completed', 'failed')",
                           name="ck_presentation_job_state"),
        sa.CheckConstraint("attempts >= 0", name="ck_presentation_job_attempts"),
    )
    op.create_index("ix_presentation_jobs_claim", "presentation_jobs", ["state", "lease_until", "created_at"])


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pdf_deliverables WHERE format = 'PPTX')")).scalar():
        raise RuntimeError("Refusing PRF-06F downgrade while immutable PPTX deliverables exist")
    op.drop_index("ix_presentation_jobs_claim", table_name="presentation_jobs")
    op.drop_table("presentation_jobs")
    op.drop_constraint("ck_pdf_deliverable_state", "pdf_deliverables", type_="check")
    op.create_check_constraint("ck_pdf_deliverable_state", "pdf_deliverables",
                               "state = 'completed' AND media_type = 'application/pdf'")
    op.drop_constraint("ck_pdf_deliverable_size", "pdf_deliverables", type_="check")
    op.create_check_constraint("ck_pdf_deliverable_size", "pdf_deliverables",
                               "byte_size > 0 AND byte_size <= 5000000")
    op.drop_constraint("uq_project_deliverable_identity", "pdf_deliverables", type_="unique")
    op.create_unique_constraint("uq_pdf_deliverable_source_renderer", "pdf_deliverables",
                                ["project_id", "method", "source_id", "source_version", "renderer_version"])
    op.drop_column("pdf_deliverables", "template_version")
    op.drop_column("pdf_deliverables", "format")
    op.alter_column("pdf_deliverables", "media_type", existing_type=sa.String(100),
                    type_=sa.String(32), existing_nullable=False)
