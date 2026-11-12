"""Immutable extracted Source revisions and run-scoped acquisition paths."""
from alembic import op
import sqlalchemy as sa
import hashlib
import json

revision = "030_source_revisions"
down_revision = "029_presentation_draft_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    for name, typ in (("terminal_resource_key", sa.String(64)),
                      ("raw_content_checksum", sa.String(64)),
                      ("raw_checksum_kind", sa.String(32)),
                      ("content_revision", sa.Integer()),
                      ("extraction_revision", sa.String(64))):
        op.add_column("sources", sa.Column(name, typ, nullable=True))
    connection = op.get_bind()
    # Freeze identity-v1 normalization in this migration, not future app code.
    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id", "fbclid", "gclid", "mc_cid", "mc_eid"}
    for row in connection.execute(sa.text("SELECT id, project_id, url, canonical_url, content_checksum FROM sources")).mappings():
        parsed = urlparse(row["url"])
        host = (parsed.hostname or "").lower()
        if parsed.port and (parsed.scheme.lower(), parsed.port) not in {("http", 80), ("https", 443)}:
            host += ":" + str(parsed.port)
        path = parsed.path if parsed.path == "/" else parsed.path.rstrip("/")
        url = urlunparse((parsed.scheme.lower(), host, path, "", urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in tracking)), ""))
        key = hashlib.sha256(json.dumps(("terminal-resource-v1", row["project_id"], url), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        # Historical binary bytes are unknown. Never label this as a byte digest.
        surrogate = hashlib.sha256(("legacy-source:" + row["id"]).encode()).hexdigest()
        connection.execute(sa.text("UPDATE sources SET terminal_resource_key=:key, raw_content_checksum=:raw, raw_checksum_kind='legacy-surrogate', content_revision=1, extraction_revision='legacy-v1' WHERE id=:id"), {"key": key, "raw": surrogate, "id": row["id"]})
    # Never invent chronological binary revisions for legacy snapshots.
    # An ambiguous legacy identity must roll the migration back atomically.
    if connection.execute(sa.text("SELECT 1 FROM sources GROUP BY project_id, terminal_resource_key HAVING count(*) > 1 LIMIT 1")).first():
        raise RuntimeError("Ambiguous legacy terminal identity; migration requires explicit legacy mapping")
    for name in ("terminal_resource_key", "raw_content_checksum", "raw_checksum_kind", "content_revision", "extraction_revision"):
        op.alter_column("sources", name, nullable=False)
    op.drop_constraint("uq_sources_project_canonical_url", "sources", type_="unique")
    op.create_unique_constraint("uq_sources_resource_revision", "sources", ["project_id", "terminal_resource_key", "content_revision", "extraction_revision"])
    op.create_unique_constraint("uq_sources_snapshot", "sources", ["project_id", "terminal_resource_key", "raw_checksum_kind", "raw_content_checksum", "extraction_revision"])
    op.create_check_constraint("ck_source_revision_positive", "sources", "content_revision > 0")
    op.create_index("ix_sources_terminal_latest", "sources", ["project_id", "terminal_resource_key", "content_revision"])
    op.create_table("source_acquisition_paths",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("workflow_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id"), nullable=False, index=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=False, index=True),
        sa.Column("path_digest", sa.String(64), nullable=False),
        sa.Column("landing_url", sa.Text(), nullable=False),
        sa.Column("terminal_url", sa.Text(), nullable=False),
        sa.Column("navigation_chain", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workflow_run_id", "path_digest", "source_id", name="uq_source_path_observation"))


def downgrade():
    connection = op.get_bind()
    duplicates = connection.execute(sa.text("SELECT 1 FROM sources GROUP BY project_id, canonical_url HAVING count(*) > 1 LIMIT 1")).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade: historical revisions share canonical URLs")
    op.drop_table("source_acquisition_paths")
    op.drop_index("ix_sources_terminal_latest", table_name="sources")
    for name in ("uq_sources_resource_revision", "uq_sources_snapshot", "ck_source_revision_positive"):
        op.drop_constraint(name, "sources")
    op.create_unique_constraint("uq_sources_project_canonical_url", "sources", ["project_id", "canonical_url"])
    for name in ("terminal_resource_key", "raw_content_checksum", "raw_checksum_kind", "content_revision", "extraction_revision"):
        op.drop_column("sources", name)
