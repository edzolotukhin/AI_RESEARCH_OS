"""QUA-02 coding and thematic-analysis Activity catalogue."""
from alembic import op
import sqlalchemy as sa

revision = "020_qua02_thematic_analysis"
down_revision = "019_qua01_transcript_authority"
branch_labels = None
depends_on = None

_EVENTS = ("'PROJECT_CREATED','DESIGN_APPROVED','METHOD_ACTIVATED','DESK_REPORT_DRAFT_CREATED',"
    "'DESK_REVIEW_ATTENTION','QUANT_REVIEW_ATTENTION','QUANT_REVIEW_APPROVED','QUANT_APPROVED_REVISION_CREATED',"
    "'QUANT_PDF_GENERATED','QUANT_PPTX_GENERATED','QUAL_RUN_CREATED','QUAL_SESSION_CREATED','QUAL_ARTIFACT_ACCEPTED',"
    "'QUAL_TRANSCRIPTION_STARTED','QUAL_TRANSCRIPTION_COMPLETED','QUAL_TRANSCRIPTION_FAILED','QUAL_TRANSCRIPT_READY',"
    "'QUAL_TRANSCRIPT_DOCX_GENERATED','QUAL_AUTHORITY_READY','QUAL_ANALYSIS_CORPUS_FROZEN',"
    "'QUAL_CODEBOOK_REVISION_CREATED','QUAL_AI_CODING_COMPLETED','QUAL_CODING_REVISION_ACCEPTED',"
    "'QUAL_THEMATIC_REVISION_CREATED','QUAL_THEMATIC_ANALYSIS_ACCEPTED','QUAL_READY_FOR_FINDINGS'")
_SOURCES = ("'project','design','run','study','report','review','revision','deliverable','session','qual_artifact',"
    "'transcription_job','transcript','transcript_export','qual_analysis_corpus','qual_codebook','qual_ai_proposal',"
    "'qual_coding','qual_thematic_analysis'")

def upgrade():
    op.drop_constraint("ck_project_activity_type","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_type","project_activity",f"event_type IN ({_EVENTS})")
    op.drop_constraint("ck_project_activity_source_kind","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_source_kind","project_activity",f"source_kind IN ({_SOURCES})")

def downgrade():
    used=op.get_bind().execute(sa.text("SELECT COUNT(*) FROM project_activity WHERE event_type LIKE 'QUAL_%' AND event_type IN ('QUAL_ANALYSIS_CORPUS_FROZEN','QUAL_CODEBOOK_REVISION_CREATED','QUAL_AI_CODING_COMPLETED','QUAL_CODING_REVISION_ACCEPTED','QUAL_THEMATIC_REVISION_CREATED','QUAL_THEMATIC_ANALYSIS_ACCEPTED','QUAL_READY_FOR_FINDINGS')")).scalar_one()
    if used: raise ValueError("QUA-02 Activity must be preserved; downgrade refused")
    op.drop_constraint("ck_project_activity_source_kind","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_source_kind","project_activity","source_kind IN ('project','design','run','study','report','review','revision','deliverable','session','qual_artifact','transcription_job','transcript','transcript_export')")
    op.drop_constraint("ck_project_activity_type","project_activity",type_="check")
    old=_EVENTS.rsplit(",",7)[0]
    op.create_check_constraint("ck_project_activity_type","project_activity",f"event_type IN ({old})")
