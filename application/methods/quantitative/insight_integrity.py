"""Additional fail-closed interpretation rules for newly pinned CMF Quant runs."""

from __future__ import annotations

import re
from dataclasses import replace

from application.quantitative.insight_synthesis import QuantitativeInsightValidator
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.finding import QuantitativeClaimType


class CanonicalQuantInsightValidator(QuantitativeInsightValidator):
    def __init__(self, *, digest_provider, require_canonical_authority=False):
        super().__init__(digest_provider=digest_provider)
        self._require_canonical_authority = require_canonical_authority

    def validate(self, insight, *, findings, allow_interpretive_compatibility=False):
        supports = self._resolve(insight, findings)
        if self._require_canonical_authority and any(
            item.canonical_authority is None for item in supports
        ):
            raise QuantitativeAnalysisError("Insight lacks canonical Quant Finding authority")
        authorities = tuple(item.canonical_authority for item in supports
                            if item.canonical_authority is not None)
        if authorities and len({(item.run_id, item.dataset_version_id,
                                item.dataset_fingerprint) for item in authorities}) != 1:
            raise QuantitativeAnalysisError("Insight combines incompatible dataset authorities")
        text = " ".join((insight.insight_text, insight.limitation_note or ""))
        lowered = text.casefold()
        percent_values = {
            item.claim.display_value for item in supports
            if item.claim.statistic_type in {
                "VALID_PERCENTAGE", "WEIGHTED_PERCENTAGE",
                "CROSS_TAB_COLUMN_PERCENTAGE", "GROUPED_CATEGORY_PERCENTAGE",
            }
        }
        for match in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)%(?![\w.])", text):
            if match.group(1) not in percent_values:
                raise QuantitativeAnalysisError("percentage is not a bound percentage Finding")
        if re.search(r"\b(?:confidence interval|confidence bounds?|\d+%\s*ci)\b", lowered):
            raise QuantitativeAnalysisError("QNT V1 does not produce confidence intervals")
        affirmative = re.sub(
            r"\b(?:not|no)\s+(?:statistically\s+)?significant\b", "", lowered,
        )
        if re.search(r"\b(?:statistically significant|significant difference|significantly)\b", affirmative):
            if not any(item.claim.claim_type is QuantitativeClaimType.SIGNIFICANT_COMPARISON
                       for item in supports):
                raise QuantitativeAnalysisError("significance claim lacks canonical comparison")
        if re.search(r"\b(?:causes?|caused|causing|leads? to|led to|drives?|drove|resulted in)\b", lowered):
            raise QuantitativeAnalysisError("causal interpretation is unsupported")
        weights = {item.claim.weighting_status for item in supports}
        if ("weighted" in lowered and ("WEIGHTED" not in weights or len(weights) != 1)):
            # Match exact words below; "unweighted" contains "weighted" as a suffix.
            if re.search(r"\bweighted\b", lowered):
                raise QuantitativeAnalysisError("weighted interpretation contradicts Findings")
        if re.search(r"\bunweighted\b", lowered) and (
            "UNWEIGHTED" not in weights or len(weights) != 1
        ):
            raise QuantitativeAnalysisError("unweighted interpretation contradicts Findings")
        p_values = {str(entry[2]) for item in authorities for entry in item.significance}
        for match in re.finditer(r"\b(?:p\s*[=<]|p-value\s*(?:of|is)\s*)(\d+(?:\.\d+)?)", lowered):
            if match.group(1) not in p_values:
                raise QuantitativeAnalysisError("p-value is unavailable in the bound Finding contract")
        if re.search(r"\b(?:n|base|denominator)\s*[=:]\s*\d", lowered):
            allowed = {
                str(item.semantic_evidence_context.denominator)
                for item in supports if item.semantic_evidence_context is not None
            }
            allowed.update(str(item.source_n) for item in authorities)
            allowed.update(str(value) for item in authorities
                           for value in item.denominators if value is not None)
            for match in re.finditer(r"\b(?:n|base|denominator)\s*[=:]\s*(\d+)", lowered):
                if match.group(1) not in allowed:
                    raise QuantitativeAnalysisError("sample/base count lacks bound authority")
        self._validate_numbers(replace(insight, insight_text=text), supports)
        return super().validate(
            insight, findings=findings,
            allow_interpretive_compatibility=allow_interpretive_compatibility,
        )

    @staticmethod
    def _validate_numbers(insight, findings):
        supported = {item.claim.display_value for item in findings
                     if item.claim.display_value is not None}
        for finding in findings:
            authority = finding.canonical_authority
            if authority is None:
                continue
            supported.add(str(authority.source_n))
            supported.update(str(value) for value in authority.denominators
                             if value is not None)
            supported.update(str(entry[2]) for entry in authority.significance)
        if any(value not in supported for value in insight.referenced_display_values):
            raise QuantitativeAnalysisError("Insight references an unsupported numeric display value")
        numbers = tuple(match.group(0) for match in re.finditer(
            r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?(?![\w.])", insight.insight_text,
        ))
        normalized = tuple(value[:-1] if value.endswith("%") else value
                           for value in numbers)
        if any(value not in insight.referenced_display_values for value in normalized):
            raise QuantitativeAnalysisError("Insight text introduces an unsupported numeric value")

    @staticmethod
    def _validate_significance(insight, findings):
        text = re.sub(
            r"\b(?:not|no)\s+(?:statistically\s+)?significant\b", "",
            insight.insight_text.casefold(),
        )
        if re.search(r"\b(?:statistically significant|significant difference|significantly)\b", text):
            if not any(item.claim.claim_type is QuantitativeClaimType.SIGNIFICANT_COMPARISON
                       for item in findings):
                raise QuantitativeAnalysisError("significance wording lacks canonical comparison")
