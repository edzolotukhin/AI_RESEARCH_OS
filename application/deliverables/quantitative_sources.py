"""Read-only projection of approved Quant revisions into deliverable sources."""

from __future__ import annotations

from application.deliverables.contracts import PdfSection, PdfSourceDocument, PdfTable
from application.quantitative.state_persistence import QuantitativePersistenceError
from domain.quantitative.analysis import StatisticalResult
from domain.quantitative.dataset import DatasetVersion
from domain.quantitative.finding import QuantitativeFindingGenerationResult
from domain.quantitative.insight import QuantitativeInsightGenerationResult
from domain.quantitative.report import (
    QuantitativeReportCompositionResult,
    QuantitativeReportValidationStatus,
)
from domain.quantitative.review import QuantitativeApprovedRevision, QuantitativeReview
from domain.quantitative.workflow import QuantitativeAnalysisManifest, QuantitativeStudyProjection
from domain.reviews.review_verdict import ReviewVerdict


class QuantitativeDeliverableSourceError(ValueError):
    """The approved Quant source chain is incomplete, stale, or inconsistent."""


def approved_quantitative_sources(*, state, project_id: str, run_id: str) -> list[PdfSourceDocument]:
    """Return exact QNT-04 approved revisions, failing closed on broken authority."""
    revisions = state.list_for_run(
        run_id, project_id=project_id, expected_type=QuantitativeApprovedRevision)
    if not revisions:
        return []
    projections = state.list_for_run(
        run_id, project_id=project_id, expected_type=QuantitativeStudyProjection)
    projections = tuple(item for item in projections
                        if item.run_id == run_id and item.project_id == project_id)
    if not projections:
        raise QuantitativeDeliverableSourceError("approved Quant source has no study projection")
    study = max(projections, key=lambda item: (item.revision, item.study_id))
    return [_document(state=state, project_id=project_id, run_id=run_id,
                      study_id=study.study_id, revision=revision)
            for revision in revisions]


def _load(state, record_id, *, project_id, run_id, expected_type):
    try:
        state.require_record_scope(record_id, project_id=project_id, run_id=run_id)
        return state.load(record_id, project_id=project_id, expected_type=expected_type)
    except QuantitativePersistenceError as exc:
        raise QuantitativeDeliverableSourceError("approved Quant source authority is unavailable") from exc


def _document(*, state, project_id, run_id, study_id, revision):
    if (revision.project_id, revision.run_id, revision.method_version) != (
            project_id, run_id, "QUANTITATIVE/1"):
        raise QuantitativeDeliverableSourceError("approved Quant revision scope is inconsistent")
    review = _load(state, revision.review_id, project_id=project_id, run_id=run_id,
                   expected_type=QuantitativeReview)
    pairs = (
        (review.review_id, revision.review_id),
        (review.fingerprint, revision.review_fingerprint),
        (review.dataset_record_id, revision.dataset_record_id),
        (review.dataset_fingerprint, revision.dataset_fingerprint),
        (review.analysis_manifest_record_id, revision.analysis_manifest_record_id),
        (review.analysis_manifest_fingerprint, revision.analysis_manifest_fingerprint),
        (review.finding_generation_record_id, revision.finding_generation_record_id),
        (review.finding_generation_fingerprint, revision.finding_generation_fingerprint),
        (review.insight_generation_record_id, revision.insight_generation_record_id),
        (review.insight_generation_fingerprint, revision.insight_generation_fingerprint),
        (review.analysis_plan_fingerprint, revision.analysis_plan_fingerprint),
        (review.weighting_authority_fingerprint, revision.weighting_authority_fingerprint),
    )
    if ((review.project_id, review.run_id, review.method_version) !=
            (project_id, run_id, "QUANTITATIVE/1")
            or review.verdict is not ReviewVerdict.APPROVE
            or any(actual != expected for actual, expected in pairs)):
        raise QuantitativeDeliverableSourceError("approved Quant Review binding is inconsistent")

    dataset = _load(state, revision.dataset_record_id, project_id=project_id, run_id=run_id,
                    expected_type=DatasetVersion)
    manifest = _load(state, revision.analysis_manifest_record_id, project_id=project_id, run_id=run_id,
                     expected_type=QuantitativeAnalysisManifest)
    findings = _load(state, revision.finding_generation_record_id, project_id=project_id, run_id=run_id,
                     expected_type=QuantitativeFindingGenerationResult)
    insights = _load(state, revision.insight_generation_record_id, project_id=project_id, run_id=run_id,
                     expected_type=QuantitativeInsightGenerationResult)
    composition = _load(state, review.report_composition_record_id,
                        project_id=project_id, run_id=run_id,
                        expected_type=QuantitativeReportCompositionResult)
    report = composition.accepted_report
    if (dataset.dataset_fingerprint != revision.dataset_fingerprint
            or manifest.fingerprint != revision.analysis_manifest_fingerprint
            or manifest.dataset_version_id != dataset.version_id
            or findings.generation_fingerprint != revision.finding_generation_fingerprint
            or insights.generation_fingerprint != revision.insight_generation_fingerprint
            or composition.composition_fingerprint != review.report_composition_fingerprint
            or report is None
            or report.validation_status is not QuantitativeReportValidationStatus.SUPPORTED
            or (report.report_id, report.validation_fingerprint) !=
               (revision.report_id, revision.report_validation_fingerprint)):
        raise QuantitativeDeliverableSourceError("approved Quant source chain is inconsistent")

    results = {}
    for record_id in manifest.statistical_result_record_ids:
        result = _load(state, record_id, project_id=project_id, run_id=run_id,
                       expected_type=StatisticalResult)
        if (result.dataset_version_id, result.dataset_fingerprint,
                result.data_fingerprint, result.codebook_fingerprint) != (
                dataset.version_id, dataset.dataset_fingerprint,
                dataset.data_fingerprint, dataset.codebook_fingerprint):
            raise QuantitativeDeliverableSourceError("Quant result has foreign dataset authority")
        if result.result_id in results:
            raise QuantitativeDeliverableSourceError("duplicate Quant result identity")
        results[result.result_id] = result

    referenced = {value for section in report.sections
                  for value in section.authoritative_result_refs}
    referenced.update(value for section in report.sections for claim in section.claim_units
                      for value in claim.authoritative_result_refs)
    if not referenced.issubset(results):
        raise QuantitativeDeliverableSourceError("Quant Report references unavailable results")

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
        ) if value),
    ) for section in report.sections)
    tables = tuple(PdfTable(
        title=section.title,
        headers=("Показник", "Значення", "База", "Зважування"),
        rows=tuple((results[result_id].variable_id, str(results[result_id].value),
                    results[result_id].base_definition,
                    results[result_id].weighting_status)
                   for result_id in dict.fromkeys(section.authoritative_result_refs)),
        base=section.base_definition,
    ) for section in report.sections if section.authoritative_result_refs)
    return PdfSourceDocument(
        project_id=project_id, method="QUANTITATIVE", run_id=run_id,
        study_id=study_id, source_id=revision.revision_id,
        source_version=revision.fingerprint, status="Схвалено",
        title=report.title, summary=None, sections=sections,
        limitations=tuple(section.narrative for section in report.sections
                          if section.section_type.value == "LIMITATIONS"),
        tables=tables,
        unavailable=("Графіки не додано: канонічний зв’язок із збереженою схваленою ревізією не підтверджено.",),
    )
