"""Allow qualitative Report and deliverable Activity events."""
from alembic import op
import sqlalchemy as sa

revision = "022_qua04_report_deliverables"
down_revision = "021_qua03_findings_review"
branch_labels = None
depends_on = None

_EVENTS = ("'PROJECT_CREATED','DESIGN_APPROVED','METHOD_ACTIVATED','DESK_REPORT_DRAFT_CREATED',"
    "'DESK_REVIEW_ATTENTION','QUANT_REVIEW_ATTENTION','QUANT_REVIEW_APPROVED','QUANT_APPROVED_REVISION_CREATED',"
    "'QUANT_PDF_GENERATED','QUANT_PPTX_GENERATED','QUAL_RUN_CREATED','QUAL_SESSION_CREATED','QUAL_ARTIFACT_ACCEPTED',"
    "'QUAL_TRANSCRIPTION_STARTED','QUAL_TRANSCRIPTION_COMPLETED','QUAL_TRANSCRIPTION_FAILED','QUAL_TRANSCRIPT_READY',"
    "'QUAL_TRANSCRIPT_DOCX_GENERATED','QUAL_AUTHORITY_READY','QUAL_ANALYSIS_CORPUS_FROZEN','QUAL_CODEBOOK_REVISION_CREATED',"
    "'QUAL_AI_CODING_COMPLETED','QUAL_CODING_REVISION_ACCEPTED','QUAL_THEMATIC_REVISION_CREATED',"
    "'QUAL_THEMATIC_ANALYSIS_ACCEPTED','QUAL_READY_FOR_FINDINGS','QUAL_FINDINGS_REVISION_CREATED','QUAL_AI_FINDINGS_READY',"
    "'QUAL_FINDING_ACCEPTED','QUAL_INSIGHT_ACCEPTED','QUAL_REVIEW_REQUESTED','QUAL_REVIEW_CHANGES_REQUIRED',"
    "'QUAL_REVIEW_APPROVED','QUAL_APPROVED_REVISION_CREATED','QUAL_READY_FOR_DELIVERABLES'")
_NEW = "'QUAL_REPORT_DRAFT_CREATED','QUAL_REPORT_FINALIZED','QUAL_PDF_GENERATED','QUAL_PPTX_GENERATED','QUAL_DELIVERABLE_READY'"
_SOURCES = ("'project','design','run','study','report','review','revision','deliverable','session','qual_artifact',"
    "'transcription_job','transcript','transcript_export','qual_analysis_corpus','qual_codebook','qual_ai_proposal',"
    "'qual_coding','qual_thematic_analysis','qual_finding','qual_insight','qual_post_analysis_revision',"
    "'qual_review','qual_approved_revision'")

def upgrade():
    op.drop_constraint("ck_project_activity_type","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_type","project_activity",f"event_type IN ({_EVENTS},{_NEW})")
    op.drop_constraint("ck_project_activity_source_kind","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_source_kind","project_activity",f"source_kind IN ({_SOURCES},'qual_report')")

def downgrade():
    used=op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM project_activity WHERE event_type IN ({_NEW})")).scalar_one()
    if used: raise ValueError("QUA-04 Activity must be preserved; downgrade refused")
    op.drop_constraint("ck_project_activity_type","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_type","project_activity",f"event_type IN ({_EVENTS})")
    op.drop_constraint("ck_project_activity_source_kind","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_source_kind","project_activity",f"source_kind IN ({_SOURCES})")
