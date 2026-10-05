"""Synthetic, provider-free OPS-01B backup/restore acceptance fixture.

This operator helper is deliberately unavailable as an HTTP endpoint.  It uses
the normal application persistence and deliverable services and refuses any
database other than the disposable OPS-01B source/restore database.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from application.composition_root import create_application_container
from application.identity import ProjectRole
from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.workflow_template import WorkflowTemplate
from infrastructure.quantitative.storage.protected_file_dataset_storage import (
    ProtectedFileDatasetStorage,
)
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


PROJECT_ID = "ops01b-recovery-project"
RUN_ID = "ops01b-recovery-run"
REPORT_ID = "ops01b-approved-report"
REVIEW_ID = "ops01b-approved-review"
RAW_ID = "ops01b-protected-artifact"
RAW_BYTES = b"OPS-01B synthetic protected research artifact\n"
OWNER_EMAIL = "ops01b-owner@example.invalid"
OUTSIDER_EMAIL = "ops01b-outsider@example.invalid"


def _password(name: str) -> str:
    value = os.environ.get(name, "")
    if len(value) < 12:
        raise RuntimeError(f"{name} must satisfy the normal password policy")
    return value


def _require_disposable_database() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if "@postgres:5432/ops01b" not in url:
        raise RuntimeError("OPS-01B fixture refused: database is not disposable")
    if any(os.environ.get(name) for name in ("OPENAI_API_KEY", "SEARCH_API_KEY", "ASSEMBLYAI_API_KEY")):
        raise RuntimeError("OPS-01B fixture refused: provider credentials are present")


def _storage(project_id: str) -> ProtectedFileDatasetStorage:
    root = os.environ.get("QUANTITATIVE_PROTECTED_STORAGE_ROOT", "")
    if not root:
        raise RuntimeError("protected storage root is unavailable")
    return ProtectedFileDatasetStorage(
        root=root,
        project_id=project_id,
        run_id=RUN_ID,
        digest_provider=Sha256DigestProvider(),
    )


def _users(container):
    identity = container.identity_service
    if identity is None:
        raise RuntimeError("identity service is unavailable")
    owner = identity.store.get_user_by_email(OWNER_EMAIL) or identity.create_user(
        OWNER_EMAIL, "OPS-01B Synthetic Owner", _password("OPS01B_OWNER_PASSWORD")
    )
    outsider = identity.store.get_user_by_email(OUTSIDER_EMAIL) or identity.create_user(
        OUTSIDER_EMAIL, "OPS-01B Synthetic Outsider", _password("OPS01B_OUTSIDER_PASSWORD")
    )
    return identity, owner, outsider


def seed() -> None:
    _require_disposable_database()
    container = create_application_container()
    try:
        identity, owner, outsider = _users(container)
        try:
            project = container.project_service.get_project(PROJECT_ID)
        except EntityNotFoundError:
            project = container.project_service.create_project(
                "OPS-01B — Synthetic Disaster Recovery",
                project_id=PROJECT_ID,
                owner_principal_id=owner.id,
                selected_methods=("DESK",),
            )
        if identity.store.get_membership(PROJECT_ID, owner.id) is None:
            identity.add_membership(PROJECT_ID, owner.id, ProjectRole.OWNER, actor_id=owner.id)
        if container.report_query_service._report_repository.get_by_id(REPORT_ID) is None:
            template = WorkflowTemplate(id="ops01b-template", name="OPS-01B Synthetic Desk")
            container.workflow_service.publish_template_snapshot(template, project_id=PROJECT_ID)
            container.workflow_service.create_workflow_run(
                template, project_id=PROJECT_ID, run_id=RUN_ID
            )
            report = Report(
                id=REPORT_ID,
                project_id=PROJECT_ID,
                workflow_run_id=RUN_ID,
                research_design_id="ops01b-design",
                title="Синтетичний звіт для перевірки відновлення",
                language="uk",
                sections=(ReportSection(
                    "ops01b-section",
                    "Перевірка незмінності",
                    "Вигаданий матеріал без реальних учасників або дослідницьких тверджень.",
                ),),
                executive_summary="Лише синтетичний доказ резервного відновлення.",
                limitations=("Не містить реальних даних.",),
                created_at=datetime.now(timezone.utc).isoformat(),
                generation_method="ops01b-synthetic-fixture",
                finding_refs=(), insight_refs=(), evidence_refs=(), citation_registry={},
                revision_number=1,
                approval_status="draft",
                deduplication_key=REPORT_ID,
            )
            container.report_query_service._report_repository.create(report)
            container.review_query_service._review_repository.create(ReviewResult(
                id=REVIEW_ID,
                project_id=PROJECT_ID,
                workflow_run_id=RUN_ID,
                research_design_id="ops01b-design",
                report_id=REPORT_ID,
                review_attempt=1,
                verdict=ReviewVerdict.APPROVE,
                quality_dimensions=(), issues=(),
                summary="Synthetic recovery acceptance approval.",
                review_method="ops01b-synthetic-fixture",
                created_at=datetime.now(timezone.utc).isoformat(),
                deduplication_key=REVIEW_ID,
            ))
        storage = _storage(PROJECT_ID)
        storage.put_raw_file(RAW_ID, RAW_BYTES)
        deliverables = container.project_deliverables_service
        pdf = deliverables.generate(PROJECT_ID, "DESK", REPORT_ID, owner_id=owner.id)
        job = deliverables.schedule_presentation(PROJECT_ID, "DESK", REPORT_ID, owner_id=owner.id)
        print(json.dumps({
            "project_id": PROJECT_ID,
            "owner_id": owner.id,
            "outsider_id": outsider.id,
            "report_id": REPORT_ID,
            "protected_sha256": hashlib.sha256(RAW_BYTES).hexdigest(),
            "pdf_id": pdf.id,
            "pdf_sha256": pdf.checksum,
            "presentation_job_id": job.id,
        }, sort_keys=True))
    finally:
        container.shutdown()


def verify() -> None:
    _require_disposable_database()
    container = create_application_container()
    try:
        identity, owner, outsider = _users(container)
        if identity.authenticate(OWNER_EMAIL, _password("OPS01B_OWNER_PASSWORD")) is None:
            raise RuntimeError("owner login failed")
        membership = identity.require(PROJECT_ID, owner.id)
        if membership.role is not ProjectRole.OWNER:
            raise RuntimeError("owner membership was not restored")
        try:
            identity.require(PROJECT_ID, outsider.id)
        except PermissionError:
            pass
        else:
            raise RuntimeError("outsider unexpectedly gained project access")
        project = container.project_service.get_project(PROJECT_ID)
        activity = container.activity_reader.list_for_project(PROJECT_ID)
        if not activity.events or activity.state != "ready":
            raise RuntimeError("project activity was not restored")
        source = container.project_deliverables_service.source(
            PROJECT_ID, "DESK", REPORT_ID, owner_id=owner.id
        )
        if source.document.status != "Схвалено" or source.pdf is None or source.pptx is None:
            raise RuntimeError("approved authority or immutable deliverables are incomplete")
        _, pdf = container.project_deliverables_service.download(
            PROJECT_ID, "DESK", REPORT_ID, source.pdf.id, owner_id=owner.id
        )
        _, pptx = container.project_deliverables_service.download_presentation(
            PROJECT_ID, "DESK", REPORT_ID, source.pptx.id, owner_id=owner.id
        )
        protected = _storage(PROJECT_ID).get_raw_file(RAW_ID)
        try:
            container.project_deliverables_service.catalog(PROJECT_ID, owner_id=outsider.id)
        except (AccessDeniedError, PermissionError):
            pass
        else:
            raise RuntimeError("outsider unexpectedly accessed deliverables")
        print(json.dumps({
            "project_id": project.id,
            "membership": membership.role.value,
            "approved_report_id": source.document.source_id,
            "activity_events": len(activity.events),
            "protected_sha256": hashlib.sha256(protected).hexdigest(),
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            "pptx_sha256": hashlib.sha256(pptx).hexdigest(),
            "authorization": "owner_allowed_outsider_denied",
        }, sort_keys=True))
    finally:
        container.shutdown()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("Usage: python tools/ops01b_acceptance_fixture.py seed|verify")
    (seed if sys.argv[1] == "seed" else verify)()
