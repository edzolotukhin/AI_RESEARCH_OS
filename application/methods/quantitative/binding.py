"""Thin CMF Quant facade over the existing deterministic vertical."""

from application.methods.contracts import Capabilities, MethodIdentity
from domain.quantitative.dataset import CodebookVersion, DatasetVersion, ValidationStatus
from application.methods.quantitative.readiness import assess_foundation


class QuantitativeBinding:
    identity = MethodIdentity(
        "QUANTITATIVE", "1", "Quantitative Research", 1,
        "quant-design-1", "quant-dataset-1", 1, "quant-authority-1",
        "quant-readiness-1", "rd-1", "quant-review-1", "qk-1",
    )
    capabilities = Capabilities(
        "persisted_dataset", ("dataset_authority",), ("PDF", "PPTX"),
        ("design", "data_qc", "report"),
    )

    def bind_dataset(self, *, dataset: DatasetVersion, codebook: CodebookVersion) -> None:
        if not isinstance(dataset, DatasetVersion) or not isinstance(codebook, CodebookVersion):
            raise ValueError("canonical Quant dataset authority is required")
        if dataset.validation_status is ValidationStatus.BLOCKED or not codebook.approved:
            raise ValueError("Quant dataset/codebook authority is blocked")
        if dataset.codebook_version_id != codebook.codebook_version_id or dataset.codebook_fingerprint != codebook.fingerprint:
            raise ValueError("Quant codebook is not bound to the exact dataset version")

    def assess_readiness(self, *, dataset, codebook, procedure, eligible_n,
                         minimum_n=1, execution_status=None):
        return assess_foundation(dataset=dataset, codebook=codebook, procedure=procedure,
                                 eligible_n=eligible_n, minimum_n=minimum_n,
                                 execution_status=execution_status)

    def run_stage(self, stage, context, delegate):
        if stage not in {"quant_import", "quant_qc", "quant_qc_approval", "quant_cleaning",
                         "quant_weightset", "quant_weight_approval", "quant_analysis",
                         "quant_findings", "quant_insights", "quant_report", "quant_rq_coverage",
                         "quant_complete"}:
            raise ValueError("Unsupported Quant stage")
        return delegate(context)

    def report_sources(self, project_id, run_ids, delegate):
        return delegate(project_id, run_ids)
