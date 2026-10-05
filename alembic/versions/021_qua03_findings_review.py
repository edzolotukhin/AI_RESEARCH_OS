"""QUA-03 Findings, Insights, Review and Approved Revision Activity catalogue."""
from alembic import op
import sqlalchemy as sa

revision = "021_qua03_findings_review"
down_revision = "020_qua02_thematic_analysis"
branch_labels = None
depends_on = None

_OLD_EVENTS = ("'PROJECT_CREATED','DESIGN_APPROVED','METHOD_ACTIVATED','DESK_REPORT_DRAFT_CREATED',"
    "'DESK_REVIEW_ATTENTION','QUANT_REVIEW_ATTENTION','QUANT_REVIEW_APPROVED','QUANT_APPROVED_REVISION_CREATED',"
    "'QUANT_PDF_GENERATED','QUANT_PPTX_GENERATED','QUAL_RUN_CREATED','QUAL_SESSION_CREATED','QUAL_ARTIFACT_ACCEPTED',"
    "'QUAL_TRANSCRIPTION_STARTED','QUAL_TRANSCRIPTION_COMPLETED','QUAL_TRANSCRIPTION_FAILED','QUAL_TRANSCRIPT_READY',"
    "'QUAL_TRANSCRIPT_DOCX_GENERATED','QUAL_AUTHORITY_READY','QUAL_ANALYSIS_CORPUS_FROZEN',"
    "'QUAL_CODEBOOK_REVISION_CREATED','QUAL_AI_CODING_COMPLETED','QUAL_CODING_REVISION_ACCEPTED',"
    "'QUAL_THEMATIC_REVISION_CREATED','QUAL_THEMATIC_ANALYSIS_ACCEPTED','QUAL_READY_FOR_FINDINGS'")
_NEW_EVENTS = ("'QUAL_FINDINGS_REVISION_CREATED','QUAL_AI_FINDINGS_READY','QUAL_FINDING_ACCEPTED',"
    "'QUAL_INSIGHT_ACCEPTED','QUAL_REVIEW_REQUESTED','QUAL_REVIEW_CHANGES_REQUIRED','QUAL_REVIEW_APPROVED',"
    "'QUAL_APPROVED_REVISION_CREATED','QUAL_READY_FOR_DELIVERABLES'")
_OLD_SOURCES = ("'project','design','run','study','report','review','revision','deliverable','session','qual_artifact',"
    "'transcription_job','transcript','transcript_export','qual_analysis_corpus','qual_codebook','qual_ai_proposal',"
    "'qual_coding','qual_thematic_analysis'")
_NEW_SOURCES = "'qual_finding','qual_insight','qual_post_analysis_revision','qual_review','qual_approved_revision'"

def upgrade():
    op.drop_constraint("ck_project_activity_type","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_type","project_activity",f"event_type IN ({_OLD_EVENTS},{_NEW_EVENTS})")
    op.drop_constraint("ck_project_activity_source_kind","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_source_kind","project_activity",f"source_kind IN ({_OLD_SOURCES},{_NEW_SOURCES})")

def downgrade():
    used=op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM project_activity WHERE event_type IN ({_NEW_EVENTS})")).scalar_one()
    if used: raise ValueError("QUA-03 Activity must be preserved; downgrade refused")
    op.drop_constraint("ck_project_activity_type","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_type","project_activity",f"event_type IN ({_OLD_EVENTS})")
    op.drop_constraint("ck_project_activity_source_kind","project_activity",type_="check")
    op.create_check_constraint("ck_project_activity_source_kind","project_activity",f"source_kind IN ({_OLD_SOURCES})")
