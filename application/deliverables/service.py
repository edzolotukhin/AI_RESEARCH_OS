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
from application.quantitative.workflow import (
    CMF_QUANTITATIVE_WORKFLOW_ID,
    QUANTITATIVE_WORKFLOW_ID,
)
from application.methods.quantitative.pin import REVIEW_PIN
from application.deliverables.quantitative_sources import approved_quantitative_sources
from application.deliverables.desk_finalization import (
    STRUCTURED_REPORT_CONTRACT,
    DeskFinalizationAuthority,
    claim_set_digest,
    coverage_contract_digest,
)
from application.report.source_display import source_display


class DeliverableFinalizationError(RuntimeError):
    def __init__(self, state: str, code: str) -> None:
        super().__init__(code)
        self.state = state
        self.code = code


@dataclass(frozen=True)
class ReportCatalogItem:
    document: PdfSourceDocument
    pdf: PdfDeliverable | None
    presentation_job: PresentationJob | None = None
    pptx: PdfDeliverable | None = None

    @property
    def finalization_state(self) -> str:
        if self.document.method != "DESK" or self.document.status != "Схвалено":
            return "not_applicable"
        if self.pdf is None:
            return "pending"
        if self.presentation_job is None:
            return "pending"
        if self.presentation_job.state in {"failed", "failed_terminal"}:
            return "finalization_failed"
        if self.presentation_job.state in {"review_approved", "pdf_generating", "pdf_complete", "pending", "pptx_pending"}:
            return self.presentation_job.state
        if self.presentation_job.state in {"processing", "pptx_processing"}:
            return "pptx_processing"
        if self.presentation_job.state == "retry_wait":
            return "pptx_retry_wait"
        return "finalization_complete" if self.pptx is not None else "finalization_failed"


@dataclass(frozen=True)
class ReportCatalog:
    desk: tuple[ReportCatalogItem, ...]
    quantitative: tuple[ReportCatalogItem, ...]
    qualitative: tuple[ReportCatalogItem, ...]
    latest_created_desk_id: str | None
    latest_approved_desk_id: str | None


class ProjectDeliverablesService:
    def __init__(self, *, projects, workflows, reports, reviews, quantitative_state,
                 qualitative_reports=None,
                 store, renderer, presentation_jobs=None, pptx_renderer=None,
                 report_claims=None) -> None:
        self.projects = projects
        self.workflows = workflows
        self.reports = reports
        self.reviews = reviews
        self.quantitative_state = quantitative_state
        self.qualitative_reports = qualitative_reports
        self.store = store
        self.renderer = renderer
        self.presentation_jobs = presentation_jobs
        self.pptx_renderer = pptx_renderer
        self.report_claims = report_claims

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

    @staticmethod
    def _approved_desk_review(report, reviews):
        same = [item for item in reviews if item.project_id == report.project_id
                and item.workflow_run_id == report.workflow_run_id
                and item.report_id == report.id
                and item.research_design_id == report.research_design_id]
        if len(same) != 1 or same[0].verdict != ReviewVerdict.APPROVE:
            raise AccessDeniedError("Схвалену ревізію звіту не знайдено")
        return same[0]

    def _desk(self, project_id: str, run_ids: set[str]) -> list[PdfSourceDocument]:
        documents = []
        for report in self.reports.list_reports_for_project(project_id):
            if report.project_id != project_id or report.workflow_run_id not in run_ids:
                continue
            reviews = self.reviews.list_reviews_for_project(
                project_id, workflow_run_id=report.workflow_run_id, report_id=report.id)
            status, review_digest = self._desk_status(report, reviews)
            approved_review = None
            try:
                approved_review = self._approved_desk_review(report, reviews)
            except AccessDeniedError:
                pass
            authority = None
            if approved_review is not None and report.metadata.get("structured_claim_contract") == STRUCTURED_REPORT_CONTRACT:
                try:
                    authority = self._structured_authority(report, approved_review)
                except AccessDeniedError:
                    approved_review = None
                    status = "Статус перевірки не підтверджено"
            source_version = (authority.source_version if authority is not None else
                f"revision-{report.revision_number}-review-{approved_review.id}-{approved_review.verdict.value.lower()}"
                if approved_review is not None else f"revision-{report.revision_number}-review-{review_digest}")
            sections = tuple(PdfSection(item.title, (item.content,), item.citation_ids)
                             for item in report.sections)
            registry = tuple((key, source_display(value))
                             for key, value in sorted(report.citation_registry.items()))
            links = tuple(str(value.get("canonical_url")) for value in report.citation_registry.values()
                          if isinstance(value, dict) and isinstance(value.get("canonical_url"), str))
            documents.append(PdfSourceDocument(
                project_id=project_id, method="DESK", run_id=report.workflow_run_id,
                study_id=None, source_id=report.id,
                source_version=source_version,
                status=status, title=report.title, summary=report.executive_summary,
                sections=sections, limitations=report.limitations,
                citation_registry=registry, created_at=report.created_at,
                links=links,
                revision_number=report.revision_number,
                previous_report_id=report.previous_report_id,
                approval_review_id=approved_review.id if approved_review else None,
                approval_decision=(approved_review.verdict.value if approved_review else None),
                source_run_id=(authority.source_run_id if authority else report.workflow_run_id),
                claim_set_digest=(authority.claim_set_digest if authority else None),
                coverage_contract_digest=(authority.coverage_contract_digest if authority else None),
            ))
        return sorted(documents, key=lambda item: (item.created_at or "", item.revision_number or 0, item.source_id), reverse=True)

    def _quantitative(self, project_id: str, run_ids: set[str]) -> list[PdfSourceDocument]:
        if self.quantitative_state is None:
            return []
        documents = []
        for run_id in sorted(run_ids):
            task_results = self.workflows.get_task_results(run_id)
            if task_results.get(REVIEW_PIN) is not None:
                documents.extend(approved_quantitative_sources(
                    state=self.quantitative_state, project_id=project_id, run_id=run_id))
                continue
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
        quant_templates = {QUANTITATIVE_WORKFLOW_ID, CMF_QUANTITATIVE_WORKFLOW_ID}
        desk_runs: set[str] = set()
        quant_runs: set[str] = set()
        qual_runs: set[str] = set()
        from application.qualitative.service import QUAL_TEMPLATE
        for run in self.workflows.list_workflow_runs_for_project(project_id):
            if run.project_id != project_id:
                raise AccessDeniedError("Проєкт не знайдено")
            (quant_runs if run.workflow_template_id in quant_templates else
             qual_runs if run.workflow_template_id == QUAL_TEMPLATE else desk_runs).add(run.id)
        from application.methods.versioning import resolve_pin
        from application.methods.desk.profile import PIN
        desk = []
        legacy_runs = set()
        for run_id in sorted(desk_runs):
            method = resolve_pin(self.workflows.get_task_results(run_id).get(PIN))
            if method is None:
                legacy_runs.add(run_id)
            else:
                desk.extend(method.report_sources(project_id, {run_id}, self._desk))
        desk.extend(self._desk(project_id, legacy_runs))
        desk.sort(key=lambda item: (item.created_at or "", item.revision_number or 0, item.source_id), reverse=True)
        quant = self._quantitative(project_id, quant_runs)
        qual = self.qualitative_reports.documents(project_id, qual_runs) if self.qualitative_reports else []

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
                if job is not None and job.state in {"completed", "finalization_complete"}:
                    pptx = self.store.find(
                        project_id=project_id, method=document.method,
                        source_id=document.source_id, source_version=document.source_version,
                        renderer_version=self.pptx_renderer.version,
                        format="PPTX", template_version=self.pptx_renderer.template_version)
            return ReportCatalogItem(document, pdf, job, pptx)

        return ReportCatalog(tuple(map(item, desk)), tuple(map(item, quant)), tuple(map(item, qual)),
                             desk[0].source_id if desk else None,
                             next((doc.source_id for doc in desk if doc.status == "Схвалено"), None))

    def source(self, project_id: str, method: str, source_id: str, *, owner_id: str) -> ReportCatalogItem:
        catalog = self.catalog(project_id, owner_id=owner_id)
        group = (catalog.desk if method == "DESK" else catalog.quantitative if method == "QUANTITATIVE"
                 else catalog.qualitative if method == "QUALITATIVE" else ())
        matches = [item for item in group if item.document.source_id == source_id]
        if len(matches) != 1:
            raise AccessDeniedError("Звіт не знайдено")
        return matches[0]

    def _approved_desk_item(self, item: ReportCatalogItem) -> ReportCatalogItem:
        document = item.document
        if (document.method == "DESK" and
                (document.status != "Схвалено" or not document.approval_review_id
                 or document.approval_decision != ReviewVerdict.APPROVE.value)):
            raise AccessDeniedError("Схвалену ревізію звіту не знайдено")
        return item

    def _structured_authority(self, report, review) -> DeskFinalizationAuthority:
        if self.report_claims is None or report.metadata.get("structured_claim_contract") != STRUCTURED_REPORT_CONTRACT:
            raise AccessDeniedError("Structured Report authority unavailable")
        if review.verdict is not ReviewVerdict.APPROVE or review.metadata.get("structured_claim_contract") != STRUCTURED_REPORT_CONTRACT:
            raise AccessDeniedError("Exact structured approval unavailable")
        if int(review.metadata.get("report_revision", 0)) != report.revision_number:
            raise AccessDeniedError("Approval targets another revision")
        claims = tuple(self.report_claims.list_for_report(report.id, report.revision_number))
        if not claims:
            raise AccessDeniedError("Structured Report has no immutable claims")
        task_results = self.workflows.get_task_results(report.workflow_run_id)
        from application.replay.desk_downstream_replay import REPLAY_KEY
        replay = task_results.get(REPLAY_KEY)
        source_run = (replay.get("source_workflow_run_id") if isinstance(replay, dict)
                      else report.workflow_run_id)
        if not isinstance(source_run, str) or any(
            (claim.project_id, claim.report_workflow_run_id, claim.source_workflow_run_id,
             claim.design_id) !=
            (report.project_id, report.workflow_run_id, source_run, report.research_design_id)
            for claim in claims
        ):
            raise AccessDeniedError("Structured claim lineage mismatch")
        digest = claim_set_digest(claims)
        coverage_digest = coverage_contract_digest(report)
        if review.metadata.get("claim_set_digest") != digest:
            raise AccessDeniedError("Approved claim digest mismatch")
        if review.metadata.get("coverage_contract_digest") != coverage_digest:
            raise AccessDeniedError("Approved coverage contract mismatch")
        later = [item for item in self.reports.list_reports_for_project(report.project_id)
                 if item.workflow_run_id == report.workflow_run_id
                 and item.revision_number > report.revision_number]
        if later:
            raise AccessDeniedError("Approved revision was superseded")
        return DeskFinalizationAuthority(
            project_id=report.project_id, report_run_id=report.workflow_run_id,
            source_run_id=source_run, design_id=report.research_design_id,
            report_id=report.id, report_revision=report.revision_number,
            review_id=review.id, claim_set_digest=digest,
            coverage_contract_digest=coverage_digest,
        )

    def generate(self, project_id: str, method: str, source_id: str, *, owner_id: str) -> PdfDeliverable:
        item = self._approved_desk_item(self.source(project_id, method, source_id, owner_id=owner_id))
        return self._generate_item(item)

    def _generate_item(self, item: ReportCatalogItem) -> PdfDeliverable:
        if item.pdf is not None:
            return item.pdf
        document = item.document
        data = self.renderer.render(document)
        if not data.startswith(b"%PDF-") or not 0 < len(data) <= 5_000_000:
            raise ValueError("PDF не вдалося створити в допустимому розмірі")
        checksum = hashlib.sha256(data).hexdigest()
        identifier = str(uuid4())
        record = PdfDeliverable(
            id=identifier, project_id=document.project_id, method=document.method, run_id=document.run_id,
            study_id=document.study_id, source_id=document.source_id, source_version=document.source_version,
            status_snapshot=document.status, renderer_version=RENDERER_VERSION,
            created_at=datetime.now(timezone.utc), storage_key=identifier,
            checksum=checksum, byte_size=len(data),
            filename=f"research-{document.method.lower()}-{identifier}.pdf",
        )
        return self.store.complete(record, data)

    def download(self, project_id: str, method: str, source_id: str,
                 deliverable_id: str, *, owner_id: str) -> tuple[PdfDeliverable, bytes]:
        item = self._approved_desk_item(self.source(project_id, method, source_id, owner_id=owner_id))
        stored = self.store.get(deliverable_id)
        if stored is None:
            raise AccessDeniedError("PDF не знайдено")
        record, data = stored
        document = item.document
        if (record.project_id, record.method, record.run_id, record.study_id,
            record.source_id) != (
            project_id, method, document.run_id, document.study_id,
            source_id):
            raise AccessDeniedError("PDF не знайдено")
        if record.renderer_version not in {RENDERER_VERSION, "prf06e-reportlab-1"}:
            raise AccessDeniedError("PDF не знайдено")
        if method in {"QUANTITATIVE", "QUALITATIVE"} and record.source_version != document.source_version:
            raise AccessDeniedError("PDF не знайдено")
        if method == "DESK" and record.source_version != document.source_version:
            raise AccessDeniedError("PDF не знайдено")
        if len(data) != record.byte_size or hashlib.sha256(data).hexdigest() != record.checksum:
            raise AccessDeniedError("PDF не знайдено")
        return record, data

    def schedule_presentation(self, project_id: str, method: str, source_id: str,
                              *, owner_id: str) -> PresentationJob:
        if self.presentation_jobs is None or self.pptx_renderer is None:
            raise ValueError("Створення презентації недоступне")
        item = self._approved_desk_item(self.source(project_id, method, source_id, owner_id=owner_id))
        return self._schedule_presentation_document(item.document)

    def _schedule_presentation_document(self, document: PdfSourceDocument,
                                        authority: DeskFinalizationAuthority | None = None) -> PresentationJob:
        job = self.presentation_jobs.schedule(
            project_id=document.project_id, method=document.method, run_id=document.run_id,
            study_id=document.study_id, source_id=document.source_id,
            source_version=document.source_version, status_snapshot=document.status,
            template_version=self.pptx_renderer.template_version,
            renderer_version=self.pptx_renderer.version,
            **({"initial_state": "review_approved", "report_revision": authority.report_revision,
                "review_id": authority.review_id, "source_run_id": authority.source_run_id,
                "claim_set_digest": authority.claim_set_digest,
                "coverage_contract_digest": authority.coverage_contract_digest}
               if authority is not None else {}))
        if job.state in {"failed", "retry_wait"}:
            return self.presentation_jobs.retry(job.id) or job
        return job

    def finalize_approved_review(self, *, project_id: str, report_id: str,
                                 review_id: str) -> dict[str, str]:
        try:
            reports = [item for item in self.reports.list_reports_for_project(project_id)
                       if item.id == report_id and item.project_id == project_id]
            if len(reports) != 1:
                raise AccessDeniedError("not approved")
            report = reports[0]
            reviews = self.reviews.list_reviews_for_project(
                project_id, workflow_run_id=report.workflow_run_id, report_id=report.id)
            review = self._approved_desk_review(report, reviews)
            if review.id != review_id:
                raise AccessDeniedError("not approved")
            authority = self._structured_authority(report, review)
            project = self.projects.get_project(project_id)
            item = self._approved_desk_item(self.source(
                project_id, "DESK", report_id, owner_id=project.owner_principal_id))
            if (item.document.source_version != authority.source_version
                    or item.document.claim_set_digest != authority.claim_set_digest
                    or item.document.coverage_contract_digest != authority.coverage_contract_digest
                    or item.document.source_run_id != authority.source_run_id):
                raise AccessDeniedError("Structured finalization provenance mismatch")
        except Exception as exc:
            raise DeliverableFinalizationError("approval_gate_rejected", "approval_gate_rejected") from exc
        try:
            job = self._schedule_presentation_document(item.document, authority)
        except Exception as exc:
            raise DeliverableFinalizationError(
                "finalization_failed", "pptx_schedule_failed"
            ) from exc
        try:
            if hasattr(self.presentation_jobs, "transition"):
                self.presentation_jobs.transition(job.id, expected=("review_approved",), state="pdf_generating")
            pdf = self._generate_item(item)
            if hasattr(self.presentation_jobs, "transition"):
                self.presentation_jobs.transition(job.id, expected=("pdf_generating", "review_approved"), state="pdf_complete")
                job = self.presentation_jobs.transition(job.id, expected=("pdf_complete",), state="pptx_pending") or job
        except Exception as exc:
            if hasattr(self.presentation_jobs, "transition"):
                self.presentation_jobs.transition(
                    job.id,
                    expected=("review_approved", "pdf_generating"),
                    state="failed_terminal",
                    failure_code="pdf_generation_failed",
                )
            raise DeliverableFinalizationError(
                "finalization_failed", "pdf_generation_failed"
            ) from exc
        if job.state in {"completed", "finalization_complete"}:
            refreshed = self._approved_desk_item(self.source(
                project_id, "DESK", report_id, owner_id=project.owner_principal_id))
            if refreshed.pptx is None:
                raise DeliverableFinalizationError(
                    "pptx_failed", "pptx_provenance_or_checksum_missing")
        return {
            "status": "finalization_complete" if job.state in {"completed", "finalization_complete"} else
                      "finalization_failed" if job.state in {"failed", "failed_terminal"} else
                      "pptx_retry_wait" if job.state == "retry_wait" else
                      "pptx_processing" if job.state in {"processing", "pptx_processing"} else "pptx_pending",
            "report_id": report.id,
            "report_revision": str(report.revision_number),
            "review_id": review.id,
            "review_decision": review.verdict.value,
            "pdf_id": pdf.id,
            "pptx_job_id": job.id,
            "claim_set_digest": authority.claim_set_digest,
            "coverage_contract_digest": authority.coverage_contract_digest,
            "source_run_id": authority.source_run_id,
        }

    def process_next_presentation(self, worker_id: str) -> bool:
        if self.presentation_jobs is None or self.pptx_renderer is None:
            return False
        job = self.presentation_jobs.claim_next(worker_id)
        if job is None:
            return False
        try:
            project = self.projects.get_project(job.project_id)
            source_item = self._approved_desk_item(self.source(
                job.project_id, job.method, job.source_id,
                owner_id=project.owner_principal_id))
            document = source_item.document
            if (document.run_id, document.study_id, document.source_version,
                document.status) != (job.run_id, job.study_id, job.source_version,
                                     job.status_snapshot):
                raise ValueError("source identity changed")
            if job.report_revision is not None:
                if (document.revision_number, document.approval_review_id,
                    document.source_run_id, document.claim_set_digest,
                    document.coverage_contract_digest) != (
                    job.report_revision, job.review_id, job.source_run_id,
                    job.claim_set_digest, job.coverage_contract_digest):
                    raise ValueError("structured finalization authority changed")
                self._generate_item(source_item)
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
        refreshed = self.presentation_jobs.find(
            project_id=job.project_id, method=job.method, source_id=job.source_id,
            source_version=job.source_version, template_version=job.template_version,
            renderer_version=job.renderer_version)
        if refreshed is not None and refreshed.report_revision is not None:
            self._settle_structured_workflow(refreshed)
        return True

    def _settle_structured_workflow(self, job: PresentationJob) -> None:
        """Complete/fail the paused Review boundary only at durable finalization terminality."""
        if (self.workflows is None or not hasattr(self.workflows, "get_workflow_run")
                or job.state not in {"finalization_complete", "failed_terminal"}):
            return
        from domain.value_objects.task_status import TaskStatus
        from domain.workflow_status import WorkflowStatus
        run = self.workflows.get_workflow_run(job.run_id)
        if run.status is not WorkflowStatus.PAUSED:
            return
        paused = [task for task in run.tasks if task.status is TaskStatus.PAUSED]
        if len(paused) != 1 or paused[0].executor_id not in {"finalization", "review"}:
            return
        version = self.workflows.get_workflow_run_version(run.id)
        results = self.workflows.get_task_results(run.id)
        state = dict(results.get("desk_deliverable_finalization") or {})
        state.update({
            "status": job.state,
            "pptx_job_id": job.id,
            "pptx_id": job.completed_deliverable_id,
            "attempts": job.attempts,
            "failure_code": job.failure_code,
        })
        results["desk_deliverable_finalization"] = state
        from application.replay.desk_downstream_replay import REPLAY_KEY
        replay = results.get(REPLAY_KEY)
        if isinstance(replay, dict):
            replay = dict(replay)
            stages = dict(replay.get("downstream_stages") or {})
            stages["deliverables"] = ("completed" if job.state == "finalization_complete" else "failed")
            replay["downstream_stages"] = stages
            replay["status"] = ("completed" if job.state == "finalization_complete" else "failed")
            if job.failure_code:
                replay["failure_code"] = job.failure_code
            results[REPLAY_KEY] = replay
        task = paused[0]
        task.resume()
        run.resume()
        if job.state == "finalization_complete":
            task.complete()
            run.complete()
        else:
            task.fail()
            run.fail()
        self.workflows.save_workflow_run(run, expected_version=version, task_results=results)

    def download_presentation(self, project_id: str, method: str, source_id: str,
                              deliverable_id: str, *, owner_id: str) -> tuple[PdfDeliverable, bytes]:
        if self.pptx_renderer is None or self.presentation_jobs is None:
            raise AccessDeniedError("Презентацію не знайдено")
        document = self._approved_desk_item(self.source(
            project_id, method, source_id, owner_id=owner_id)).document
        stored = self.store.get(deliverable_id)
        if stored is None:
            raise AccessDeniedError("Презентацію не знайдено")
        record, data = stored
        job = self.presentation_jobs.find(
            project_id=project_id, method=method, source_id=source_id,
            source_version=record.source_version,
            template_version=record.template_version,
            renderer_version=record.renderer_version)
        if (job is None or job.state not in {"completed", "finalization_complete"}
                or job.completed_deliverable_id != deliverable_id):
            raise AccessDeniedError("Презентацію не знайдено")
        if (record.project_id, record.method, record.run_id, record.study_id,
            record.source_id, record.format, record.media_type) != (
            project_id, method, document.run_id, document.study_id, source_id,
            "PPTX", self.pptx_renderer.media_type):
            raise AccessDeniedError("Презентацію не знайдено")
        if record.source_version != document.source_version:
            raise AccessDeniedError("Презентацію не знайдено")
        if len(data) != record.byte_size or hashlib.sha256(data).hexdigest() != record.checksum:
            raise AccessDeniedError("Презентацію не знайдено")
        return record, data
