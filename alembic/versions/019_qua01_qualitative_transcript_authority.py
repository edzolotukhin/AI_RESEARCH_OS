"""Canonical qualitative artifact and transcript authority."""
from alembic import op
import sqlalchemy as sa

revision = "019_qua01_transcript_authority"
down_revision = "018_qnt06d_deliverable_activity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "qualitative_state_records",
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("record_id", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("record_type", sa.String(64), nullable=False),
        sa.Column("parent_record_id", sa.String(128), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("private_bytes", sa.LargeBinary(), nullable=True),
    )
    op.create_index("ix_qualitative_state_records_run_id", "qualitative_state_records", ["run_id"])
    op.create_index("ix_qualitative_state_records_record_type", "qualitative_state_records", ["record_type"])
    op.drop_constraint("ck_project_activity_method", "project_activity", type_="check")
    op.create_check_constraint("ck_project_activity_method", "project_activity",
                               "method IS NULL OR method IN ('DESK','QUANTITATIVE','QUALITATIVE')")
    op.drop_constraint("ck_project_activity_type", "project_activity", type_="check")
    op.create_check_constraint("ck_project_activity_type", "project_activity",
        "event_type IN ('PROJECT_CREATED','DESIGN_APPROVED','METHOD_ACTIVATED','DESK_REPORT_DRAFT_CREATED',"
        "'DESK_REVIEW_ATTENTION','QUANT_REVIEW_ATTENTION','QUANT_REVIEW_APPROVED',"
        "'QUANT_APPROVED_REVISION_CREATED','QUANT_PDF_GENERATED','QUANT_PPTX_GENERATED',"
        "'QUAL_RUN_CREATED','QUAL_SESSION_CREATED','QUAL_ARTIFACT_ACCEPTED','QUAL_TRANSCRIPTION_STARTED',"
        "'QUAL_TRANSCRIPTION_COMPLETED','QUAL_TRANSCRIPTION_FAILED','QUAL_TRANSCRIPT_READY',"
        "'QUAL_TRANSCRIPT_DOCX_GENERATED','QUAL_AUTHORITY_READY')")
    op.drop_constraint("ck_project_activity_source_kind", "project_activity", type_="check")
    op.create_check_constraint("ck_project_activity_source_kind", "project_activity",
        "source_kind IN ('project','design','run','study','report','review','revision','deliverable',"
        "'session','qual_artifact','transcription_job','transcript','transcript_export')")


def downgrade():
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM project_activity WHERE method='QUALITATIVE'")).scalar_one()
    records = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM qualitative_state_records")).scalar_one()
    if count or records:
        raise ValueError("Qualitative authority data must be preserved; downgrade refused")
    op.drop_constraint("ck_project_activity_source_kind", "project_activity", type_="check")
    op.create_check_constraint("ck_project_activity_source_kind", "project_activity",
        "source_kind IN ('project', 'design', 'run', 'study', 'report', 'review', 'revision', 'deliverable')")
    op.drop_constraint("ck_project_activity_type", "project_activity", type_="check")
    op.create_check_constraint("ck_project_activity_type", "project_activity",
        "event_type IN ('PROJECT_CREATED', 'DESIGN_APPROVED', 'METHOD_ACTIVATED', 'DESK_REPORT_DRAFT_CREATED', "
        "'DESK_REVIEW_ATTENTION', 'QUANT_REVIEW_ATTENTION', 'QUANT_REVIEW_APPROVED', "
        "'QUANT_APPROVED_REVISION_CREATED', 'QUANT_PDF_GENERATED', 'QUANT_PPTX_GENERATED')")
    op.drop_index("ix_qualitative_state_records_record_type", table_name="qualitative_state_records")
    op.drop_index("ix_qualitative_state_records_run_id", table_name="qualitative_state_records")
    op.drop_table("qualitative_state_records")
    op.drop_constraint("ck_project_activity_method", "project_activity", type_="check")
    op.create_check_constraint("ck_project_activity_method", "project_activity",
                               "method IS NULL OR method IN ('DESK','QUANTITATIVE')")
