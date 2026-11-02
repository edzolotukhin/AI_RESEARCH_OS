"""Add immutable upstream authority extension and composition substrate."""
from alembic import op
import sqlalchemy as sa

revision = "028_research_authority_extension"
down_revision = "027_h3_claim_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("research_authority_extensions",
        sa.Column("extension_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("research_design_id", sa.String(64), nullable=False),
        sa.Column("parent_source_workflow_run_id", sa.String(64), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("extension_workflow_run_id", sa.String(64), sa.ForeignKey("workflow_runs.id"), nullable=False, unique=True),
        sa.Column("selected_information_need_ids", sa.JSON(), nullable=False),
        sa.Column("gap_contract_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("terminal_reason", sa.String(256)),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_authority_extensions_idempotency"),
    )
    op.create_index("ix_authority_extensions_project", "research_authority_extensions", ["project_id"])
    op.create_table("composed_research_authorities",
        sa.Column("composition_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("research_design_id", sa.String(64), nullable=False),
        sa.Column("parent_source_workflow_run_id", sa.String(64), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("selected_information_need_ids", sa.JSON(), nullable=False),
        sa.Column("composition_version", sa.String(64), nullable=False),
        sa.Column("composition_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.UniqueConstraint("composition_digest", name="uq_composed_authorities_digest"),
    )
    op.create_index("ix_composed_authorities_project", "composed_research_authorities", ["project_id"])
    op.create_table("composed_research_authority_members",
        sa.Column("composition_id", sa.String(64), sa.ForeignKey("composed_research_authorities.composition_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("workflow_run_id", sa.String(64), sa.ForeignKey("workflow_runs.id"), primary_key=True),
    )
    op.execute("""
        CREATE FUNCTION reject_composed_authority_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'composed research authority is immutable'; END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("composed_research_authorities", "composed_research_authority_members"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_composed_authority_mutation()
        """)


def downgrade() -> None:
    for table in ("composed_research_authority_members", "composed_research_authorities"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_composed_authority_mutation()")
    op.drop_table("composed_research_authority_members")
    op.drop_index("ix_composed_authorities_project", table_name="composed_research_authorities")
    op.drop_table("composed_research_authorities")
    op.drop_index("ix_authority_extensions_project", table_name="research_authority_extensions")
    op.drop_table("research_authority_extensions")
