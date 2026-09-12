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
    QuantitativeSemanticEvidenceContext,
)


PROMPT_VERSION = "QI_FINDING_GENERATION_V4"
MATERIALITY_METHOD_VERSION = "QI_SELECTOR_MATERIALITY_V1"
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
        semantic_evidence_contexts: Mapping[str, QuantitativeSemanticEvidenceContext] | None = None,
        limitations: Sequence[str] = (),
    ) -> QuantitativeFindingGenerationResult:
        results = self._authoritative_results(statistical_results)
        comparisons = self._authoritative_comparisons(comparison_results, results)
        labels = self._safe_text_mapping(display_labels or {}, "display label")
        contexts = dict(semantic_evidence_contexts or {})
        if any(key != value.result_id for key, value in contexts.items()):
            raise QuantitativeAnalysisError("semantic evidence context result identity mismatch")
        safe_limitations = tuple(self._safe_text(item, "limitation") for item in limitations)
        materiality = self._selection_materiality(results)
        authority_bundle = self._bundle(
            results, comparisons, labels, safe_limitations, contexts,
        )
        eligible_results = tuple(
            item
            for item in results
            if item.presentation_eligible and self._allowed_claim_types(item.statistic_type)
        )
        eligible_ids = {item.result_id for item in eligible_results}
        selectable_comparisons = tuple(
            item
            for item in comparisons
            if item.group_a_result_id in {result.result_id for result in results}
            and item.group_b_result_id in {result.result_id for result in results}
        )
        comparison_precursor_ids = {
            result_id
            for item in selectable_comparisons
            for result_id in (item.group_a_result_id, item.group_b_result_id)
        }
        selectable_ids = eligible_ids | comparison_precursor_ids
        selectable_results = tuple(item for item in results if item.result_id in selectable_ids)
        if not eligible_results and not selectable_comparisons:
            return self._empty_generation(
                authority_bundle=authority_bundle,
                reason="NO_PRESENTATION_ELIGIBLE_QH_SUPPORT",
            )
        bundle = self._bundle(
            selectable_results, selectable_comparisons, labels, safe_limitations, contexts,
            selector_contract=True, materiality=materiality,
        )
        bundle_fingerprint = canonical_digest(
            authority_bundle, digest_provider=self._digest
        )
        prompt = self._prompt(bundle)
        prompt_fingerprint = canonical_digest(
            {"version": PROMPT_VERSION, "prompt": prompt},
            digest_provider=self._digest,
        )

        # QI V1 permits exactly one proposal-generation pass and no repair call.
        raw_output = self._generator.generate(prompt)
        raw_proposals = self._proposal_list(raw_output)
        if not raw_proposals and any(
            materiality[item.result_id]["is_dominant"]
            for item in selectable_results
        ):
            raise QuantitativeAnalysisError(
                "QI selector abstained despite application-ranked dominant eligible result"
            )
        available_results = {item.result_id: item for item in selectable_results}
        available_comparisons = {
            item.comparison_result_id: item for item in selectable_comparisons
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
                    semantic_evidence_contexts=contexts,
                )
                proposed.append(finding)
                accepted.append(
                    self._validator.validate(
                        finding,
                        statistical_results=available_results,
                        comparison_results=available_comparisons,
                        semantic_evidence_contexts=contexts,
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

    def _empty_generation(self, *, authority_bundle, reason):
        bundle_fingerprint = canonical_digest(
            authority_bundle, digest_provider=self._digest
        )
        prompt_fingerprint = canonical_digest(
            {"version": PROMPT_VERSION, "abstention": reason},
            digest_provider=self._digest,
        )
        summary = {"proposed": 0, "parsed": 0, "accepted": 0, "rejected": 0}
        generation_fingerprint = canonical_digest(
            {
                "bundle": bundle_fingerprint,
                "generator": self._generator.identity,
                "prompt": prompt_fingerprint,
                "accepted": (),
                "rejected": (),
                "summary": summary,
                "abstention": reason,
                "version": PROMPT_VERSION,
            },
            digest_provider=self._digest,
        )
        return QuantitativeFindingGenerationResult(
            generation_id=str(uuid5(NAMESPACE_URL, f"qi-generation:{generation_fingerprint}")),
            input_result_bundle_fingerprint=bundle_fingerprint,
            generator_identity=self._generator.identity,
            prompt_version=PROMPT_VERSION,
            prompt_fingerprint=prompt_fingerprint,
            proposed_findings=(),
            accepted_findings=(),
            rejected_findings=(),
            generation_metadata={
                "generation_passes": 0,
                "repair_attempts": 0,
                "abstention_reason": reason,
            },
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

    def _bundle(
        self, results, comparisons, labels, limitations, contexts=None, *, selector_contract=False,
        materiality=None,
    ):
        contexts = contexts or {}
        expected_materiality = self._selection_materiality(results)
        if materiality is None:
            materiality = expected_materiality
        if any(
            materiality.get(item.result_id) != expected_materiality[item.result_id]
            for item in results
        ):
            raise QuantitativeAnalysisError(
                "selection materiality metadata is inconsistent with authoritative results"
            )
        return {
            "statistical_results": tuple(
                self._selector_result_projection(
                    item, labels, materiality[item.result_id], contexts.get(item.result_id)
                )
                if selector_contract
                else self._result_projection(item, labels, contexts.get(item.result_id))
                for item in results
            ),
            "comparison_results": tuple(
                self._selector_comparison_projection(item)
                if selector_contract
                else self._comparison_projection(item)
                for item in comparisons
            ),
            "limitations": limitations,
        }

    @staticmethod
    def _result_projection(item, labels, context=None):
        projection = {
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
        if context is not None:
            projection["semantic_evidence_context"] = (
                QuantitativeFindingGenerationService._semantic_context_projection(context)
            )
        return projection

    @staticmethod
    def _selector_result_projection(item, labels, selection_materiality, context=None):
        projection = {
            "result_id": item.result_id,
            "display_label": labels.get(item.result_id, item.statistic_type),
            "allowed_claim_types": QuantitativeFindingGenerationService._allowed_claim_types(
                item.statistic_type
            ),
            "display_value_1dp": QuantitativeFindingSupportValidator.display_value(
                Decimal(str(item.value)), decimal_places=1
            ),
            "category_value": canonical_scalar(item.category_value),
            "row_category_value": canonical_scalar(item.row_category_value),
            "column_category_value": canonical_scalar(item.column_category_value),
            "denominator": canonical_scalar(item.denominator),
            "filter_definition": item.filter_definition,
            "base_definition": item.base_definition,
            "weighting_status": item.weighting_status,
            "unweighted_n": item.unweighted_n,
            "presentation_eligible": item.presentation_eligible,
            "selection_materiality": selection_materiality,
        }
        if context is not None:
            projection["semantic_evidence_context"] = (
                QuantitativeFindingGenerationService._semantic_context_projection(context)
            )
        return projection

    @staticmethod
    def _semantic_context_projection(context):
        return {
            "context_id": context.context_id,
            "fingerprint": context.fingerprint,
            "result_id": context.result_id,
            "variable_id": context.variable_id,
            "variable_label": context.variable_label,
            "question_context": context.question_context,
            "category_code": canonical_scalar(context.category_code),
            "category_label": context.category_label,
            "filter_definition": context.filter_definition,
            "base_definition": context.base_definition,
            "denominator": canonical_scalar(context.denominator),
            "population_description": context.population_description,
            "display_value": context.display_value,
            "weighting_status": context.weighting_status,
            "provenance": context.provenance,
        }

    def _selection_materiality(self, results):
        ranked = {}
        distributions = {}
        for item in results:
            if not item.presentation_eligible or item.statistic_type not in {
                "VALID_PERCENTAGE", "WEIGHTED_PERCENTAGE", "CROSS_TAB_COLUMN_PERCENTAGE",
            }:
                continue
            key = canonical_digest(
                {
                    "analysis_specification_id": item.analysis_specification_id,
                    "analysis_specification_fingerprint": item.analysis_specification_fingerprint,
                    "variable_id": item.variable_id,
                    "variable_fingerprint": item.variable_fingerprint,
                    "statistic_type": item.statistic_type,
                    "filter_definition": item.filter_definition,
                    "base_definition": item.base_definition,
                    "weighting_status": item.weighting_status,
                    "weight_set_fingerprint": item.weight_set_fingerprint,
                    "row_variable_id": item.row_variable_id,
                    "row_variable_fingerprint": item.row_variable_fingerprint,
                    "column_variable_id": item.column_variable_id,
                    "column_variable_fingerprint": item.column_variable_fingerprint,
                    "column_category_value": canonical_scalar(item.column_category_value),
                },
                digest_provider=self._digest,
            )
            try:
                value = Decimal(str(item.value))
            except (InvalidOperation, ValueError) as exc:
                raise QuantitativeAnalysisError("ranked percentage result has invalid value") from exc
            if not value.is_finite():
                raise QuantitativeAnalysisError("ranked percentage result has invalid value")
            distributions.setdefault(key, []).append((item, value))
        for entries in distributions.values():
            values = sorted({value for _, value in entries}, reverse=True)
            for item, value in entries:
                ranked[item.result_id] = {
                    "method_version": MATERIALITY_METHOD_VERSION,
                    "kind": "TOP_CATEGORICAL_PERCENTAGE",
                    "rank_within_distribution": values.index(value) + 1,
                    "tied_result_count": sum(1 for _, other in entries if other == value),
                    "eligible_distribution_size": len(entries),
                    "is_dominant": value == values[0],
                }
        return {
            item.result_id: ranked.get(
                item.result_id,
                {
                    "method_version": MATERIALITY_METHOD_VERSION,
                    "kind": "NOT_RANKED",
                    "rank_within_distribution": None,
                    "tied_result_count": 0,
                    "eligible_distribution_size": 0,
                    "is_dominant": False,
                },
            )
            for item in results
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
    def _selector_comparison_projection(item):
        return {
            "comparison_result_id": item.comparison_result_id,
            "group_a_result_id": item.group_a_result_id,
            "group_b_result_id": item.group_b_result_id,
            "observed_difference_1dp": QuantitativeFindingSupportValidator.display_value(
                Decimal(str(item.observed_difference)), decimal_places=1
            ),
            "significant": item.significant,
            "supports_significance_wording": item.supports_significance_wording,
            "method": item.method,
            "group_a_base": item.group_a_base,
            "group_b_base": item.group_b_base,
        }

    @staticmethod
    def _prompt(bundle):
        instructions = (
            "Generate structured Quantitative Finding proposals by selecting only the supplied result IDs. "
            "Return IDs only: never copy, reconstruct, abbreviate, or return authority fingerprints; "
            "the application resolves canonical fingerprints, exact values, statistic types, categories, "
            "bases, filters, and weighting from the exact supplied bundle. Do not return those fields. "
            "When semantic_evidence_context is supplied, write only a bounded analytical claim. The "
            "application deterministically attaches its canonical category, question, population, "
            "denominator, filter, base, and weighting context. Omission is allowed, but never state or "
            "imply a conflicting population, denominator, filter, base, or weighting contract. "
            "Use only an allowed_claim_type listed for every selected result. Do not calculate new values "
            "or introduce numbers absent from authoritative results. When prose includes a percentage, copy "
            "the supplied display_value_1dp exactly and append %. "
            "Do not infer significance from percentages alone: significance wording requires a supplied "
            "comparison result with supports_significance_wording=true. Distinguish observed differences "
            "from statistically significant differences. Preserve filters, bases, categories, and weighted/"
            "unweighted context exactly. Prefer analytically useful findings over exhaustive restatement and "
            "include a limitation_note when supplied bases or context warrant caution. selection_materiality is "
            "application-owned: never return it. If any supplied result has is_dominant=true, select at least one "
            "such result; an empty proposals array is allowed only when no supplied result is dominant. Return one "
            "JSON object with a proposals array and only QH claim types. No respondent-level facts or identifiers "
            "exist in this context."
        )
        schema = {
            "reference_contract": {
                "DESCRIPTIVE_VALUE": {"selected_result_ids": 1, "selected_comparison_ids": 0},
                "NUMERIC_SUMMARY": {"selected_result_ids": 1, "selected_comparison_ids": 0},
                "KPI_VALUE": {"selected_result_ids": 1, "selected_comparison_ids": 0},
                "DESCRIPTIVE_COMPARISON": {"selected_result_ids": 2, "selected_comparison_ids": 0},
                "SIGNIFICANT_COMPARISON": {"selected_result_ids": 2, "selected_comparison_ids": 1},
            },
            "proposals": [{
                "claim_type": "DESCRIPTIVE_VALUE|NUMERIC_SUMMARY|KPI_VALUE|DESCRIPTIVE_COMPARISON|SIGNIFICANT_COMPARISON",
                "finding_text": "string",
                "selected_result_ids": ["result-id"],
                "selected_comparison_ids": ["comparison-id"],
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

    def _parse_proposal(self, raw, *, ordinal, bundle_fingerprint, available_results, available_comparisons, semantic_evidence_contexts):
        if not isinstance(raw, Mapping):
            raise QuantitativeAnalysisError("proposal must be an object")
        forbidden_design_fields = {
            "planned_analysis_id", "planned_comparison_id", "objective_ids",
            "research_question_ids", "analytical_requirement_ids",
            "selection_materiality", "rank_within_distribution", "is_dominant",
        }
        if forbidden_design_fields.intersection(raw):
            raise QuantitativeAnalysisError("proposal must not supply design lineage")
        claim_type = QuantitativeClaimType(str(raw["claim_type"]))
        result_ids = self._selected_ids(
            raw,
            canonical_name="selected_result_ids",
            legacy_name="statistical_result_refs",
        )
        comparison_ids = self._string_list(
            self._selected_value(
                raw,
                canonical_name="selected_comparison_ids",
                legacy_name="comparison_result_refs",
                default=[],
            ),
            "selected_comparison_ids",
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
        resolved = tuple(available_results[item] for item in result_ids)
        self._validate_claim_compatibility(claim_type, resolved)
        canonical = self._canonical_claim_fields(claim_type, resolved)
        self._validate_legacy_authority_fields(raw, canonical, claim_type)
        value = canonical["value"]
        provider_text = self._safe_text(str(raw["finding_text"]), "finding text")
        self._validate_prose_numbers(provider_text, canonical["allowed_prose_numbers"])
        context = semantic_evidence_contexts.get(result_ids[0]) if len(result_ids) == 1 else None
        text = provider_text
        if context is not None:
            self._validate_provider_semantic_prose(provider_text, context, claim_type)
            text = self._project_canonical_semantic_context(provider_text, context)
        limitation = raw.get("limitation_note")
        if limitation is not None:
            self._safe_text(str(limitation), "limitation note")
        pii = self._pii_exposures(text)
        identity_proposal = {
            "claim_type": claim_type.value,
            "finding_text": text,
            "selected_result_ids": result_ids,
            "selected_comparison_ids": comparison_ids,
            "limitation_note": None if limitation is None else str(limitation),
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
                variable_id=canonical["variable_id"],
                statistic_type=canonical["statistic_type"],
                category_value=canonical["category_value"],
                filter_definition=canonical["filter_definition"],
                base_definition=canonical["base_definition"],
                weighting_status=canonical["weighting_status"],
                weight_set_fingerprint=canonical["weight_set_fingerprint"],
                direction=canonical["direction"],
                display_value=canonical["display_value"],
            ),
            statistical_result_refs=result_refs,
            comparison_result_refs=comparison_refs,
            rounding_decimal_places=1,
            pii_exposures=pii,
            semantic_evidence_context=context,
        )

    @staticmethod
    def _validate_provider_semantic_prose(text, context, claim_type):
        normalized = " ".join(text.casefold().replace(",", "").split())
        if claim_type is not QuantitativeClaimType.SIGNIFICANT_COMPARISON and re.search(
            r"\b(?:statistically significant|significant difference|significantly)\b", normalized
        ):
            raise QuantitativeAnalysisError("Finding prose claims unsupported significance")
        if re.search(
            r"\b(?:causes?|caused|causing|drives?|drove|led to|leads to|results? in|because of|due to)\b",
            normalized,
        ):
            raise QuantitativeAnalysisError("Finding prose claims unsupported causality")
        population = QuantitativeFindingGenerationService._normalize_semantic_text(
            context.population_description
        )
        population_terms = re.compile(
            r"\b(?:among|amongst|of|for)\s+(?:the\s+)?(?:all\s+)?"
            r"[^,.;:]{0,80}?\b(?:respondents?|consumers?|users?|participants?|adults?|"
            r"households|customers?|population)\b"
        )
        if population_terms.search(normalized) and (not population or population not in normalized):
            raise QuantitativeAnalysisError(
                "Finding prose contradicts or fabricates canonical population context"
            )
        contract_terms = {
            "weighted": context.weighting_status.casefold() == "weighted",
            "unweighted": context.weighting_status.casefold() == "unweighted",
            "all_rows": context.filter_definition.casefold() == "all_rows",
            "filtered": context.filter_definition.casefold() == "filtered",
            "valid_responses": context.base_definition.casefold() == "valid_responses",
            "all_responses": context.base_definition.casefold() == "all_responses",
        }
        tokenized = normalized.replace("-", "_").replace(" ", "_")
        for term, canonical_match in contract_terms.items():
            mentioned = (
                bool(re.search(r"\bweighted\b", normalized))
                if term == "weighted"
                else term in tokenized
            )
            if mentioned and not canonical_match:
                raise QuantitativeAnalysisError(
                    "Finding prose contradicts canonical filter/base/weighting context"
                )

    @staticmethod
    def _project_canonical_semantic_context(text, context):
        fields = (
            ("context", context.context_id),
            ("question", context.question_context),
            ("category", context.category_label),
            ("value", context.display_value),
            ("denominator", context.denominator),
            ("filter", context.filter_definition),
            ("base", context.base_definition),
            ("weighting", context.weighting_status),
        )
        if context.population_description is not None:
            fields += (("population", context.population_description),)
        rendered = "; ".join(f"{name}={value}" for name, value in fields)
        return f"{text} [Canonical quantitative context: {rendered}.]"

    @staticmethod
    def _normalize_semantic_text(value):
        if value is None:
            return ""
        return " ".join(str(value).casefold().replace(",", "").split())

    @staticmethod
    def _allowed_claim_types(statistic_type):
        if statistic_type in {
            "VALID_PERCENTAGE", "WEIGHTED_PERCENTAGE", "CROSS_TAB_COLUMN_PERCENTAGE",
        }:
            return (
                QuantitativeClaimType.DESCRIPTIVE_VALUE.value,
                QuantitativeClaimType.DESCRIPTIVE_COMPARISON.value,
                QuantitativeClaimType.SIGNIFICANT_COMPARISON.value,
            )
        if statistic_type in {
            "NUMERIC_MEAN", "NUMERIC_WEIGHTED_MEAN", "NUMERIC_MEDIAN",
            "NUMERIC_MINIMUM", "NUMERIC_MAXIMUM",
        }:
            return (QuantitativeClaimType.NUMERIC_SUMMARY.value,)
        if statistic_type in {"NPS", "CUSTOM_INDEX"}:
            return (QuantitativeClaimType.KPI_VALUE.value,)
        return ()

    @classmethod
    def _validate_claim_compatibility(cls, claim_type, results):
        if claim_type not in {
            QuantitativeClaimType.DESCRIPTIVE_COMPARISON,
            QuantitativeClaimType.SIGNIFICANT_COMPARISON,
        } and any(not item.presentation_eligible for item in results):
            raise QuantitativeAnalysisError(
                "ineligible result cannot support a standalone Finding"
            )
        if claim_type in {
            QuantitativeClaimType.DESCRIPTIVE_COMPARISON,
            QuantitativeClaimType.SIGNIFICANT_COMPARISON,
        }:
            if not results or any(
                item.statistic_type not in {
                    "VALID_PERCENTAGE", "WEIGHTED_PERCENTAGE",
                    "CROSS_TAB_COLUMN_PERCENTAGE",
                }
                for item in results
            ):
                raise QuantitativeAnalysisError(
                    "selected results are incompatible with comparison Finding claim"
                )
            return
        if len(results) != 1 or claim_type.value not in cls._allowed_claim_types(
            results[0].statistic_type
        ):
            raise QuantitativeAnalysisError(
                "selected result is incompatible with Finding claim type"
            )

    @classmethod
    def _canonical_claim_fields(cls, claim_type, results):
        first = results[0]
        if claim_type in {
            QuantitativeClaimType.DESCRIPTIVE_COMPARISON,
            QuantitativeClaimType.SIGNIFICANT_COMPARISON,
        }:
            value = Decimal(str(first.value)) - Decimal(str(results[1].value))
            direction = "HIGHER" if value > 0 else "LOWER" if value < 0 else "EQUAL"
            category = first.row_category_value
        else:
            value = Decimal(str(first.value))
            direction = None
            category = first.category_value
        allowed_prose_numbers = {
            QuantitativeFindingSupportValidator.display_value(
                Decimal(str(item.value)), decimal_places=1
            )
            for item in results
        }
        for item in results:
            for candidate in (
                item.category_value,
                item.row_category_value,
                item.column_category_value,
                item.denominator,
                item.unweighted_n,
            ):
                rendered = cls._canonical_prose_number(candidate)
                if rendered is not None:
                    allowed_prose_numbers.add(rendered)
        allowed_prose_numbers.add(
            QuantitativeFindingSupportValidator.display_value(value, decimal_places=1)
        )
        return {
            "value": value,
            "variable_id": first.variable_id,
            "statistic_type": first.statistic_type,
            "category_value": category,
            "filter_definition": first.filter_definition,
            "base_definition": first.base_definition,
            "weighting_status": first.weighting_status,
            "weight_set_fingerprint": first.weight_set_fingerprint,
            "direction": direction,
            "display_value": QuantitativeFindingSupportValidator.display_value(
                value, decimal_places=1
            ),
            "allowed_prose_numbers": frozenset(allowed_prose_numbers),
        }

    @classmethod
    def _validate_legacy_authority_fields(cls, raw, canonical, claim_type):
        comparisons = {
            "value": lambda actual, expected: cls._decimal_or_none(actual) == expected,
            "variable_id": lambda actual, expected: str(actual) == expected,
            "statistic_type": lambda actual, expected: str(actual) == expected,
            "category_value": lambda actual, expected: actual == expected,
            "filter_definition": lambda actual, expected: str(actual) == expected,
            "base_definition": lambda actual, expected: str(actual) == expected,
            "weighting_status": lambda actual, expected: str(actual) == expected,
            "weight_set_fingerprint": lambda actual, expected: cls._optional_string(actual) == expected,
            "direction": lambda actual, expected: cls._optional_string(actual) == expected,
            "display_value": lambda actual, expected: cls._optional_string(actual) == expected,
        }
        for name, matches in comparisons.items():
            if name == "value" and raw.get(name) is None and claim_type in {
                QuantitativeClaimType.DESCRIPTIVE_COMPARISON,
                QuantitativeClaimType.SIGNIFICANT_COMPARISON,
            }:
                continue
            if name == "display_value" and claim_type in {
                QuantitativeClaimType.DESCRIPTIVE_COMPARISON,
                QuantitativeClaimType.SIGNIFICANT_COMPARISON,
            }:
                continue
            if name in raw and not matches(raw[name], canonical[name]):
                raise QuantitativeAnalysisError(
                    f"model-supplied {name} contradicts canonical support"
                )
        if "rounding_decimal_places" in raw and cls._integer(
            raw["rounding_decimal_places"]
        ) != 1:
            raise QuantitativeAnalysisError(
                "model-supplied rounding precision contradicts canonical support"
            )

    @staticmethod
    def _validate_prose_numbers(text, allowed_numbers):
        numeric_tokens = re.findall(
            r"(?<![\w-])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s*%)?(?![\w-])",
            text,
        )
        for token in numeric_tokens:
            rendered = token.rstrip().removesuffix("%").strip().replace(",", "")
            if rendered not in allowed_numbers:
                raise QuantitativeAnalysisError(
                    "Finding prose contains a number outside canonical display support"
                )

    @staticmethod
    def _canonical_prose_number(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
        if not number.is_finite():
            return None
        rendered = format(number.normalize(), "f")
        return "0" if rendered == "-0" else rendered

    @classmethod
    def _selected_ids(cls, raw, *, canonical_name, legacy_name):
        return cls._string_list(
            cls._selected_value(
                raw,
                canonical_name=canonical_name,
                legacy_name=legacy_name,
            ),
            canonical_name,
        )

    @staticmethod
    def _selected_value(raw, *, canonical_name, legacy_name, default=None):
        has_canonical = canonical_name in raw
        has_legacy = legacy_name in raw
        if has_canonical and has_legacy and raw[canonical_name] != raw[legacy_name]:
            raise QuantitativeAnalysisError("conflicting Finding support selectors")
        if has_canonical:
            return raw[canonical_name]
        if has_legacy:
            return raw[legacy_name]
        return default

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
