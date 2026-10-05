"""Pilot users, browser sessions, and project memberships."""
from alembic import op
import sqlalchemy as sa

revision="023_ux01a_identity_membership";down_revision="022_qua04_report_deliverables";branch_labels=None;depends_on=None

def upgrade():
    op.create_table("users",sa.Column("id",sa.String(36),primary_key=True),sa.Column("email",sa.String(254),nullable=False,unique=True),sa.Column("display_name",sa.String(160),nullable=False),sa.Column("password_hash",sa.String(256),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.CheckConstraint("status IN ('active','disabled')",name="ck_users_status"))
    op.create_table("browser_sessions",sa.Column("id",sa.String(36),primary_key=True),sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("token_hash",sa.String(64),nullable=False,unique=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("revoked_at",sa.DateTime(timezone=True)),sa.Index("ix_browser_sessions_user_id","user_id"),sa.Index("ix_browser_sessions_expires_at","expires_at"))
    op.create_table("project_memberships",sa.Column("project_id",sa.String(64),sa.ForeignKey("projects.id",ondelete="CASCADE"),primary_key=True),sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),primary_key=True),sa.Column("role",sa.String(16),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_by",sa.String(36),sa.ForeignKey("users.id",ondelete="SET NULL")),sa.CheckConstraint("role IN ('OWNER','RESEARCHER','VIEWER')",name="ck_project_memberships_role"))

def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM project_memberships")).scalar_one() or bind.execute(sa.text("SELECT count(*) FROM users")).scalar_one(): raise ValueError("UX-01A identity data must be preserved; downgrade refused")
    op.drop_table("project_memberships");op.drop_table("browser_sessions");op.drop_table("users")
