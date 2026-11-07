"""Guarded qualification runner for one existing failed Desk PPTX job."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.composition_root import create_application_container
from infrastructure.documents.pptx_renderer import PptxRenderer
from tests.integration.postgresql.helpers import postgresql_application_config
from tests.qualification.p8d_desk_evidence_runner import _validate_pptx

RUN_ID = "76dd7c91-ab9f-5097-88b6-1755fdf15a49"
JOB_ID = "44e62b98-fd83-400a-9550-0bbb84b2c640"
REVIEW_ID = "8da1af19-cd85-4ba6-87af-1eb99128ca93"
DB = "ai_research_os_p8d_isolation_test"


def guard_database() -> None:
    if os.environ.get("POSTGRESQL_INTEGRATION_TESTS") != "1":
        raise RuntimeError("POSTGRESQL_INTEGRATION_TESTS=1 is required")
    if os.environ.get("POSTGRESQL_DISPOSABLE_TEST_DATABASE") != "1":
        raise RuntimeError("POSTGRESQL_DISPOSABLE_TEST_DATABASE=1 is required")
    value = os.environ.get("DATABASE_URL_TEST", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL_TEST is required")
    parsed = urlparse(value)
    if (parsed.hostname, parsed.port or 5432, parsed.path.lstrip("/")) != ("127.0.0.1", 55432, DB):
        raise RuntimeError("refusing non-approved disposable database")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def preflight(container):
    service = container.project_deliverables_service
    run = container.workflow_service.get_workflow_run(RUN_ID)
    project = container.project_service.get_project(run.project_id)
    reports = container.report_query_service.list_reports_for_project(project.id, workflow_run_id=RUN_ID)
    if len(reports) != 1:
        raise RuntimeError(f"expected one report, got {len(reports)}")
    report = reports[0]
    reviews = container.review_query_service.list_reviews_for_project(
        project.id, workflow_run_id=RUN_ID, report_id=report.id
    )
    review = next((item for item in reviews if item.id == REVIEW_ID), None)
    if review is None or getattr(review.verdict, "value", review.verdict) != "approve":
        raise RuntimeError("approved review identity or verdict mismatch")
    jobs = [item for item in service.presentation_jobs.list_recent() if item.id == JOB_ID]
    if len(jobs) != 1:
        raise RuntimeError(f"expected one target job, got {len(jobs)}")
    job = jobs[0]
    if job.run_id != RUN_ID or job.project_id != project.id or job.source_id != report.id:
        raise RuntimeError("presentation job identity mismatch")
    if job.report_revision != report.revision_number or job.review_id != REVIEW_ID:
        raise RuntimeError("presentation job report/review binding mismatch")
    if job.state != "failed_terminal" or job.failure_code != "generation_failed":
        raise RuntimeError("target job is not the confirmed failed-terminal job")
    if job.completed_deliverable_id is not None:
        raise RuntimeError("target job unexpectedly has completed PPTX")
    renderer = service.pptx_renderer
    if not isinstance(renderer, PptxRenderer):
        raise RuntimeError("production PptxRenderer is not configured")
    if (job.renderer_version, job.template_version) != (renderer.version, renderer.template_version):
        raise RuntimeError("renderer/template identity mismatch")
    if job.attempts >= 3:
        # retry() is the only supported recovery API; it will refuse exhausted jobs.
        retry_supported = False
    else:
        retry_supported = job.state in {"failed", "retry_wait"}
    return {
        "workflow_run_id": RUN_ID, "project_id": project.id, "report_id": report.id,
        "report_revision": report.revision_number, "review_id": REVIEW_ID,
        "job_id": JOB_ID, "state": job.state, "attempts": job.attempts,
        "failure_code": job.failure_code, "source_run_id": job.source_run_id,
        "renderer_version": job.renderer_version, "template_version": job.template_version,
        "retry_supported": retry_supported,
    }, project, report, job


def execute(container, project, report, before):
    if not before["retry_supported"]:
        raise RuntimeError("production retry API does not support an exhausted failed_terminal job")
    jobs = container.project_deliverables_service.presentation_jobs
    retried = jobs.retry(JOB_ID)
    if retried is None:
        raise RuntimeError("presentation_jobs.retry() did not find target job")
    container.project_deliverables_service.process_next_presentation("p8d-targeted-retry")
    after = next(item for item in jobs.list_recent() if item.id == JOB_ID)
    if after.state not in {"completed", "finalization_complete"} or not after.completed_deliverable_id:
        raise RuntimeError(f"retry did not complete: {after.state}")
    item = container.project_deliverables_service.source(
        project.id, "DESK", report.id, owner_id=project.owner_principal_id
    )
    stored_record, stored = container.project_deliverables_service.store.get(after.completed_deliverable_id)
    downloaded_record, downloaded = container.project_deliverables_service.download_presentation(
        project.id, "DESK", report.id, after.completed_deliverable_id, owner_id=project.owner_principal_id
    )
    _validate_pptx(stored)
    if stored != downloaded or _sha(stored) != stored_record.checksum or len(stored) != stored_record.byte_size:
        raise RuntimeError("PPTX stored/downloaded checksum or size mismatch")
    if (stored_record.project_id, stored_record.run_id, stored_record.source_id) != (project.id, RUN_ID, report.id):
        raise RuntimeError("PPTX storage identity mismatch")
    if after.report_revision != report.revision_number or after.review_id != REVIEW_ID:
        raise RuntimeError("PPTX job approval identity mismatch after retry")
    return {
        "job_id": after.id, "state": after.state, "attempts": after.attempts,
        "pptx_id": stored_record.id, "stored_sha256": _sha(stored),
        "downloaded_sha256": _sha(downloaded), "checksum": stored_record.checksum,
        "byte_size": stored_record.byte_size, "renderer_version": stored_record.renderer_version,
        "template_version": stored_record.template_version,
        "source_run_id": after.source_run_id,
        "approval_provenance_present": item.document.approved_delivery_provenance is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("p8d_targeted_retry_evidence"))
    parser.add_argument("--execute", action="store_true", help="perform the single guarded retry")
    args = parser.parse_args()
    guard_database()
    container = create_application_container(config=postgresql_application_config())
    try:
        evidence, project, report, job = preflight(container)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "preflight.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        if not args.execute:
            status = "PREFLIGHT_PASS" if evidence["retry_supported"] else "PREFLIGHT_BLOCKED"
            print(json.dumps({"status": status, **evidence}, indent=2))
            return 0 if evidence["retry_supported"] else 2
        result = execute(container, project, report, evidence)
        (args.output_dir / "postflight.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"status": "RETRY_PASS", **result}, indent=2))
        return 0
    finally:
        container.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
