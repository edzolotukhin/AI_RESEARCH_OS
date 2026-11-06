"""Operator-run, disposable-PostgreSQL Desk provenance qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from application.composition_root import create_application_container
from infrastructure.documents.pptx_renderer import PptxRenderer
from tests.api.auth_helpers import bootstrap_test_api_key
from tests.api.helpers import activate_approved_desk_project, drain_background_runs
from api.ui.principal import resolve_ui_principal
from tests.fixtures.research_brief import CANONICAL_BRIEF_REQUEST as BRIEF
from tests.helpers.brief_aligned_planner_llm import create_brief_aligned_llm_mock
from tests.helpers.dated_desk_integration_fixture import dated_desk_overrides
from tests.integration.postgresql.helpers import (
    postgresql_application_config,
)

EXPECTED_DB = "ai_research_os_p8d_isolation_test"
EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 55432


def _require_disposable_database() -> str:
    if os.environ.get("POSTGRESQL_INTEGRATION_TESTS") != "1":
        raise RuntimeError("POSTGRESQL_INTEGRATION_TESTS=1 is required")
    if os.environ.get("POSTGRESQL_DISPOSABLE_TEST_DATABASE") != "1":
        raise RuntimeError("POSTGRESQL_DISPOSABLE_TEST_DATABASE=1 is required")
    value = os.environ.get("DATABASE_URL_TEST", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL_TEST is required; DATABASE_URL is never used")
    parsed = urlparse(value)
    host, port, database = parsed.hostname, parsed.port or 5432, parsed.path.lstrip("/")
    if host != EXPECTED_HOST or port != EXPECTED_PORT or database != EXPECTED_DB:
        raise RuntimeError(f"refusing database {host}:{port}/{database}")
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_pptx(data: bytes) -> None:
    if not data:
        raise ValueError("PPTX is empty")
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(data)) as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "ppt/presentation.xml"}
            slides = {name for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml")}
            if not required.issubset(names) or not slides or archive.testzip() is not None:
                raise ValueError("PPTX package is structurally invalid")
            if not any(archive.read(name).strip() for name in slides):
                raise ValueError("PPTX slides are empty")
    except zipfile.BadZipFile as exc:
        raise ValueError("PPTX package is not a valid ZIP") from exc


def _jsonable(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def _collect_artifacts(container, project_id, run_id, report_id, owner_id):
    service = container.project_deliverables_service
    item = service.source(project_id, "DESK", report_id, owner_id=owner_id)
    if item.pdf is None or item.pptx is None:
        raise RuntimeError("approved Desk catalog item has no PDF/PPTX")
    pdf_record, pdf_stored = service.store.get(item.pdf.id)
    pptx_record, pptx_stored = service.store.get(item.pptx.id)
    pdf_download_record, pdf_download = service.download(
        project_id, "DESK", report_id, item.pdf.id, owner_id=owner_id
    )
    pptx_download_record, pptx_download = service.download_presentation(
        project_id, "DESK", report_id, item.pptx.id, owner_id=owner_id
    )
    if not pdf_stored or not pptx_stored or pdf_stored != pdf_download or pptx_stored != pptx_download:
        raise RuntimeError("stored and native-download bytes do not match")
    if not pdf_download.startswith(b"%PDF-") or not pptx_download.startswith(b"PK\x03\x04"):
        raise RuntimeError("invalid PDF/PPTX signature")
    jobs = [job for job in service.presentation_jobs.list_recent() if job.run_id == run_id]
    job = next((job for job in jobs if job.completed_deliverable_id == item.pptx.id), None)
    if job is None or job.state not in {"completed", "finalization_complete"}:
        raise RuntimeError("PPTX presentation job is not complete")
    _validate_pptx(pptx_download)
    return {
        "pdf": {"id": pdf_record.id, "stored_sha256": _sha(pdf_stored),
                "downloaded_sha256": _sha(pdf_download), "checksum": pdf_record.checksum,
                "byte_size": pdf_record.byte_size, "renderer_version": pdf_record.renderer_version},
        "pptx": {"id": pptx_record.id, "stored_sha256": _sha(pptx_stored),
                 "downloaded_sha256": _sha(pptx_download), "checksum": pptx_record.checksum,
                 "byte_size": pptx_record.byte_size, "renderer_version": pptx_record.renderer_version,
                 "template_version": getattr(job, "template_version", None)},
        "source_version": item.document.source_version,
        "approval_provenance": _jsonable(item.document.approved_delivery_provenance),
        "finalization_state": item.finalization_state,
        "job_review_id": job.review_id,
        "job_report_revision": job.report_revision,
        "job_source_run_id": job.source_run_id,
        "presentation_job_id": job.id,
        "presentation_state": job.state,
    }, {"pdf": pdf_download, "pptx": pptx_download}


def run(output_dir: Path) -> int:
    database_url = _require_disposable_database()
    output_dir.mkdir(parents=True, exist_ok=True)
    log = [f"started={datetime.now(timezone.utc).isoformat()}", "database=approved disposable target"]
    container = None
    try:
        container = create_application_container(
            config=postgresql_application_config(
                deterministic_stage_executors=False, search_provider="deterministic",
                evidence_extractor="deterministic", analysis_engine="deterministic",
                report_engine="deterministic", review_engine="deterministic",
            ),
            overrides=dated_desk_overrides(llm_client=create_brief_aligned_llm_mock()),
        )
        renderer = container.project_deliverables_service.pptx_renderer
        if not isinstance(renderer, PptxRenderer):
            raise RuntimeError(f"unexpected PPTX renderer: {type(renderer).__name__}")
        if (renderer.version, renderer.template_version) != ("pptxgenjs-4.0.1-2", "neutral-corporate-1"):
            raise RuntimeError("unexpected production PPTX renderer version")
        bootstrap_test_api_key(container)
        owner = resolve_ui_principal(container).principal_id
        project = container.project_service.create_project(
            f"P8-D Desk qualification {uuid4()}", owner_principal_id=owner, selected_methods=("DESK",)
        )
        run_record = activate_approved_desk_project(container, project.id, BRIEF)
        drain_background_runs(container)
        terminal = container.workflow_service.get_workflow_run(run_record.id)
        status = getattr(terminal.status, "value", terminal.status)
        if status != "completed":
            raise RuntimeError(f"Desk workflow did not complete: {status}")
        reports = container.report_query_service.list_reports_for_project(project.id, workflow_run_id=run_record.id)
        if len(reports) != 1:
            raise RuntimeError(f"expected one Desk report, found {len(reports)}")
        report = reports[0]
        reviews = container.review_query_service.list_reviews_for_project(
            project.id, workflow_run_id=run_record.id, report_id=report.id
        )
        approved = [r for r in reviews if getattr(r.verdict, "value", r.verdict) == "approve"]
        if len(approved) != 1:
            raise RuntimeError("expected exactly one approved review")
        evidence, files = _collect_artifacts(container, project.id, run_record.id, report.id, owner)
        if evidence["job_review_id"] != approved[0].id or evidence["job_report_revision"] != report.revision_number:
            raise RuntimeError("presentation job approval identity does not match persisted review/report")
        if evidence["job_source_run_id"] not in (None, run_record.id):
            raise RuntimeError("presentation job source run does not match workflow run")
        manifest = {
            "method": "DESK", "project_id": project.id, "workflow_run_id": run_record.id,
            "report_id": report.id, "report_revision": report.revision_number,
            "review_id": approved[0].id, "review_verdict": "approve",
            "source_version": evidence["source_version"], "approval_provenance": evidence["approval_provenance"],
            "artifacts": evidence,
            "checks": {
                "pdf_stored_downloaded_match": evidence["pdf"]["stored_sha256"] == evidence["pdf"]["downloaded_sha256"],
                "pptx_stored_downloaded_match": evidence["pptx"]["stored_sha256"] == evidence["pptx"]["downloaded_sha256"],
                "pdf_checksum_match": evidence["pdf"]["stored_sha256"] == evidence["pdf"]["checksum"],
                "pptx_checksum_match": evidence["pptx"]["stored_sha256"] == evidence["pptx"]["checksum"],
            },
        }
        (output_dir / "desk.pdf").write_bytes(files["pdf"])
        (output_dir / "desk.pptx").write_bytes(files["pptx"])
        manifest["artifacts"]["pdf"]["exported_sha256"] = _sha((output_dir / "desk.pdf").read_bytes())
        manifest["artifacts"]["pptx"]["exported_sha256"] = _sha((output_dir / "desk.pptx").read_bytes())
        manifest["checks"]["pdf_exported_match"] = manifest["artifacts"]["pdf"]["downloaded_sha256"] == manifest["artifacts"]["pdf"]["exported_sha256"]
        manifest["checks"]["pptx_exported_match"] = manifest["artifacts"]["pptx"]["downloaded_sha256"] == manifest["artifacts"]["pptx"]["exported_sha256"]
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        log += [f"project_id={project.id}", f"workflow_run_id={run_record.id}", f"report_id={report.id}", f"review_id={approved[0].id}"]
        (output_dir / "execution_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
        (output_dir / "qualification_report.md").write_text("# P8-D Desk canonical evidence\n\nSee `manifest.json`.\n", encoding="utf-8")
        return 0
    except Exception as exc:
        log.append(f"status=BLOCKED: {type(exc).__name__}: {exc}")
        (output_dir / "execution_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
        raise
    finally:
        if container is not None:
            container.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("p8d_canonical_evidence"))
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.output_dir))
    except Exception as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(2)
