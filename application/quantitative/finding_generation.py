from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.finding_support import QuantitativeFindingSupportValidator
from application.quantitative.fingerprints import canonical_digest, canonical_scalar
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.analysis import AnalyticalComparisonResult, StatisticalResult
from domain.quantitative.finding import (
    QuantitativeClaim,
    QuantitativeClaimType,
    QuantitativeComparisonReference,
    QuantitativeFinding,
    QuantitativeFindingGenerationResult,
    QuantitativeFindingRejection,
    QuantitativeResultReference,
)


PROMPT_VERSION = "QI_FINDING_GENERATION_V2"
MAX_RESULTS = 100
MAX_PROMPT_CHARACTERS = 60_000
MAX_PROPOSALS = 25


class QuantitativeFindingProposalGenerator(Protocol):
    @property
    def identity(self) -> str: ...

    def generate(self, prompt: str) -> Mapping[str, Any]: ...


class QuantitativeFindingGenerationService:
    def __init__(
        self,
        *,
        generator: QuantitativeFindingProposalGenerator,
        support_validator: QuantitativeFindingSupportValidator,
        digest_provider: DeterministicDigestProvider,
    ) -> None:
        self._generator = generator
        self._validator = support_validator
        self._digest = digest_provider

    def generate(
        self,
        *,
        statistical_results: Sequence[StatisticalResult],
        comparison_results: Sequence[AnalyticalComparisonResult] = (),
        display_labels: Mapping[str, str] | None = None,
        limitations: Sequence[str] = (),
    ) -> QuantitativeFindingGenerationResult:
        results = self._authoritative_results(statistical_results)
        comparisons = self._authoritative_comparisons(comparison_results, results)
        labels = self._safe_text_mapping(display_labels or {}, "display label")
        safe_limitations = tuple(self._safe_text(item, "limitation") for item in limitations)
        bundle = self._bundle(results, comparisons, labels, safe_limitations)
        bundle_fingerprint = canonical_digest(bundle, digest_provider=self._digest)
        prompt = self._prompt(bundle)
        prompt_fingerprint = canonical_digest(
            {"version": PROMPT_VERSION, "prompt": prompt},
            digest_provider=self._digest,
        )

        # QI V1 permits exactly one proposal-generation pass and no repair call.
        raw_output = self._generator.generate(prompt)
        raw_proposals = self._proposal_list(raw_output)
        available_results = {item.result_id: item for item in results}
        available_comparisons = {
            item.comparison_result_id: item for item in comparisons
        }
        proposed: list[QuantitativeFinding] = []
        accepted: list[QuantitativeFinding] = []
        rejected: list[QuantitativeFindingRejection] = []

        for ordinal, raw in enumerate(raw_proposals, start=1):
            proposal_payload = dict(raw) if isinstance(raw, Mapping) else {"raw_type": type(raw).__name__}
            try:
                finding = self._parse_proposal(
                    raw,
                    ordinal=ordinal,
                    bundle_fingerprint=bundle_fingerprint,
                    available_results=available_results,
                    available_comparisons=available_comparisons,
                )
                proposed.append(finding)
                accepted.append(
                    self._validator.validate(
                        finding,
                        statistical_results=available_results,
                        comparison_results=available_comparisons,
                    )
                )
            except (QuantitativeAnalysisError, ValueError, TypeError, KeyError) as exc:
                reason = f"{type(exc).__name__}: {exc}"
                rejected.append(
                    QuantitativeFindingRejection(
                        proposal_ordinal=ordinal,
                        proposal_payload=proposal_payload,
                        reason=reason,
                        rejection_fingerprint=canonical_digest(
                            {
                                "bundle": bundle_fingerprint,
                                "ordinal": ordinal,
                                "proposal": proposal_payload,
                                "reason": reason,
                                "version": PROMPT_VERSION,
                            },
                            digest_provider=self._digest,
                        ),
                    )
                )

        summary = {
            "proposed": len(raw_proposals),
            "parsed": len(proposed),
            "accepted": len(accepted),
            "rejected": len(rejected),
        }
        generation_payload = {
            "bundle": bundle_fingerprint,
            "generator": self._generator.identity,
            "prompt": prompt_fingerprint,
            "accepted": tuple(item.support_validation_fingerprint for item in accepted),
            "rejected": tuple(item.rejection_fingerprint for item in rejected),
            "summary": summary,
            "version": PROMPT_VERSION,
        }
        generation_fingerprint = canonical_digest(generation_payload, digest_provider=self._digest)
        return QuantitativeFindingGenerationResult(
            generation_id=str(uuid5(NAMESPACE_URL, f"qi-generation:{generation_fingerprint}")),
            input_result_bundle_fingerprint=bundle_fingerprint,
            generator_identity=self._generator.identity,
            prompt_version=PROMPT_VERSION,
            prompt_fingerprint=prompt_fingerprint,
            proposed_findings=tuple(proposed),
            accepted_findings=tuple(accepted),
            rejected_findings=tuple(rejected),
            generation_metadata={"generation_passes": 1, "repair_attempts": 0},
            acceptance_summary=summary,
            generation_fingerprint=generation_fingerprint,
        )

    @staticmethod
    def _authoritative_results(results):
        if not results or len(results) > MAX_RESULTS:
            raise QuantitativeAnalysisError("approved result bundle must be non-empty and bounded")
        ids = [item.result_id for item in results]
        if len(ids) != len(set(ids)) or any(not item.reproducibility_fingerprint for item in results):
            raise QuantitativeAnalysisError("result bundle contains duplicate or non-authoritative results")
        return tuple(results)

    @staticmethod
    def _authoritative_comparisons(comparisons, results):
        ids = [item.comparison_result_id for item in comparisons]
        if len(ids) != len(set(ids)):
            raise QuantitativeAnalysisError("comparison bundle contains duplicate results")
        result_pairs = {(item.result_id, item.reproducibility_fingerprint) for item in results}
        for item in comparisons:
            if not item.reproducibility_fingerprint or (
                item.group_a_result_id, item.group_a_result_fingerprint
            ) not in result_pairs or (
                item.group_b_result_id, item.group_b_result_fingerprint
            ) not in result_pairs:
                raise QuantitativeAnalysisError("comparison bundle references unavailable StatisticalResults")
        return tuple(comparisons)

    def _bundle(self, results, comparisons, labels, limitations):
        return {
            "statistical_results": tuple(self._result_projection(item, labels) for item in results),
            "comparison_results": tuple(self._comparison_projection(item) for item in comparisons),
            "limitations": limitations,
        }

    @staticmethod
    def _result_projection(item, labels):
        return {
            "result_id": item.result_id,
            "reproducibility_fingerprint": item.reproducibility_fingerprint,
            "display_label": labels.get(item.result_id, item.statistic_type),
            "variable_id": item.variable_id,
            "statistic_type": item.statistic_type,
            "value": canonical_scalar(item.value),
            "display_value_1dp": QuantitativeFindingSupportValidator.display_value(
                Decimal(str(item.value)), decimal_places=1
            ),
            "denominator": canonical_scalar(item.denominator),
            "category_value": canonical_scalar(item.category_value),
            "row_category_value": canonical_scalar(item.row_category_value),
            "column_category_value": canonical_scalar(item.column_category_value),
            "filter_definition": item.filter_definition,
            "base_definition": item.base_definition,
            "weighting_status": item.weighting_status,
            "weight_set_fingerprint": item.weight_set_fingerprint,
            "unweighted_n": item.unweighted_n,
            "weighted_base": canonical_scalar(item.weighted_base),
            "missing_value_semantics": item.missing_value_semantics,
            "presentation_eligible": item.presentation_eligible,
        }

    @staticmethod
    def _comparison_projection(item):
        return {
            "comparison_result_id": item.comparison_result_id,
            "reproducibility_fingerprint": item.reproducibility_fingerprint,
            "group_a_result_id": item.group_a_result_id,
            "group_b_result_id": item.group_b_result_id,
            "observed_difference": canonical_scalar(item.observed_difference),
            "p_value": canonical_scalar(item.p_value),
            "alpha": canonical_scalar(item.alpha),
            "significant": item.significant,
            "supports_significance_wording": item.supports_significance_wording,
            "method": item.method,
            "method_version": item.method_version,
            "group_a_base": item.group_a_base,
            "group_b_base": item.group_b_base,
        }

    @staticmethod
    def _prompt(bundle):
        instructions = (
            "Generate structured Quantitative Finding proposals using only the supplied result IDs. "
            "Return IDs only: never copy, reconstruct, abbreviate, or return authority fingerprints; "
            "the application resolves canonical fingerprints from the exact supplied bundle. "
            "Do not calculate new values or introduce numbers absent from authoritative results. "
            "Do not infer significance from percentages alone: significance wording requires a supplied "
            "comparison result with supports_significance_wording=true. Distinguish observed differences "
            "from statistically significant differences. Preserve filters, bases, categories, and weighted/"
            "unweighted context exactly. Prefer analytically useful findings over exhaustive restatement and "
            "include a limitation_note when supplied bases or context warrant caution. Return one JSON object "
            "with a proposals array and only QH claim types. No respondent-level facts or identifiers exist in "
            "this context."
        )
        schema = {
            "reference_contract": {
                "DESCRIPTIVE_VALUE": {"statistical_result_refs": 1, "comparison_result_refs": 0},
                "NUMERIC_SUMMARY": {"statistical_result_refs": 1, "comparison_result_refs": 0},
                "KPI_VALUE": {"statistical_result_refs": 1, "comparison_result_refs": 0},
                "DESCRIPTIVE_COMPARISON": {"statistical_result_refs": 2, "comparison_result_refs": 0},
                "SIGNIFICANT_COMPARISON": {"statistical_result_refs": 2, "comparison_result_refs": 1},
            },
            "proposals": [{
                "claim_type": "DESCRIPTIVE_VALUE|NUMERIC_SUMMARY|KPI_VALUE|DESCRIPTIVE_COMPARISON|SIGNIFICANT_COMPARISON",
                "finding_text": "string",
                "statistical_result_refs": ["result-id"],
                "comparison_result_refs": ["comparison-id"],
                "value": "exact decimal or null",
                "display_value": "deterministically rounded string or null",
                "rounding_decimal_places": 1,
                "variable_id": "variable-id",
                "statistic_type": "type",
                "category_value": "category or null",
                "filter_definition": "exact supplied filter",
                "base_definition": "exact supplied base",
                "weighting_status": "UNWEIGHTED|WEIGHTED",
                "weight_set_fingerprint": "fingerprint or null",
                "direction": "HIGHER|LOWER|EQUAL|null",
                "limitation_note": "optional string",
            }]
        }
        prompt = instructions + "\nOUTPUT_SCHEMA=" + json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\nAUTHORITATIVE_BUNDLE=" + json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise QuantitativeAnalysisError("Quantitative Finding prompt exceeds bounded size")
        return prompt

    @staticmethod
    def _proposal_list(raw_output):
        if not isinstance(raw_output, Mapping):
            raise QuantitativeAnalysisError("structured generator output must be an object")
        proposals = raw_output.get("proposals")
        if not isinstance(proposals, list) or len(proposals) > MAX_PROPOSALS:
            raise QuantitativeAnalysisError("structured generator proposals must be a bounded array")
        return tuple(proposals)

    def _parse_proposal(self, raw, *, ordinal, bundle_fingerprint, available_results, available_comparisons):
        if not isinstance(raw, Mapping):
            raise QuantitativeAnalysisError("proposal must be an object")
        claim_type = QuantitativeClaimType(str(raw["claim_type"]))
        result_ids = self._string_list(raw.get("statistical_result_refs"), "statistical_result_refs")
        comparison_ids = self._string_list(
            raw.get("comparison_result_refs", []),
            "comparison_result_refs",
            allow_empty=True,
        )
        self._validate_reference_cardinality(claim_type, result_ids, comparison_ids)
        if any(item not in available_results for item in result_ids):
            raise QuantitativeAnalysisError("proposal references a result outside the authoritative bundle")
        if any(item not in available_comparisons for item in comparison_ids):
            raise QuantitativeAnalysisError("proposal references a comparison outside the authoritative bundle")
        # The model selects bundle-bound IDs only. Canonical fingerprints are always
        # recovered here and cannot be supplied or overridden by model output.
        result_refs = tuple(QuantitativeResultReference(
            item, available_results[item].reproducibility_fingerprint
        ) for item in result_ids)
        comparison_refs = tuple(QuantitativeComparisonReference(
            item, available_comparisons[item].reproducibility_fingerprint
        ) for item in comparison_ids)
        value = self._decimal_or_none(raw.get("value"))
        text = self._safe_text(str(raw["finding_text"]), "finding text")
        limitation = raw.get("limitation_note")
        if limitation is not None:
            self._safe_text(str(limitation), "limitation note")
        pii = self._pii_exposures(text)
        identity_proposal = {
            key: value for key, value in raw.items()
            if key not in {
                "statistical_result_fingerprints",
                "comparison_result_fingerprints",
            }
        }
        proposal_identity = canonical_digest(
            {"bundle": bundle_fingerprint, "ordinal": ordinal, "proposal": identity_proposal},
            digest_provider=self._digest,
        )
        return QuantitativeFinding(
            finding_id=str(uuid5(NAMESPACE_URL, f"qi-finding:{proposal_identity}")),
            text=text,
            claim=QuantitativeClaim(
                claim_type=claim_type,
                value=value,
                variable_id=str(raw["variable_id"]),
                statistic_type=str(raw["statistic_type"]),
                category_value=raw.get("category_value"),
                filter_definition=str(raw["filter_definition"]),
                base_definition=str(raw["base_definition"]),
                weighting_status=str(raw["weighting_status"]),
                weight_set_fingerprint=self._optional_string(raw.get("weight_set_fingerprint")),
                direction=self._optional_string(raw.get("direction")),
                display_value=self._optional_string(raw.get("display_value")),
            ),
            statistical_result_refs=result_refs,
            comparison_result_refs=comparison_refs,
            rounding_decimal_places=self._integer(raw.get("rounding_decimal_places", 1)),
            pii_exposures=pii,
        )

    @staticmethod
    def _string_list(value, name, *, allow_empty=False):
        if not isinstance(value, list) or (not value and not allow_empty) or any(not isinstance(item, str) or not item for item in value):
            raise QuantitativeAnalysisError(f"{name} must be a non-empty string array")
        if len(value) != len(set(value)):
            raise QuantitativeAnalysisError(f"{name} contains duplicates")
        return tuple(value)

    @staticmethod
    def _validate_reference_cardinality(claim_type, result_ids, comparison_ids):
        expected = {
            QuantitativeClaimType.DESCRIPTIVE_VALUE: (1, 0),
            QuantitativeClaimType.NUMERIC_SUMMARY: (1, 0),
            QuantitativeClaimType.KPI_VALUE: (1, 0),
            QuantitativeClaimType.DESCRIPTIVE_COMPARISON: (2, 0),
            QuantitativeClaimType.SIGNIFICANT_COMPARISON: (2, 1),
        }[claim_type]
        actual = (len(result_ids), len(comparison_ids))
        if actual != expected:
            raise QuantitativeAnalysisError(
                f"{claim_type.value} requires exactly {expected[0]} StatisticalResult "
                f"reference(s) and {expected[1]} ComparisonResult reference(s)"
            )

    @staticmethod
    def _decimal_or_none(value):
        if value is None:
            return None
        if isinstance(value, bool):
            raise QuantitativeAnalysisError("proposal value must be a finite decimal")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise QuantitativeAnalysisError("proposal value must be a finite decimal") from None
        if not result.is_finite():
            raise QuantitativeAnalysisError("proposal value must be a finite decimal")
        return result

    @staticmethod
    def _integer(value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise QuantitativeAnalysisError("rounding_decimal_places must be an integer")
        return value

    @staticmethod
    def _optional_string(value):
        return None if value is None else str(value)

    @classmethod
    def _safe_text_mapping(cls, values, label):
        return {str(key): cls._safe_text(str(value), label) for key, value in values.items()}

    @classmethod
    def _safe_text(cls, value, label):
        text = value.strip()
        if not text or len(text) > 500 or cls._pii_exposures(text):
            raise QuantitativeAnalysisError(f"{label} is empty, oversized, or contains direct PII")
        return text

    @staticmethod
    def _pii_exposures(text):
        exposures = []
        if re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE):
            exposures.append("email")
        if re.search(r"(?<!\w)(?:\+?\d[\d .()/-]{7,}\d)(?!\w)", text):
            exposures.append("telephone")
        return tuple(exposures)
