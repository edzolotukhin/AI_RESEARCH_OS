from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Mapping, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.finding import (
    QuantitativeClaimType,
    QuantitativeFinding,
    QuantitativeSupportStatus,
)
from domain.quantitative.insight import (
    QuantitativeFindingReference,
    QuantitativeInsight,
    QuantitativeInsightGenerationResult,
    QuantitativeInsightRejection,
    QuantitativeInsightType,
    QuantitativeInsightValidationStatus,
)


PROMPT_VERSION = "QJ_INSIGHT_SYNTHESIS_V1"
VALIDATION_VERSION = "qj-1"
MAX_FINDINGS = 50
MAX_PROPOSALS = 20
MAX_PROMPT_CHARACTERS = 50_000


class QuantitativeInsightProposalGenerator(Protocol):
    @property
    def identity(self) -> str: ...

    def generate(self, prompt: str) -> Mapping[str, Any]: ...


class QuantitativeInsightValidator:
    def __init__(self, *, digest_provider: DeterministicDigestProvider) -> None:
        self._digest = digest_provider

    def validate(
        self,
        insight: QuantitativeInsight,
        *,
        findings: Mapping[str, QuantitativeFinding],
    ) -> QuantitativeInsight:
        if insight.methodology != "QUANTITATIVE" or not insight.insight_text.strip():
            raise QuantitativeAnalysisError("invalid Quantitative Insight identity or methodology")
        supports = self._resolve(insight, findings)
        contexts = {item.analytical_context_fingerprint for item in supports}
        if "" in contexts or len(contexts) != 1:
            raise QuantitativeAnalysisError("supporting Findings have incompatible analytical contexts")
        if self._pii_exposures(insight.insight_text) or (
            insight.limitation_note and self._pii_exposures(insight.limitation_note)
        ):
            raise QuantitativeAnalysisError("Quantitative Insight contains direct PII")
        if self._contains_causal_language(insight.insight_text):
            raise QuantitativeAnalysisError("causal wording is unsupported by observational Quantitative Findings")
        self._validate_numbers(insight, supports)
        self._validate_significance(insight, supports)
        self._validate_type(insight, supports)

        context = next(iter(contexts))
        fingerprint = canonical_digest(
            {
                "insight_id": insight.insight_id,
                "type": insight.insight_type.value,
                "text": insight.insight_text,
                "supports": tuple(
                    (item.finding_id, item.support_validation_fingerprint)
                    for item in supports
                ),
                "referenced_display_values": insight.referenced_display_values,
                "direction": insight.direction,
                "limitation_note": insight.limitation_note,
                "context": context,
                "version": VALIDATION_VERSION,
            },
            digest_provider=self._digest,
        )
        return replace(
            insight,
            support_context_fingerprint=context,
            validation_status=QuantitativeInsightValidationStatus.SUPPORTED,
            validation_fingerprint=fingerprint,
            validation_version=VALIDATION_VERSION,
        )

    @staticmethod
    def _resolve(insight, available):
        if not insight.supporting_finding_refs:
            raise QuantitativeAnalysisError("Insight requires supporting Quantitative Findings")
        resolved = []
        seen = set()
        for reference in insight.supporting_finding_refs:
            finding = available.get(reference.finding_id)
            if finding is None:
                raise QuantitativeAnalysisError("supporting Finding is missing")
            if finding.support_validation_status is not QuantitativeSupportStatus.SUPPORTED:
                raise QuantitativeAnalysisError("rejected or unvalidated Finding cannot support Insight")
            if finding.support_validation_fingerprint != reference.support_validation_fingerprint:
                raise QuantitativeAnalysisError("supporting Finding is stale or altered")
            if finding.finding_id in seen:
                raise QuantitativeAnalysisError("duplicate supporting Finding reference")
            seen.add(finding.finding_id)
            resolved.append(finding)
        return tuple(resolved)

    @staticmethod
    def _validate_numbers(insight, findings):
        supported = {
            item.claim.display_value
            for item in findings
            if item.claim.display_value is not None
        }
        if any(value not in supported for value in insight.referenced_display_values):
            raise QuantitativeAnalysisError("Insight references an unsupported numeric display value")
        numbers = tuple(match.group(0) for match in re.finditer(r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?(?![\w.])", insight.insight_text))
        normalized = tuple(value[:-1] if value.endswith("%") else value for value in numbers)
        if any(value not in insight.referenced_display_values for value in normalized):
            raise QuantitativeAnalysisError("Insight text introduces an unsupported numeric value")

    @staticmethod
    def _validate_significance(insight, findings):
        claims_significance = bool(re.search(
            r"\b(statistically significant|significantly (?:higher|lower|different))\b",
            insight.insight_text,
            re.IGNORECASE,
        ))
        if claims_significance and not any(
            item.claim.claim_type is QuantitativeClaimType.SIGNIFICANT_COMPARISON
            for item in findings
        ):
            raise QuantitativeAnalysisError("significance wording lacks an accepted significant Finding")

    @staticmethod
    def _validate_type(insight, findings):
        if insight.insight_type is QuantitativeInsightType.SEGMENT_CONTRAST:
            directions = {
                item.claim.direction
                for item in findings
                if item.claim.claim_type in {
                    QuantitativeClaimType.DESCRIPTIVE_COMPARISON,
                    QuantitativeClaimType.SIGNIFICANT_COMPARISON,
                }
            }
            if not insight.direction or insight.direction not in directions:
                raise QuantitativeAnalysisError("segment contrast direction is unsupported or contradicted")
        elif insight.insight_type is QuantitativeInsightType.KPI_INTERPRETATION:
            if not any(item.claim.claim_type is QuantitativeClaimType.KPI_VALUE for item in findings):
                raise QuantitativeAnalysisError("KPI interpretation requires an accepted KPI Finding")
        elif insight.insight_type is QuantitativeInsightType.LIMITATION:
            if not insight.limitation_note:
                raise QuantitativeAnalysisError("limitation Insight requires an explicit limitation note")

    @staticmethod
    def _contains_causal_language(text):
        return bool(re.search(r"\b(causes?|caused|leads? to|led to|drives?|drove)\b", text, re.IGNORECASE))

    @staticmethod
    def _pii_exposures(text):
        return bool(
            re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE)
            or re.search(r"(?<!\w)(?:\+?\d[\d .()/-]{7,}\d)(?!\w)", text)
        )


class QuantitativeInsightSynthesisService:
    def __init__(
        self,
        *,
        generator: QuantitativeInsightProposalGenerator,
        validator: QuantitativeInsightValidator,
        digest_provider: DeterministicDigestProvider,
    ) -> None:
        self._generator = generator
        self._validator = validator
        self._digest = digest_provider

    def generate(self, *, findings: Sequence[QuantitativeFinding]) -> QuantitativeInsightGenerationResult:
        accepted = self._accepted_findings(findings)
        available = {item.finding_id: item for item in accepted}
        bundle = tuple(self._finding_projection(item) for item in accepted)
        bundle_fingerprint = canonical_digest(bundle, digest_provider=self._digest)
        prompt = self._prompt(bundle)
        prompt_fingerprint = canonical_digest(
            {"version": PROMPT_VERSION, "prompt": prompt},
            digest_provider=self._digest,
        )
        raw = self._generator.generate(prompt)
        proposals = self._proposal_list(raw)
        parsed: list[QuantitativeInsight] = []
        validated: list[QuantitativeInsight] = []
        rejected: list[QuantitativeInsightRejection] = []
        for ordinal, proposal in enumerate(proposals, start=1):
            payload = dict(proposal) if isinstance(proposal, Mapping) else {"raw_type": type(proposal).__name__}
            try:
                insight = self._parse(proposal, ordinal, bundle_fingerprint, available)
                parsed.append(insight)
                validated.append(self._validator.validate(insight, findings=available))
            except (QuantitativeAnalysisError, ValueError, TypeError, KeyError) as exc:
                reason = f"{type(exc).__name__}: {exc}"
                rejected.append(QuantitativeInsightRejection(
                    ordinal,
                    payload,
                    reason,
                    canonical_digest(
                        {"bundle": bundle_fingerprint, "ordinal": ordinal, "proposal": payload, "reason": reason, "version": PROMPT_VERSION},
                        digest_provider=self._digest,
                    ),
                ))
        summary = {"proposed": len(proposals), "parsed": len(parsed), "accepted": len(validated), "rejected": len(rejected)}
        generation_fingerprint = canonical_digest(
            {
                "bundle": bundle_fingerprint,
                "generator": self._generator.identity,
                "prompt": prompt_fingerprint,
                "accepted": tuple(item.validation_fingerprint for item in validated),
                "rejected": tuple(item.rejection_fingerprint for item in rejected),
                "summary": summary,
                "version": PROMPT_VERSION,
            },
            digest_provider=self._digest,
        )
        return QuantitativeInsightGenerationResult(
            str(uuid5(NAMESPACE_URL, f"qj-generation:{generation_fingerprint}")),
            bundle_fingerprint,
            self._generator.identity,
            PROMPT_VERSION,
            prompt_fingerprint,
            tuple(parsed),
            tuple(validated),
            tuple(rejected),
            {"generation_passes": 1, "repair_attempts": 0},
            summary,
            generation_fingerprint,
        )

    @staticmethod
    def _accepted_findings(findings):
        if not findings or len(findings) > MAX_FINDINGS:
            raise QuantitativeAnalysisError("accepted Finding bundle must be non-empty and bounded")
        ids = [item.finding_id for item in findings]
        if len(ids) != len(set(ids)) or any(
            item.methodology != "QUANTITATIVE"
            or item.support_validation_status is not QuantitativeSupportStatus.SUPPORTED
            or not item.support_validation_fingerprint
            or not item.analytical_context_fingerprint
            for item in findings
        ):
            raise QuantitativeAnalysisError("Insight input contains duplicate, rejected, or stale Findings")
        return tuple(findings)

    @staticmethod
    def _finding_projection(item):
        return {
            "finding_id": item.finding_id,
            "support_validation_fingerprint": item.support_validation_fingerprint,
            "analytical_context_fingerprint": item.analytical_context_fingerprint,
            "claim_type": item.claim.claim_type.value,
            "finding_text": item.text,
            "display_value": item.claim.display_value,
            "direction": item.claim.direction,
            "filter_definition": item.claim.filter_definition,
            "base_definition": item.claim.base_definition,
            "weighting_status": item.claim.weighting_status,
            "weight_set_fingerprint": item.claim.weight_set_fingerprint,
        }

    @staticmethod
    def _prompt(bundle):
        instructions = (
            "Synthesize structured Quantitative Insights using only supplied accepted Finding IDs. "
            "Do not invent or recalculate numbers; every number must exactly match a supplied display_value "
            "and be listed in referenced_display_values. Do not upgrade observed differences to significance; "
            "significance wording requires an accepted SIGNIFICANT_COMPARISON Finding. Preserve weighting, "
            "filters, bases, populations, and direction. Do not infer causality or introduce unsupported "
            "segments. Use one of SYNTHESIS, SEGMENT_CONTRAST, KPI_INTERPRETATION, LIMITATION."
        )
        schema = {"proposals": [{"insight_type": "SYNTHESIS|SEGMENT_CONTRAST|KPI_INTERPRETATION|LIMITATION", "insight_text": "string", "supporting_finding_refs": ["finding-id"], "supporting_finding_fingerprints": {"finding-id": "expected-fingerprint"}, "referenced_display_values": ["exact display value"], "direction": "HIGHER|LOWER|EQUAL|null", "limitation_note": "string or null"}]}
        prompt = instructions + "\nOUTPUT_SCHEMA=" + json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\nACCEPTED_FINDINGS=" + json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise QuantitativeAnalysisError("Quantitative Insight prompt exceeds bounded size")
        return prompt

    @staticmethod
    def _proposal_list(raw):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("proposals"), list) or len(raw["proposals"]) > MAX_PROPOSALS:
            raise QuantitativeAnalysisError("structured Insight output requires a bounded proposals array")
        return tuple(raw["proposals"])

    def _parse(self, raw, ordinal, bundle_fingerprint, available):
        if not isinstance(raw, Mapping):
            raise QuantitativeAnalysisError("Insight proposal must be an object")
        finding_ids = self._strings(raw.get("supporting_finding_refs"), "supporting_finding_refs")
        expected = raw.get("supporting_finding_fingerprints") or {}
        if not isinstance(expected, Mapping):
            raise QuantitativeAnalysisError("supporting Finding fingerprints must be an object")
        refs = tuple(QuantitativeFindingReference(
            item,
            str(expected.get(item) or (available[item].support_validation_fingerprint if item in available else "UNAVAILABLE")),
        ) for item in finding_ids)
        display_values = self._strings(raw.get("referenced_display_values", []), "referenced_display_values", allow_empty=True)
        text = self._bounded_text(raw["insight_text"], "insight_text")
        limitation = raw.get("limitation_note")
        limitation = None if limitation is None else self._bounded_text(limitation, "limitation_note")
        identity = canonical_digest(
            {"bundle": bundle_fingerprint, "ordinal": ordinal, "proposal": dict(raw)},
            digest_provider=self._digest,
        )
        return QuantitativeInsight(
            str(uuid5(NAMESPACE_URL, f"qj-insight:{identity}")),
            text,
            QuantitativeInsightType(str(raw["insight_type"])),
            refs,
            display_values,
            None if raw.get("direction") is None else str(raw["direction"]),
            limitation,
        )

    @staticmethod
    def _strings(value, name, *, allow_empty=False):
        if not isinstance(value, list) or (not value and not allow_empty) or any(not isinstance(item, str) or not item for item in value) or len(value) != len(set(value)):
            raise QuantitativeAnalysisError(f"{name} must be a unique string array")
        return tuple(value)

    @staticmethod
    def _bounded_text(value, name):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1000:
            raise QuantitativeAnalysisError(f"{name} must be a bounded non-empty string")
        return value.strip()
