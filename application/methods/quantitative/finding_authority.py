"""Bind new-run Quant Findings to immutable dataset/result authority."""

from __future__ import annotations

from dataclasses import replace

from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.finding import CanonicalQuantFindingAuthority


class CanonicalQuantFindingSupportValidator(QuantitativeFindingSupportValidator):
    def __init__(self, *, digest_provider, dataset, run_id: str):
        super().__init__(digest_provider=digest_provider)
        self._dataset = dataset
        self._run_id = run_id

    def validate(self, finding, *, statistical_results, comparison_results=None,
                 semantic_evidence_contexts=None):
        supported = super().validate(
            finding, statistical_results=statistical_results,
            comparison_results=comparison_results,
            semantic_evidence_contexts=semantic_evidence_contexts,
        )
        results = tuple(statistical_results[item.result_id]
                        for item in supported.statistical_result_refs)
        comparisons = tuple((comparison_results or {})[item.comparison_result_id]
                            for item in supported.comparison_result_refs)
        dataset = self._dataset
        if not self._run_id or any(
            (item.dataset_version_id, item.dataset_fingerprint, item.data_fingerprint,
             item.codebook_fingerprint) !=
            (dataset.version_id, dataset.dataset_fingerprint, dataset.data_fingerprint,
             dataset.codebook_fingerprint)
            for item in results
        ) or any(
            (item.dataset_version_id, item.dataset_fingerprint, item.data_fingerprint) !=
            (dataset.version_id, dataset.dataset_fingerprint, dataset.data_fingerprint)
            for item in comparisons
        ):
            raise QuantitativeAnalysisError("Finding result is outside pinned dataset authority")
        procedures = tuple((item.computation_method, item.computation_version)
                           for item in results) + tuple(
            (item.method, item.method_version) for item in comparisons
        )
        significance = tuple(
            (item.comparison_result_id, item.significant,
             canonical_scalar(item.p_value), canonical_scalar(item.alpha))
            for item in comparisons
        )
        payload = {
            "run": self._run_id, "method": "QUANTITATIVE/1",
            "dataset": (dataset.version_id, dataset.dataset_fingerprint,
                        dataset.data_fingerprint, dataset.codebook_fingerprint),
            "source_n": dataset.row_count,
            "results": tuple((item.result_id, item.reproducibility_fingerprint)
                             for item in results),
            "comparisons": tuple((item.comparison_result_id,
                                  item.reproducibility_fingerprint) for item in comparisons),
            "procedures": procedures,
            "denominators": tuple(canonical_scalar(item.denominator) for item in results),
            "filter": supported.claim.filter_definition,
            "base": supported.claim.base_definition,
            "weighting": (supported.claim.weighting_status,
                          supported.claim.weight_set_fingerprint),
            "missing": tuple(item.missing_value_semantics for item in results),
            "significance": significance,
            "version": "QNT03_FINDING_AUTHORITY_V1",
        }
        authority = CanonicalQuantFindingAuthority(
            self._run_id, "QUANTITATIVE/1", dataset.version_id,
            dataset.dataset_fingerprint, dataset.row_count,
            supported.statistical_result_refs, supported.comparison_result_refs,
            procedures, tuple(item.denominator for item in results),
            supported.claim.filter_definition, supported.claim.base_definition,
            supported.claim.weighting_status, supported.claim.weight_set_fingerprint,
            tuple(item.missing_value_semantics for item in results),
            tuple((item.comparison_result_id, item.significant, item.p_value, item.alpha)
                  for item in comparisons),
            canonical_digest(payload, digest_provider=self._digest),
        )
        fingerprint = canonical_digest({
            "support": supported.support_validation_fingerprint,
            "authority": authority.fingerprint,
            "version": "QNT03_FINDING_SUPPORT_V1",
        }, digest_provider=self._digest)
        return replace(supported, canonical_authority=authority,
                       support_validation_fingerprint=fingerprint,
                       support_validation_version="qnt03-1")
