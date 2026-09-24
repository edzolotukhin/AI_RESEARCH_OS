"""Authorize exact saved reports before catalog, generation, and download."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from application.deliverables.contracts import PdfDeliverable, PdfSection, PdfSourceDocument, RENDERER_VERSION
from application.deliverables.presentation_jobs import PresentationJob
from application.persistence.exceptions import AccessDeniedError, EntityNotFoundError
from domain.quantitative.report import QuantitativeReportCompositionResult, QuantitativeReportValidationStatus
from domain.quantitative.workflow import QuantitativeStudyProjection
from domain.reviews.review_verdict import ReviewVerdict
from application.quantitative.workflow import build_quantitative_workflow_template


@dataclass(frozen=True)
class ReportCatalogItem:
    document: PdfSourceDocument
    pdf: PdfDeliverable | None
    presentation_job: PresentationJob | None = None
    pptx: PdfDeliverable | None = None


@dataclass(frozen=True)
class ReportCatalog:
    desk: tuple[ReportCatalogItem, ...]
    quantitative: tuple[ReportCatalogItem, ...]
    latest_created_desk_id: str | None
    latest_approved_desk_id: str | None


class ProjectDeliverablesService:
    def __init__(self, *, projects, workflows, reports, reviews, quantitative_state,
                 store, renderer, presentation_jobs=None, pptx_renderer=None) -> None:
        self.projects = projects
        self.workflows = workflows
        self.reports = reports
        self.reviews = reviews
        self.quantitative_state = quantitative_state
        self.store = store
        self.renderer = renderer
        self.presentation_jobs = presentation_jobs
        self.pptx_renderer = pptx_renderer

    def _project(self, project_id: str, owner_id: str):
        try:
            project = self.projects.get_project(project_id)
        except EntityNotFoundError as exc:
            raise AccessDeniedError("Проєкт не знайдено") from exc
        if project.owner_principal_id != owner_id:
            raise AccessDeniedError("Проєкт не знайдено")
        return project

    @staticmethod
    def _desk_status(report, reviews) -> tuple[str, str]:
        same = [item for item in reviews if item.project_id == report.project_id
                and item.workflow_run_id == report.workflow_run_id and item.report_id == report.id
                and item.research_design_id == report.research_design_id]
        verdicts = {item.verdict for item in same}
        digest = hashlib.sha256("|".join(sorted(f"{item.id}:{item.verdict.value}" for item in same)).encode()).hexdigest()[:16]
        if not same:
            return ("Статус перевірки не підтверджено" if report.approval_status == "approved"
                    else "Чернетка"), digest
        if len(same) == 1 and verdicts == {ReviewVerdict.APPROVE}:
            return "Схвалено", digest
        if len(same) > 1 or len(verdicts) > 1 or report.approval_status == "approved":
            return "Статус перевірки не підтверджено", digest
        return "Потребує доопрацювання", digest

    def _desk(self, project_id: str, run_ids: set[str]) -> list[PdfSourceDocument]:
        documents = []
        for report in self.reports.list_reports_for_project(project_id):
            if report.project_id != project_id or report.workflow_run_id not in run_ids:
                continue
            reviews = self.reviews.list_reviews_for_project(
                project_id, workflow_run_id=report.workflow_run_id, report_id=report.id)
            status, review_digest = self._desk_status(report, reviews)
            sections = tuple(PdfSection(item.title, (item.content,), item.citation_ids)
                             for item in report.sections)
            registry = tuple((key, str(value)) for key, value in sorted(report.citation_registry.items()))
            links = tuple(str(value.get("canonical_url")) for value in report.citation_registry.values()
                          if isinstance(value, dict) and isinstance(value.get("canonical_url"), str))
            documents.append(PdfSourceDocument(
                project_id=project_id, method="DESK", run_id=report.workflow_run_id,
                study_id=None, source_id=report.id,
                source_version=f"revision-{report.revision_number}-review-{review_digest}",
                status=status, title=report.title, summary=report.executive_summary,
                sections=sections, limitations=report.limitations,
                citation_registry=registry, created_at=report.created_at,
                links=links,
                revision_number=report.revision_number,
                previous_report_id=report.previous_report_id,
            ))
        return sorted(documents, key=lambda item: (item.created_at or "", item.revision_number or 0, item.source_id), reverse=True)

    def _quantitative(self, project_id: str, run_ids: set[str]) -> list[PdfSourceDocument]:
        if self.quantitative_state is None:
            return []
        documents = []
        for run_id in sorted(run_ids):
            projections = self.quantitative_state.list_for_run(
                run_id, project_id=project_id, expected_type=QuantitativeStudyProjection)
            projections = tuple(item for item in projections if item.run_id == run_id and item.project_id == project_id)
            if not projections:
                continue
            study = max(projections, key=lambda item: (item.revision, item.study_id))
            compositions = self.quantitative_state.list_for_run(
                run_id, project_id=project_id, expected_type=QuantitativeReportCompositionResult)
            for item in compositions:
                report = item.accepted_report
                if report is None or report.validation_status != QuantitativeReportValidationStatus.SUPPORTED:
                    continue
                sections = tuple(PdfSection(
                    section.title,
                    tuple(value for value in (
                        section.narrative,
                        *(claim.text for claim in section.claim_units),
                        *(f"Збережене значення твердження: {value}"
                          for claim in section.claim_units for value in claim.referenced_display_values),
                        *(f"Збережене значення: {value}" for value in section.referenced_display_values),
                        f"База: {section.base_definition}" if section.base_definition else "",
                        f"Фільтр: {section.filter_definition}" if section.filter_definition else "",
                        f"Зважування: {section.weighting_status}" if section.weighting_status else "",
                        f"Напрям: {section.direction}" if section.direction else "",
                        *(f"Посилання на результат: {value}" for value in section.authoritative_result_refs),
                        *(f"Посилання на таблицю: {value}" for value in section.authoritative_table_refs),
                    ) if value),
                ) for section in report.sections)
                documents.append(PdfSourceDocument(
                    project_id=project_id, method="QUANTITATIVE", run_id=run_id,
                    study_id=study.study_id, source_id=report.report_id,
                    source_version=item.composition_id, status="Прийнято",
                    title=report.title, summary=None, sections=sections,
                    limitations=tuple(section.narrative for section in report.sections
                                      if section.section_type.value == "LIMITATIONS"),
                    unavailable=("Окремі таблиці та статистичні записи не додано: зв’язок із цим збереженим звітом не підтверджено.",),
                ))
        return sorted(documents, key=lambda item: (item.run_id, item.source_version, item.source_id))

    def catalog(self, project_id: str, *, owner_id: str) -> ReportCatalog:
        self._project(project_id, owner_id)
        quant_template = build_quantitative_workflow_template().id
        desk_runs: set[str] = set()
        quant_runs: set[str] = set()
        for run in self.workflows.list_workflow_runs_for_project(project_id):
            if run.project_id != project_id:
                raise AccessDeniedError("Проєкт не знайдено")
            (quant_runs if run.workflow_template_id == quant_template else desk_runs).add(run.id)
        desk = self._desk(project_id, desk_runs)
        quant = self._quantitative(project_id, quant_runs)

        def item(document):
            pdf = self.store.find(project_id=project_id, method=document.method,
                                  source_id=document.source_id, source_version=document.source_version,
                                  renderer_version=RENDERER_VERSION)
            job = None
            pptx = None
            if self.presentation_jobs is not None and self.pptx_renderer is not None:
                job = self.presentation_jobs.find(
                    project_id=project_id, method=document.method,
                    source_id=document.source_id, source_version=document.source_version,
                    template_version=self.pptx_renderer.template_version,
                    renderer_version=self.pptx_renderer.version)
                if job is not None and job.state == "completed":
                    pptx = self.store.find(
                        project_id=project_id, method=document.method,
                        source_id=document.source_id, source_version=document.source_version,
                        renderer_version=self.pptx_renderer.version,
                        format="PPTX", template_version=self.pptx_renderer.template_version)
            return ReportCatalogItem(document, pdf, job, pptx)

        return ReportCatalog(tuple(map(item, desk)), tuple(map(item, quant)),
                             desk[0].source_id if desk else None,
                             next((doc.source_id for doc in desk if doc.status == "Схвалено"), None))

    def source(self, project_id: str, method: str, source_id: str, *, owner_id: str) -> ReportCatalogItem:
        catalog = self.catalog(project_id, owner_id=owner_id)
        group = catalog.desk if method == "DESK" else catalog.quantitative if method == "QUANTITATIVE" else ()
        matches = [item for item in group if item.document.source_id == source_id]
        if len(matches) != 1:
            raise AccessDeniedError("Звіт не знайдено")
        return matches[0]

    def generate(self, project_id: str, method: str, source_id: str, *, owner_id: str) -> PdfDeliverable:
        item = self.source(project_id, method, source_id, owner_id=owner_id)
        if item.pdf is not None:
            return item.pdf
        document = item.document
        data = self.renderer.render(document)
        if not data.startswith(b"%PDF-") or not 0 < len(data) <= 5_000_000:
            raise ValueError("PDF не вдалося створити в допустимому розмірі")
        checksum = hashlib.sha256(data).hexdigest()
        identifier = str(uuid4())
        record = PdfDeliverable(
            id=identifier, project_id=project_id, method=method, run_id=document.run_id,
            study_id=document.study_id, source_id=source_id, source_version=document.source_version,
            status_snapshot=document.status, renderer_version=RENDERER_VERSION,
            created_at=datetime.now(timezone.utc), storage_key=identifier,
            checksum=checksum, byte_size=len(data),
            filename=f"research-{method.lower()}-{identifier}.pdf",
        )
        return self.store.complete(record, data)

    def download(self, project_id: str, method: str, source_id: str,
                 deliverable_id: str, *, owner_id: str) -> tuple[PdfDeliverable, bytes]:
        item = self.source(project_id, method, source_id, owner_id=owner_id)
        stored = self.store.get(deliverable_id)
        if stored is None:
            raise AccessDeniedError("PDF не знайдено")
        record, data = stored
        document = item.document
        if (record.project_id, record.method, record.run_id, record.study_id,
            record.source_id, record.renderer_version) != (
            project_id, method, document.run_id, document.study_id,
            source_id, RENDERER_VERSION):
            raise AccessDeniedError("PDF не знайдено")
        if method == "QUANTITATIVE" and record.source_version != document.source_version:
            raise AccessDeniedError("PDF не знайдено")
        if method == "DESK" and not record.source_version.startswith(
            f"revision-{document.revision_number}-review-"):
            raise AccessDeniedError("PDF не знайдено")
        if len(data) != record.byte_size or hashlib.sha256(data).hexdigest() != record.checksum:
            raise AccessDeniedError("PDF не знайдено")
        return record, data

    def schedule_presentation(self, project_id: str, method: str, source_id: str,
                              *, owner_id: str) -> PresentationJob:
        if self.presentation_jobs is None or self.pptx_renderer is None:
            raise ValueError("Створення презентації недоступне")
        document = self.source(project_id, method, source_id, owner_id=owner_id).document
        job = self.presentation_jobs.schedule(
            project_id=project_id, method=method, run_id=document.run_id,
            study_id=document.study_id, source_id=source_id,
            source_version=document.source_version, status_snapshot=document.status,
            template_version=self.pptx_renderer.template_version,
            renderer_version=self.pptx_renderer.version)
        if job.state == "failed":
            return self.presentation_jobs.retry(job.id) or job
        return job

    def process_next_presentation(self, worker_id: str) -> bool:
        if self.presentation_jobs is None or self.pptx_renderer is None:
            return False
        job = self.presentation_jobs.claim_next(worker_id)
        if job is None:
            return False
        try:
            project = self.projects.get_project(job.project_id)
            document = self.source(job.project_id, job.method, job.source_id,
                                   owner_id=project.owner_principal_id).document
            if (document.run_id, document.study_id, document.source_version,
                document.status) != (job.run_id, job.study_id, job.source_version,
                                     job.status_snapshot):
                raise ValueError("source identity changed")
            existing = self.store.find(
                project_id=job.project_id, method=job.method, source_id=job.source_id,
                source_version=job.source_version, renderer_version=job.renderer_version,
                format="PPTX", template_version=job.template_version)
            if existing is None:
                data = self.pptx_renderer.render(document)
                identifier = str(uuid4())
                record = PdfDeliverable(
                    id=identifier, project_id=job.project_id, method=job.method,
                    run_id=job.run_id, study_id=job.study_id, source_id=job.source_id,
                    source_version=job.source_version, status_snapshot=job.status_snapshot,
                    renderer_version=job.renderer_version, created_at=datetime.now(timezone.utc),
                    storage_key=identifier, checksum=hashlib.sha256(data).hexdigest(),
                    byte_size=len(data), filename=f"research-{job.method.lower()}-{identifier}.pptx",
                    media_type=self.pptx_renderer.media_type, format="PPTX",
                    template_version=job.template_version,
                )
                existing = self.store.complete(record, data)
            self.presentation_jobs.complete(job.id, worker_id, existing.id)
        except Exception:
            # The failure code is deliberately content-free; the user may retry.
            self.presentation_jobs.fail(job.id, worker_id, "generation_failed")
        return True

    def download_presentation(self, project_id: str, method: str, source_id: str,
                              deliverable_id: str, *, owner_id: str) -> tuple[PdfDeliverable, bytes]:
        if self.pptx_renderer is None or self.presentation_jobs is None:
            raise AccessDeniedError("Презентацію не знайдено")
        document = self.source(project_id, method, source_id, owner_id=owner_id).document
        stored = self.store.get(deliverable_id)
        if stored is None:
            raise AccessDeniedError("Презентацію не знайдено")
        record, data = stored
        job = self.presentation_jobs.find(
            project_id=project_id, method=method, source_id=source_id,
            source_version=record.source_version,
            template_version=record.template_version,
            renderer_version=record.renderer_version)
        if job is None or job.state != "completed" or job.completed_deliverable_id != deliverable_id:
            raise AccessDeniedError("Презентацію не знайдено")
        if (record.project_id, record.method, record.run_id, record.study_id,
            record.source_id, record.format, record.media_type) != (
            project_id, method, document.run_id, document.study_id, source_id,
            "PPTX", self.pptx_renderer.media_type):
            raise AccessDeniedError("Презентацію не знайдено")
        if (method == "QUANTITATIVE" and record.source_version != document.source_version) or (
            method == "DESK" and not record.source_version.startswith(
                f"revision-{document.revision_number}-review-")):
            raise AccessDeniedError("Презентацію не знайдено")
        if len(data) != record.byte_size or hashlib.sha256(data).hexdigest() != record.checksum:
            raise AccessDeniedError("Презентацію не знайдено")
        return record, data
