"""Idempotent synthetic fixtures for the isolated PRF-07B database only."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from application.composition_root import create_application_container
from application.persistence.exceptions import EntityNotFoundError
from application.security.api_key_format import parse_api_key
from domain.quantitative.report import (
    QuantitativeReport,
    QuantitativeReportCompositionResult,
    QuantitativeReportSection,
    QuantitativeReportSectionType,
    QuantitativeReportValidationStatus,
)
from domain.reports.report import Report
from domain.reports.report_section import ReportSection
from domain.reviews.review_result import ReviewResult
from domain.reviews.review_verdict import ReviewVerdict
from domain.workflow_template import WorkflowTemplate

PROJECT_ID = "prf07b-synthetic-acceptance"
RUN_ID = "prf07b-desk-run"
DESIGN_ID = "prf07b-fictional-design"
APPROVED_ID = "prf07b-desk-revision-1"
DRAFT_ID = "prf07b-desk-revision-2"
QUANT_ID = "prf07b-quant-accepted"


def _require_isolation() -> str:
    url = os.environ.get("DATABASE_URL", "")
    expected = "postgresql+psycopg://prf07b:"
    if not url.startswith(expected) or not url.endswith("@postgres:5432/prf07b_acceptance"):
        raise RuntimeError("PRF-07B seeding refused: database identity is not isolated")
    key = os.environ.get("UI_INTERNAL_API_KEY", "")
    if parse_api_key(key) is None:
        raise RuntimeError("PRF-07B seeding refused: local UI key is absent")
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("SEARCH_API_KEY"):
        raise RuntimeError("PRF-07B seeding refused: external API credentials present")
    return key


def _owner(container, key: str) -> str:
    service = container.authentication_service
    assert service is not None
    key_id, _ = parse_api_key(key)
    record = service._api_key_repository.get_by_id(key_id)
    if record is None:
        service.register_api_key(
            name="prf07b-local-owner",
            key_id=key_id,
            key_prefix=f"airos_{key_id}",
            key_hash=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        )
    return service.authenticate_api_key(key).principal_id


def _desk_report(project_id: str, revision: int) -> Report:
    source_id = APPROVED_ID if revision == 1 else DRAFT_ID
    long_heading = (
        "Довгий синтетичний заголовок для перевірки перенесення тексту "
        "та читабельності української презентації"
    )
    paragraph = (
        "Це вигаданий приклад для візуальної перевірки документа. "
        "Умовний матеріал описує лише припущення тестового сценарію; "
        "він не містить ринкових фактів або порад. "
    )
    long_text = "\n\n".join(
        f"Тестовий абзац {index}. " + paragraph * 6 for index in range(1, 11)
    )
    return Report(
        id=source_id,
        project_id=project_id,
        workflow_run_id=RUN_ID,
        research_design_id=DESIGN_ID,
        title=f"Синтетичний кабінетний звіт — редакція {revision}",
        language="uk",
        sections=(
            ReportSection(
                f"{source_id}-intro",
                "Мета та межі синтетичного прикладу",
                paragraph * 3,
                citation_ids=("fictional-1",),
            ),
            ReportSection(
                f"{source_id}-long",
                long_heading,
                long_text,
                citation_ids=("fictional-1", "fictional-2"),
            ),
            ReportSection(
                f"{source_id}-conclusion",
                "Обережний висновок",
                "У межах вигаданого прикладу можна перевірити лише структуру "
                "та читабельність документа; реальних дослідницьких висновків немає.",
            ),
        ),
        executive_summary="Повністю синтетичний матеріал для перевірки PDF і PPTX.",
        limitations=(
            "Усі джерела, числа і твердження в цьому звіті вигадані.",
            "Матеріал не можна використовувати для бізнес-рішень.",
        ),
        created_at=f"2026-09-{revision:02}T12:00:00+00:00",
        generation_method="prf07b-synthetic-fixture",
        finding_refs=(),
        insight_refs=(),
        evidence_refs=(),
        citation_registry={
            "fictional-1": {
                "title": "Навчальний матеріал А (вигаданий)",
                "canonical_url": "https://prf07b-example.invalid/a",
            },
            "fictional-2": {
                "title": "Навчальний матеріал Б (вигаданий)",
                "canonical_url": "https://prf07b-example.invalid/b",
            },
        },
        revision_number=revision,
        previous_report_id=APPROVED_ID if revision == 2 else None,
        approval_status="draft",
        deduplication_key=source_id,
    )


def seed() -> None:
    key = _require_isolation()
    container = create_application_container()
    try:
        ready, reason = container.check_readiness()
        if not ready:
            raise RuntimeError(f"PRF-07B schema not ready: {reason}")
        owner = _owner(container, key)
        try:
            project = container.project_service.get_project(PROJECT_ID)
        except EntityNotFoundError:
            project = None
        if project is not None:
            if project.owner_principal_id != owner:
                raise RuntimeError("PRF-07B project ownership mismatch")
            catalog = container.project_deliverables_service.catalog(PROJECT_ID, owner_id=owner)
            if len(catalog.desk) != 2 or len(catalog.quantitative) != 1:
                raise RuntimeError("PRF-07B existing fixtures are incomplete; refusing overwrite")
            print("Synthetic acceptance fixtures already present and verified")
            return

        project = container.project_service.create_project(
            "PRF-07B — Синтетична перевірка PDF/PPTX",
            project_id=PROJECT_ID,
            owner_principal_id=owner,
            selected_methods=("DESK", "QUANTITATIVE"),
        )
        template = WorkflowTemplate(id="prf07b-desk-template", name="Synthetic Desk")
        container.workflow_service.publish_template_snapshot(template, project_id=project.id)
        container.workflow_service.create_workflow_run(
            template, project_id=project.id, run_id=RUN_ID
        )
        report_repo = container.report_query_service._report_repository
        for revision in (1, 2):
            report_repo.create(_desk_report(project.id, revision))
        container.review_query_service._review_repository.create(
            ReviewResult(
                id="prf07b-review-approved",
                project_id=project.id,
                workflow_run_id=RUN_ID,
                research_design_id=DESIGN_ID,
                report_id=APPROVED_ID,
                review_attempt=1,
                verdict=ReviewVerdict.APPROVE,
                quality_dimensions=(),
                issues=(),
                summary="Синтетичне схвалення редакції 1 лише для приймального стенда.",
                review_method="prf07b-synthetic-fixture",
                created_at=datetime.now(timezone.utc).isoformat(),
                deduplication_key="prf07b-review-approved",
            )
        )

        study = container.quantitative_ui_service.create_quantitative_study_for_project(
            project_id=project.id,
            owner_id=owner,
            title="Синтетична кількісна студія",
            description="Лише вигадані значення для перевірки документів.",
            submission_key="prf07b-quant-study",
        )
        quant_report = QuantitativeReport(
            report_id=QUANT_ID,
            title="Синтетичний кількісний звіт — прийнято",
            sections=(
                QuantitativeReportSection(
                    section_id="prf07b-quant-kpi",
                    section_type=QuantitativeReportSectionType.KPI_RESULTS,
                    title="Ілюстративний показник і методологічні припущення",
                    narrative=(
                        "Вигаданий приклад: 12 із 40 умовних записів мають тестову ознаку. "
                        "Це не фактична статистика. "
                    ) * 18,
                    referenced_display_values=("12 із 40",),
                    base_definition="40 вигаданих тестових записів",
                    filter_definition="Лише синтетична група А",
                    weighting_status="Зважування не застосовано",
                ),
                QuantitativeReportSection(
                    section_id="prf07b-quant-limits",
                    section_type=QuantitativeReportSectionType.LIMITATIONS,
                    title="Обмеження",
                    narrative="Усі значення вигадані; вибірки респондентів не існує.",
                ),
            ),
            supporting_finding_refs=(),
            supporting_insight_refs=(),
            validation_status=QuantitativeReportValidationStatus.SUPPORTED,
        )
        composition = QuantitativeReportCompositionResult(
            composition_id="prf07b-quant-composition-1",
            input_support_bundle_fingerprint="prf07b-synthetic-bundle",
            generator_identity="prf07b-synthetic-fixture",
            prompt_version="synthetic-v1",
            prompt_fingerprint="prf07b-synthetic-prompt",
            proposed_report=quant_report,
            accepted_report=quant_report,
            rejected_reports=(),
            composition_metadata={"synthetic": True},
            composition_fingerprint="prf07b-synthetic-composition",
        )
        container.quantitative_ui_service.state.persist(
            composition,
            record_id="prf07b-quant-composition-record",
            project_id=project.id,
            run_id=study.run_id,
            accepted=True,
        )
        catalog = container.project_deliverables_service.catalog(project.id, owner_id=owner)
        if (
            len(catalog.desk) != 2
            or len(catalog.quantitative) != 1
            or catalog.latest_created_desk_id != DRAFT_ID
            or catalog.latest_approved_desk_id != APPROVED_ID
        ):
            raise RuntimeError("PRF-07B fixture catalog shape mismatch")
        print("Synthetic acceptance fixtures created and verified")
    finally:
        container.shutdown()


if __name__ == "__main__":
    seed()
