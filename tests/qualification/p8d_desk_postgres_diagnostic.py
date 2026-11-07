"""Read-only extraction of one failed Desk PPTX payload from disposable PostgreSQL."""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.composition_root import create_application_container
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.qualification.p8d_pptx_diagnostic import render_payload

TARGET_DB = "ai_research_os_p8d_isolation_test"
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 55432


def _guard_database() -> None:
    from urllib.parse import urlparse

    if os.environ.get("POSTGRESQL_INTEGRATION_TESTS") != "1":
        raise RuntimeError("POSTGRESQL_INTEGRATION_TESTS=1 is required")
    if os.environ.get("POSTGRESQL_DISPOSABLE_TEST_DATABASE") != "1":
        raise RuntimeError("POSTGRESQL_DISPOSABLE_TEST_DATABASE=1 is required")
    url = os.environ.get("DATABASE_URL_TEST", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL_TEST is required")
    parsed = urlparse(url)
    if (parsed.hostname, parsed.port or 5432, parsed.path.lstrip("/")) != (
        TARGET_HOST, TARGET_PORT, TARGET_DB
    ):
        raise RuntimeError("refusing non-approved disposable database")


def diagnose(run_id: str):
    _guard_database()
    container = create_application_container(
        config=postgresql_application_config(
            deterministic_stage_executors=False,
            search_provider="deterministic",
            evidence_extractor="deterministic",
            analysis_engine="deterministic",
            report_engine="deterministic",
            review_engine="deterministic",
        )
    )
    try:
        run = container.workflow_service.get_workflow_run(run_id)
        project = container.project_service.get_project(run.project_id)
        reports = container.report_query_service.list_reports_for_project(
            project.id, workflow_run_id=run_id
        )
        if not reports:
            raise RuntimeError("no persisted report exists for the target workflow run")
        if len(reports) != 1:
            raise RuntimeError(f"ambiguous report count for target run: {len(reports)}")
        report = reports[0]
        item = container.project_deliverables_service.source(
            project.id, "DESK", report.id, owner_id=project.owner_principal_id
        )
        # asdict is held only in memory and is never printed or written.
        result = render_payload(asdict(item.document))
        return {
            "workflow_run_id": run_id,
            "report_present": True,
            "report_revision": report.revision_number,
            "category": result.category,
            "returncode": result.returncode,
            "stderr": result.stderr,
            "stdout_size": result.stdout_size,
        }
    finally:
        container.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        result = diagnose(args.run_id)
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0 if result["category"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
