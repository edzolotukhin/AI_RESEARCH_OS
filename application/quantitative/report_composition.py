from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Mapping, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.one_way_statistics import QuantitativeAnalysisError
from domain.quantitative.finding import QuantitativeClaimType, QuantitativeFinding, QuantitativeSupportStatus
from domain.quantitative.insight import (
    QuantitativeInsight, QuantitativeInsightCompatibilityMode,
    QuantitativeInsightValidationStatus,
)
from domain.quantitative.report import (
    QuantitativeReport,
    QuantitativeReportClaimSupportMode,
    QuantitativeReportClaimUnit,
    QuantitativeReportCompositionResult,
    QuantitativeReportRejection,
    QuantitativeReportSection,
    QuantitativeReportSectionType,
    QuantitativeReportSupportReference,
    QuantitativeReportValidationStatus,
)


PROMPT_VERSION = "QK_REPORT_COMPOSITION_V1"
DESIGN_AWARE_PROMPT_VERSION = "QK_REPORT_COMPOSITION_V2"
DERIVED_CLAIM_PROMPT_VERSION = "QK_REPORT_COMPOSITION_V4"
VALIDATION_VERSION = "qk-1"
CLAIM_VALIDATION_VERSION = "qk-2"
DERIVED_CLAIM_VALIDATION_VERSION = "qk-3"
MAX_FINDINGS = 75
MAX_INSIGHTS = 50
MAX_SECTIONS = 12
MAX_PROMPT_CHARACTERS = 75_000


class QuantitativeReportProposalGenerator(Protocol):
    @property
    def identity(self) -> str: ...

    def generate(self, prompt: str) -> Mapping[str, Any]: ...


class QuantitativeReportValidator:
    def __init__(self, *, digest_provider: DeterministicDigestProvider) -> None:
        self._digest = digest_provider

    def validate(self, report, *, findings, insights):
        if report.methodology != "QUANTITATIVE" or not report.title.strip() or not report.sections:
            raise QuantitativeAnalysisError("invalid Quantitative Report identity or structure")
        report_findings = self._resolve_findings(report.supporting_finding_refs, findings)
        report_insights = self._resolve_insights(report.supporting_insight_refs, insights, findings)
        finding_ids = {item.finding_id for item in report_findings}
        insight_ids = {item.insight_id for item in report_insights}
        if any(
            support.finding_id not in finding_ids
            for insight in report_insights
            for support in insight.supporting_finding_refs
        ):
            raise QuantitativeAnalysisError("Insight support chain falls outside the Report Finding bundle")
        section_ids = [item.section_id for item in report.sections]
        if len(section_ids) != len(set(section_ids)):
            raise QuantitativeAnalysisError("Report section IDs must be unique")
        for section in report.sections:
            section_findings = self._resolve_findings(section.finding_refs, findings)
            section_insights = self._resolve_insights(section.insight_refs, insights, findings)
            if any(item.finding_id not in finding_ids for item in section_findings) or any(item.insight_id not in insight_ids for item in section_insights):
                raise QuantitativeAnalysisError("section references support outside the Report bundle")
            chain_findings = self._support_chain(section_findings, section_insights, findings)
            if section.claim_units:
                self._validate_claim_units(section, section_findings, section_insights, findings, insights, derived=report.generation_version == DERIVED_CLAIM_VALIDATION_VERSION)
            else:
                self._validate_section(section, chain_findings, section_insights)
        support_fingerprint = canonical_digest(
            {
                "findings": tuple((item.finding_id, item.support_validation_fingerprint) for item in report_findings),
                "insights": tuple((item.insight_id, item.validation_fingerprint) for item in report_insights),
            },
            digest_provider=self._digest,
        )
        validation_version = (
            DERIVED_CLAIM_VALIDATION_VERSION
            if report.generation_version == DERIVED_CLAIM_VALIDATION_VERSION
            else CLAIM_VALIDATION_VERSION
            if any(item.claim_units for item in report.sections)
            else VALIDATION_VERSION
        )
        validation_fingerprint = canonical_digest(
            {
                "report_id": report.report_id,
                "title": report.title,
                "sections": tuple(self._section_payload(item) for item in report.sections),
                "support": support_fingerprint,
                "version": validation_version,
            },
            digest_provider=self._digest,
        )
        return replace(
            report,
            analytical_support_fingerprint=support_fingerprint,
            validation_status=QuantitativeReportValidationStatus.SUPPORTED,
            validation_fingerprint=validation_fingerprint,
            generation_version=validation_version,
        )

    def _validate_claim_units(self, section, section_findings, section_insights, findings, insights, *, derived=False):
        narrative = " ".join(item.text.strip() for item in section.claim_units) if derived else "".join(item.text for item in section.claim_units)
        if narrative != section.narrative:
            raise QuantitativeAnalysisError("Report claim units must exactly partition section narrative")
        if len({item.claim_id for item in section.claim_units}) != len(section.claim_units):
            raise QuantitativeAnalysisError("Report claim unit IDs must be unique")
        section_finding_ids = {item.finding_id for item in section_findings}
        section_insight_ids = {item.insight_id for item in section_insights}
        used_findings, used_insights = set(), set()
        for unit in section.claim_units:
            unit_findings = self._resolve_findings(unit.finding_refs, findings)
            unit_insights = self._resolve_insights(unit.insight_refs, insights, findings)
            finding_ids = {item.finding_id for item in unit_findings}
            insight_ids = {item.insight_id for item in unit_insights}
            if not finding_ids or not finding_ids.issubset(section_finding_ids) or not insight_ids.issubset(section_insight_ids):
                raise QuantitativeAnalysisError("Report claim support falls outside section authority")
            used_findings.update(finding_ids)
            used_insights.update(insight_ids)
            if unit.support_mode is QuantitativeReportClaimSupportMode.DIRECT_FINDING:
                if len(unit_findings) != 1 or unit_insights:
                    raise QuantitativeAnalysisError("direct Report claim requires exactly one Finding")
            else:
                if not unit_insights:
                    raise QuantitativeAnalysisError("relational Report claim requires Insight authority")
                if unit.support_mode is QuantitativeReportClaimSupportMode.INTERPRETIVE_COMPATIBILITY_INSIGHT:
                    governing = tuple(item for item in unit_insights if item.compatibility_mode == QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value and item.compatibility_authority_id and item.compatibility_authority_fingerprint and finding_ids.issubset({ref.finding_id for ref in item.supporting_finding_refs}))
                else:
                    governing = tuple(item for item in unit_insights if len({finding.analytical_context_fingerprint for finding in unit_findings}) == 1 and finding_ids.issubset({ref.finding_id for ref in item.supporting_finding_refs}))
                if not governing:
                    raise QuantitativeAnalysisError("Report relationship lacks complete governed Insight authority")
            if not derived:
                self._validate_section(replace(section, narrative=unit.text, referenced_display_values=unit.referenced_display_values, authoritative_result_refs=unit.authoritative_result_refs, claim_units=()), unit_findings, unit_insights)
        if used_findings != section_finding_ids or used_insights != section_insight_ids:
            raise QuantitativeAnalysisError("Report section contains unattributed support")

    def validate_derived_claim_units(self, report, *, findings, insights):
        if report.generation_version != DERIVED_CLAIM_VALIDATION_VERSION:
            raise QuantitativeAnalysisError("derived Report requires qk-3 authority")
        for section in report.sections:
            if not section.claim_units:
                raise QuantitativeAnalysisError("qk-3 Report sections require governed claim units")
            for unit in section.claim_units:
                unit_findings = self._resolve_findings(unit.finding_refs, findings)
                unit_insights = self._resolve_insights(unit.insight_refs, insights, findings)
                if unit.support_mode is QuantitativeReportClaimSupportMode.DIRECT_FINDING:
                    if len(unit_findings) != 1 or unit_insights or unit.text != unit_findings[0].text:
                        raise QuantitativeAnalysisError("qk-3 direct claim must exactly reproduce one governed Finding")
                else:
                    if len(unit_insights) != 1 or unit.text != unit_insights[0].insight_text:
                        raise QuantitativeAnalysisError("qk-3 relational claim must exactly reproduce one governed Insight")
                    required = {item.finding_id for item in unit_insights[0].supporting_finding_refs}
                    supplied = {item.finding_id for item in unit_findings}
                    if supplied != required:
                        raise QuantitativeAnalysisError("qk-3 relational claim requires the complete Insight support set")
        return self.validate(report, findings=findings, insights=insights)

    @staticmethod
    def _resolve_findings(refs, available):
        resolved = []
        for ref in refs:
            item = available.get(ref.authority_id)
            if item is None:
                raise QuantitativeAnalysisError("Report references a missing Finding")
            if item.support_validation_status is not QuantitativeSupportStatus.SUPPORTED:
                raise QuantitativeAnalysisError("rejected Finding cannot support Report")
            if item.support_validation_fingerprint != ref.validation_fingerprint:
                raise QuantitativeAnalysisError("Report references a stale Finding")
            resolved.append(item)
        if len({item.finding_id for item in resolved}) != len(resolved):
            raise QuantitativeAnalysisError("duplicate Finding reference")
        return tuple(resolved)

    @staticmethod
    def _resolve_insights(refs, available, findings):
        resolved = []
        for ref in refs:
            item = available.get(ref.authority_id)
            if item is None:
                raise QuantitativeAnalysisError("Report references a missing Insight")
            if item.validation_status is not QuantitativeInsightValidationStatus.SUPPORTED:
                raise QuantitativeAnalysisError("rejected Insight cannot support Report")
            if item.validation_fingerprint != ref.validation_fingerprint:
                raise QuantitativeAnalysisError("Report references a stale Insight")
            for support in item.supporting_finding_refs:
                finding = findings.get(support.finding_id)
                if finding is None or finding.support_validation_status is not QuantitativeSupportStatus.SUPPORTED or finding.support_validation_fingerprint != support.support_validation_fingerprint:
                    raise QuantitativeAnalysisError("Insight support chain is missing, stale, or rejected")
            resolved.append(item)
        if len({item.insight_id for item in resolved}) != len(resolved):
            raise QuantitativeAnalysisError("duplicate Insight reference")
        return tuple(resolved)

    @staticmethod
    def _support_chain(direct, insights, findings):
        chain = {item.finding_id: item for item in direct}
        for insight in insights:
            for ref in insight.supporting_finding_refs:
                chain[ref.finding_id] = findings[ref.finding_id]
        if not chain:
            raise QuantitativeAnalysisError("Report section has no authoritative support")
        return tuple(chain.values())

    def _validate_section(self, section, findings, insights):
        if not section.title.strip() or not section.narrative.strip():
            raise QuantitativeAnalysisError("Report section title and narrative are required")
        contexts = {item.analytical_context_fingerprint for item in findings}
        if "" in contexts:
            raise QuantitativeAnalysisError("Report section combines incompatible analytical contexts")
        if len(contexts) != 1:
            finding_ids = {item.finding_id for item in findings}
            governed = tuple(
                item for item in insights
                if (
                    item.compatibility_mode
                    == QuantitativeInsightCompatibilityMode.INTERPRETIVE_COMPATIBILITY.value
                    and item.compatibility_authority_id
                    and item.compatibility_authority_fingerprint
                )
            )
            governed_support = {
                reference.finding_id
                for insight in governed
                for reference in insight.supporting_finding_refs
            }
            if not governed or not finding_ids.issubset(governed_support):
                raise QuantitativeAnalysisError("Report section combines incompatible analytical contexts")
        claims = tuple(item.claim for item in findings)
        first = claims[0]
        if section.weighting_status != first.weighting_status or section.filter_definition != first.filter_definition or section.base_definition != first.base_definition:
            raise QuantitativeAnalysisError("Report section misrepresents weighting, population, filter, or base")
        if any(claim.weighting_status != first.weighting_status or claim.filter_definition != first.filter_definition or claim.base_definition != first.base_definition for claim in claims):
            raise QuantitativeAnalysisError("Report section support contexts are incompatible")
        supported_values = {claim.display_value for claim in claims if claim.display_value is not None}
        if any(item not in supported_values for item in section.referenced_display_values):
            raise QuantitativeAnalysisError("Report section references an unsupported display value")
        numbers = tuple(match.group(0) for match in re.finditer(r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?(?![\w.])", section.narrative))
        normalized = tuple(item[:-1] if item.endswith("%") else item for item in numbers)
        if any(item not in section.referenced_display_values for item in normalized):
            raise QuantitativeAnalysisError("Report narrative introduces an unsupported numeric value")
        if self._claims_significance(section.narrative) and not any(claim.claim_type is QuantitativeClaimType.SIGNIFICANT_COMPARISON for claim in claims):
            raise QuantitativeAnalysisError("Report significance wording lacks authoritative support")
        if self._contains_causality(section.narrative):
            raise QuantitativeAnalysisError("Report causal wording is unsupported")
        if self._contains_pii(section.narrative):
            raise QuantitativeAnalysisError("Report narrative contains direct PII")
        directions = {claim.direction for claim in claims if claim.direction}
        if section.section_type is QuantitativeReportSectionType.SEGMENT_RESULTS and (not section.direction or section.direction not in directions):
            raise QuantitativeAnalysisError("Report segment direction is unsupported or contradicted")
        if section.section_type is QuantitativeReportSectionType.KPI_RESULTS and not any(claim.claim_type is QuantitativeClaimType.KPI_VALUE for claim in claims):
            raise QuantitativeAnalysisError("KPI section lacks an authoritative KPI Finding")
        reachable_results = {ref.result_id for finding in findings for ref in finding.statistical_result_refs}
        if any(item not in reachable_results for item in section.authoritative_result_refs):
            raise QuantitativeAnalysisError("Report section references an unsupported result identity")
        if section.authoritative_table_refs:
            raise QuantitativeAnalysisError("table identities are not yet exposed by accepted Finding authority")

    @staticmethod
    def _claims_significance(text):
        return bool(re.search(r"\b(statistically significant|significantly (?:higher|lower|different))\b", text, re.IGNORECASE))

    @staticmethod
    def _contains_causality(text):
        return bool(re.search(r"\b(causes?|caused|leads? to|led to|drives?|drove)\b", text, re.IGNORECASE))

    @staticmethod
    def _contains_pii(text):
        return bool(re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE) or re.search(r"(?<!\w)(?:\+?\d[\d .()/-]{7,}\d)(?!\w)", text))

    @staticmethod
    def _section_payload(section):
        return {
            "id": section.section_id,
            "type": section.section_type.value,
            "title": section.title,
            "narrative": section.narrative,
            "findings": tuple((item.authority_id, item.validation_fingerprint) for item in section.finding_refs),
            "insights": tuple((item.authority_id, item.validation_fingerprint) for item in section.insight_refs),
            "values": section.referenced_display_values,
            "results": section.authoritative_result_refs,
            "tables": section.authoritative_table_refs,
            "weighting": section.weighting_status,
            "filter": section.filter_definition,
            "base": section.base_definition,
            "direction": section.direction,
            "claims": tuple((item.claim_id, item.text, item.support_mode.value, tuple((ref.authority_id, ref.validation_fingerprint) for ref in item.finding_refs), tuple((ref.authority_id, ref.validation_fingerprint) for ref in item.insight_refs), item.referenced_display_values, item.authoritative_result_refs) for item in section.claim_units),
        }


class QuantitativeReportCompositionService:
    def __init__(self, *, generator: QuantitativeReportProposalGenerator, validator: QuantitativeReportValidator, digest_provider: DeterministicDigestProvider) -> None:
        self._generator = generator
        self._validator = validator
        self._digest = digest_provider

    def compose(self, *, findings: Sequence[QuantitativeFinding], insights: Sequence[QuantitativeInsight]) -> QuantitativeReportCompositionResult:
        finding_map, insight_map = self._accepted_support(findings, insights)
        bundle = {"findings": tuple(self._finding_projection(item) for item in findings), "insights": tuple(self._insight_projection(item) for item in insights)}
        bundle_fp = canonical_digest(bundle, digest_provider=self._digest)
        prompt = self._prompt(bundle)
        prompt_fp = canonical_digest({"version": PROMPT_VERSION, "prompt": prompt}, digest_provider=self._digest)
        raw = self._generator.generate(prompt)
        proposed = None
        accepted = None
        rejected = []
        try:
            proposed = self._parse(raw, bundle_fp, finding_map, insight_map)
            accepted = self._validator.validate(proposed, findings=finding_map, insights=insight_map)
        except (QuantitativeAnalysisError, ValueError, TypeError, KeyError) as exc:
            payload = dict(raw) if isinstance(raw, Mapping) else {"raw_type": type(raw).__name__}
            reason = f"{type(exc).__name__}: {exc}"
            rejected.append(QuantitativeReportRejection(payload, reason, canonical_digest({"bundle": bundle_fp, "proposal": payload, "reason": reason, "version": PROMPT_VERSION}, digest_provider=self._digest)))
        composition_fp = canonical_digest({"bundle": bundle_fp, "generator": self._generator.identity, "prompt": prompt_fp, "accepted": accepted.validation_fingerprint if accepted else None, "rejected": tuple(item.rejection_fingerprint for item in rejected), "version": PROMPT_VERSION}, digest_provider=self._digest)
        return QuantitativeReportCompositionResult(str(uuid5(NAMESPACE_URL, f"qk-composition:{composition_fp}")), bundle_fp, self._generator.identity, PROMPT_VERSION, prompt_fp, proposed, accepted, tuple(rejected), {"generation_passes": 1, "repair_attempts": 0}, composition_fp)

    def compose_design_aware(
        self,
        *,
        findings: Sequence[QuantitativeFinding],
        insights: Sequence[QuantitativeInsight],
        bundle: Mapping[str, Any],
        post_validator=None,
    ) -> QuantitativeReportCompositionResult:
        finding_map, insight_map = self._accepted_support(findings, insights)
        if tuple(item.get("finding_id") for item in bundle.get("findings", ())) != tuple(sorted(finding_map)):
            raise QuantitativeAnalysisError("design-aware Report Finding bundle mismatch")
        if tuple(item.get("insight_id") for item in bundle.get("insights", ())) != tuple(sorted(insight_map)):
            raise QuantitativeAnalysisError("design-aware Report Insight bundle mismatch")
        bundle_fp = canonical_digest(bundle, digest_provider=self._digest)
        prompt = self._prompt_v3(bundle)
        prompt_fp = canonical_digest({"version": DERIVED_CLAIM_PROMPT_VERSION, "prompt": prompt}, digest_provider=self._digest)
        raw = self._generator.generate(prompt)
        proposed = None
        accepted = None
        rejected = []
        try:
            proposed = self._parse_v3(raw, bundle_fp, finding_map, insight_map)
            accepted = self._validator.validate_derived_claim_units(proposed, findings=finding_map, insights=insight_map)
            if post_validator is not None:
                accepted = post_validator(accepted)
        except (QuantitativeAnalysisError, ValueError, TypeError, KeyError) as exc:
            accepted = None
            payload = dict(raw) if isinstance(raw, Mapping) else {"raw_type": type(raw).__name__}
            reason = f"{type(exc).__name__}: {exc}"
            rejected.append(QuantitativeReportRejection(payload, reason, canonical_digest({"bundle": bundle_fp, "proposal": payload, "reason": reason, "version": DERIVED_CLAIM_PROMPT_VERSION}, digest_provider=self._digest)))
        composition_fp = canonical_digest({"bundle": bundle_fp, "generator": self._generator.identity, "prompt": prompt_fp, "accepted": accepted.validation_fingerprint if accepted else None, "rejected": tuple(item.rejection_fingerprint for item in rejected), "version": DERIVED_CLAIM_PROMPT_VERSION}, digest_provider=self._digest)
        return QuantitativeReportCompositionResult(str(uuid5(NAMESPACE_URL, f"qk-composition:{composition_fp}")), bundle_fp, self._generator.identity, DERIVED_CLAIM_PROMPT_VERSION, prompt_fp, proposed, accepted, tuple(rejected), {"generation_passes": 1, "repair_attempts": 0}, composition_fp)
    @staticmethod
    def _accepted_support(findings, insights):
        if not findings or len(findings) > MAX_FINDINGS or len(insights) > MAX_INSIGHTS:
            raise QuantitativeAnalysisError("Report support bundle is empty or exceeds bounds")
        finding_map = {item.finding_id: item for item in findings}
        insight_map = {item.insight_id: item for item in insights}
        if (
            len(finding_map) != len(findings)
            or len(insight_map) != len(insights)
            or any(
                item.support_validation_status is not QuantitativeSupportStatus.SUPPORTED
                or not item.support_validation_fingerprint
                for item in findings
            )
            or any(
                item.validation_status is not QuantitativeInsightValidationStatus.SUPPORTED
                or not item.validation_fingerprint
                for item in insights
            )
        ):
            raise QuantitativeAnalysisError("Report input contains duplicate or rejected support")
        return finding_map, insight_map

    @staticmethod
    def _finding_projection(item):
        return {"finding_id": item.finding_id, "validation_fingerprint": item.support_validation_fingerprint, "text": item.text, "claim_type": item.claim.claim_type.value, "display_value": item.claim.display_value, "direction": item.claim.direction, "context": item.analytical_context_fingerprint, "weighting": item.claim.weighting_status, "filter": item.claim.filter_definition, "base": item.claim.base_definition, "result_refs": tuple(ref.result_id for ref in item.statistical_result_refs)}

    @staticmethod
    def _insight_projection(item):
        return {"insight_id": item.insight_id, "validation_fingerprint": item.validation_fingerprint, "text": item.insight_text, "type": item.insight_type.value, "finding_refs": tuple(ref.finding_id for ref in item.supporting_finding_refs), "display_values": item.referenced_display_values, "context": item.support_context_fingerprint, "limitation": item.limitation_note}

    @staticmethod
    def _prompt(bundle):
        instructions = "Compose one structured Quantitative Report using only supplied accepted Finding and Insight IDs. Do not calculate or invent numbers; every narrative number must exactly match an approved display value and be listed explicitly. Preserve significance, direction, weighting, filters, bases, and populations. Do not infer causality or cite unsupported authority. Return a title and ordered sections only; no free-form report outside the schema."
        schema = {"title": "string", "finding_refs": ["id"], "finding_fingerprints": {"id": "fingerprint"}, "insight_refs": ["id"], "insight_fingerprints": {"id": "fingerprint"}, "sections": [{"section_id": "id", "section_type": "EXECUTIVE_SUMMARY|KEY_FINDINGS|SEGMENT_RESULTS|KPI_RESULTS|LIMITATIONS", "title": "string", "narrative": "string", "finding_refs": ["id"], "finding_fingerprints": {"id": "fingerprint"}, "insight_refs": ["id"], "insight_fingerprints": {"id": "fingerprint"}, "referenced_display_values": ["value"], "authoritative_result_refs": ["id"], "authoritative_table_refs": [], "weighting_status": "UNWEIGHTED|WEIGHTED", "filter_definition": "string", "base_definition": "string", "direction": "HIGHER|LOWER|EQUAL|null", "claim_units": [{"claim_id": "id", "text": "exact contiguous narrative text", "support_mode": "DIRECT_FINDING|EXACT_CONTEXT_INSIGHT|INTERPRETIVE_COMPATIBILITY_INSIGHT", "finding_refs": ["id"], "insight_refs": ["id"], "referenced_display_values": ["value"], "authoritative_result_refs": ["id"]}]}]}
        prompt = instructions + "\nOUTPUT_SCHEMA=" + json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\nAPPROVED_SUPPORT=" + json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise QuantitativeAnalysisError("Quantitative Report prompt exceeds bounded size")
        return prompt

    @staticmethod
    def _prompt_v2(bundle):
        instructions = "Compose one structured Quantitative Report using only supplied accepted Finding and Insight IDs. Do not return fingerprints, design IDs, lineage IDs, coverage states, answered flags, or objective-completion fields. Do not calculate or invent numbers; every narrative number must exactly match an approved display value and be listed explicitly. Preserve significance, direction, weighting, filters, bases, and populations. Do not infer causality or cite unsupported authority. Return a title and ordered sections only. For each section, claim_units must exactly concatenate in order to narrative. Attribute independent descriptive claims to DIRECT_FINDING; attribute relationships only to complete persisted Insight authority."
        schema = {"title": "string", "finding_refs": ["id"], "insight_refs": ["id"], "sections": [{"section_id": "id", "section_type": "EXECUTIVE_SUMMARY|KEY_FINDINGS|SEGMENT_RESULTS|KPI_RESULTS|LIMITATIONS", "title": "string", "narrative": "string", "finding_refs": ["id"], "insight_refs": ["id"], "referenced_display_values": ["value"], "authoritative_result_refs": ["id"], "authoritative_table_refs": [], "weighting_status": "UNWEIGHTED|WEIGHTED", "filter_definition": "string", "base_definition": "string", "direction": "HIGHER|LOWER|EQUAL|null", "claim_units": [{"claim_id": "id", "text": "exact contiguous narrative text", "support_mode": "DIRECT_FINDING|EXACT_CONTEXT_INSIGHT|INTERPRETIVE_COMPATIBILITY_INSIGHT", "finding_refs": ["id"], "insight_refs": ["id"], "referenced_display_values": ["value"], "authoritative_result_refs": ["id"]}]}]}
        prompt = instructions + "\nOUTPUT_SCHEMA=" + json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\nAPPROVED_SUPPORT=" + json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise QuantitativeAnalysisError("Quantitative Report prompt exceeds bounded size")
        return prompt

    @staticmethod
    def _prompt_v3(bundle):
        instructions = "Compose one structured Quantitative Report using only supplied accepted Finding and Insight IDs. Return a title and ordered supported sections. Do not return section narrative, section-level support references, fingerprints, context/base/filter/weighting fields, design IDs, lineage IDs, coverage states, answered flags, or objective-completion fields; production derives them. Every section must contain at least one claim_unit. For DIRECT_FINDING, copy exactly one supplied Finding text and reference exactly that Finding. For EXACT_CONTEXT_INSIGHT or INTERPRETIVE_COMPATIBILITY_INSIGHT, copy exactly one supplied Insight text, reference exactly that Insight, and include its complete Finding support set. Do not paraphrase claim text, infer relationships, combine unrelated Insights, or emit unsupported methodology or limitations prose. Do not return referenced_display_values or authoritative_result_refs; production derives those fields from validated persisted Finding/Insight authority. Preserve claim order only; production owns narrative separators."
        schema = {"title": "string", "sections": [{"section_id": "id", "section_type": "EXECUTIVE_SUMMARY|KEY_FINDINGS|SEGMENT_RESULTS|KPI_RESULTS", "title": "string", "claim_units": [{"claim_id": "id", "text": "exact supplied Finding or Insight text", "support_mode": "DIRECT_FINDING|EXACT_CONTEXT_INSIGHT|INTERPRETIVE_COMPATIBILITY_INSIGHT", "finding_refs": ["id"], "insight_refs": ["id"]}]}]}
        prompt = instructions + "\nOUTPUT_SCHEMA=" + json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\nAPPROVED_SUPPORT=" + json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise QuantitativeAnalysisError("Quantitative Report prompt exceeds bounded size")
        return prompt

    def _parse_v3(self, raw, bundle_fp, findings, insights):
        if not isinstance(raw, Mapping) or set(raw) - {"title", "sections"}:
            raise QuantitativeAnalysisError("qk-3 provider attempted to author system-owned Report fields")
        raw_sections = raw.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections or len(raw_sections) > MAX_SECTIONS:
            raise QuantitativeAnalysisError("structured Report proposal requires bounded sections")
        sections = []
        report_findings, report_insights = [], []
        finding_fingerprints = {key: value.support_validation_fingerprint for key, value in findings.items()}
        insight_fingerprints = {key: value.validation_fingerprint for key, value in insights.items()}
        for raw_section in raw_sections:
            if not isinstance(raw_section, Mapping) or set(raw_section) - {"section_id", "section_type", "title", "claim_units"}:
                raise QuantitativeAnalysisError("qk-3 provider attempted to author system-owned section fields")
            raw_units = raw_section.get("claim_units")
            if not isinstance(raw_units, list) or not raw_units:
                raise QuantitativeAnalysisError("qk-3 Report sections require governed claim units")
            units = tuple(self._parse_claim_unit_v3(item, findings, insights, finding_fingerprints, insight_fingerprints) for item in raw_units)
            section_findings = self._ordered_refs(unit.finding_refs for unit in units)
            section_insights = self._ordered_refs(unit.insight_refs for unit in units)
            if not section_findings:
                raise QuantitativeAnalysisError("qk-3 substantive section requires Finding authority")
            resolved = tuple(findings[item.authority_id] for item in section_findings if item.authority_id in findings)
            if len(resolved) != len(section_findings):
                raise QuantitativeAnalysisError("Report references a missing Finding")
            contexts = {(item.claim.weighting_status, item.claim.filter_definition, item.claim.base_definition) for item in resolved}
            if len(contexts) != 1:
                raise QuantitativeAnalysisError("qk-3 section support contexts are incompatible")
            weighting, filter_definition, base_definition = next(iter(contexts))
            displays = self._ordered_strings(unit.referenced_display_values for unit in units)
            results = self._ordered_strings(unit.authoritative_result_refs for unit in units)
            directions = {item.claim.direction for item in resolved if item.claim.direction}
            sections.append(QuantitativeReportSection(self._text(raw_section["section_id"], "section_id"), QuantitativeReportSectionType(str(raw_section["section_type"])), self._text(raw_section["title"], "section title"), " ".join(unit.text.strip() for unit in units), section_findings, section_insights, displays, results, (), weighting, filter_definition, base_definition, next(iter(directions)) if len(directions) == 1 else None, units))
            report_findings.extend(section_findings)
            report_insights.extend(section_insights)
        canonical_sections = tuple(sections)
        identity = canonical_digest({"bundle": bundle_fp, "title": raw.get("title"), "sections": tuple(QuantitativeReportValidator._section_payload(item) for item in canonical_sections), "version": DERIVED_CLAIM_VALIDATION_VERSION}, digest_provider=self._digest)
        return QuantitativeReport(str(uuid5(NAMESPACE_URL, f"qk-report:{identity}")), self._text(raw["title"], "title"), canonical_sections, self._ordered_refs((tuple(report_findings),)), self._ordered_refs((tuple(report_insights),)), generation_metadata={"prompt_version": DERIVED_CLAIM_PROMPT_VERSION, "generator": self._generator.identity}, generation_version=DERIVED_CLAIM_VALIDATION_VERSION)

    @staticmethod
    def _ordered_refs(groups):
        seen, values = set(), []
        for group in groups:
            for item in group:
                if item.authority_id not in seen:
                    seen.add(item.authority_id); values.append(item)
        return tuple(values)

    @staticmethod
    def _ordered_strings(groups):
        seen, values = set(), []
        for group in groups:
            for item in group:
                if item not in seen:
                    seen.add(item); values.append(item)
        return tuple(values)

    def _parse_v2(self, raw, bundle_fp, findings, insights):
        forbidden = {"finding_fingerprints", "insight_fingerprints", "objective_ids", "research_question_ids", "analytical_requirement_ids", "re_lineage_ids", "rf_lineage_ids", "rd_ids", "rc_ids", "coverage_status", "rq_answered", "objective_complete", "support_validation_fingerprints"}
        if not isinstance(raw, Mapping):
            raise QuantitativeAnalysisError("structured Report proposal must be an object")
        if forbidden.intersection(raw):
            raise QuantitativeAnalysisError("model-authored Report authority is forbidden")
        sections = raw.get("sections")
        if isinstance(sections, list) and any(isinstance(item, Mapping) and forbidden.intersection(item) for item in sections):
            raise QuantitativeAnalysisError("model-authored section authority is forbidden")
        canonical = dict(raw)
        canonical["finding_fingerprints"] = {key: value.support_validation_fingerprint for key, value in findings.items()}
        canonical["insight_fingerprints"] = {key: value.validation_fingerprint for key, value in insights.items()}
        canonical_sections = []
        for section in sections or ():
            value = dict(section)
            value["finding_fingerprints"] = {key: findings[key].support_validation_fingerprint for key in value.get("finding_refs", ()) if key in findings}
            value["insight_fingerprints"] = {key: insights[key].validation_fingerprint for key in value.get("insight_refs", ()) if key in insights}
            canonical_sections.append(value)
        canonical["sections"] = canonical_sections
        parsed = self._parse(canonical, bundle_fp, findings, insights)
        return replace(parsed, generation_metadata={"prompt_version": DESIGN_AWARE_PROMPT_VERSION, "generator": self._generator.identity})
    def _parse(self, raw, bundle_fp, findings, insights):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("sections"), list) or not raw["sections"] or len(raw["sections"]) > MAX_SECTIONS:
            raise QuantitativeAnalysisError("structured Report proposal requires bounded sections")
        finding_ids = self._strings(raw.get("finding_refs"), "finding_refs")
        insight_ids = self._strings(raw.get("insight_refs", []), "insight_refs", allow_empty=True)
        finding_fingerprints = self._fingerprints(raw.get("finding_fingerprints", {}), "finding_fingerprints")
        insight_fingerprints = self._fingerprints(raw.get("insight_fingerprints", {}), "insight_fingerprints")
        sections = tuple(self._parse_section(item, findings, insights) for item in raw["sections"])
        identity = canonical_digest({"bundle": bundle_fp, "proposal": dict(raw)}, digest_provider=self._digest)
        return QuantitativeReport(str(uuid5(NAMESPACE_URL, f"qk-report:{identity}")), self._text(raw["title"], "title"), sections, tuple(self._ref(item, findings, "finding", finding_fingerprints) for item in finding_ids), tuple(self._ref(item, insights, "insight", insight_fingerprints) for item in insight_ids), generation_metadata={"prompt_version": PROMPT_VERSION, "generator": self._generator.identity})

    def _parse_section(self, raw, findings, insights):
        if not isinstance(raw, Mapping): raise QuantitativeAnalysisError("Report section must be an object")
        finding_ids = self._strings(raw.get("finding_refs", []), "section finding_refs", allow_empty=True)
        insight_ids = self._strings(raw.get("insight_refs", []), "section insight_refs", allow_empty=True)
        finding_fingerprints = self._fingerprints(raw.get("finding_fingerprints", {}), "section finding_fingerprints")
        insight_fingerprints = self._fingerprints(raw.get("insight_fingerprints", {}), "section insight_fingerprints")
        claim_units = tuple(self._parse_claim_unit(item, findings, insights, finding_fingerprints, insight_fingerprints) for item in raw.get("claim_units", ()))
        return QuantitativeReportSection(self._text(raw["section_id"], "section_id"), QuantitativeReportSectionType(str(raw["section_type"])), self._text(raw["title"], "section title"), self._text(raw["narrative"], "section narrative"), tuple(self._ref(item, findings, "finding", finding_fingerprints) for item in finding_ids), tuple(self._ref(item, insights, "insight", insight_fingerprints) for item in insight_ids), self._strings(raw.get("referenced_display_values", []), "display values", allow_empty=True), self._strings(raw.get("authoritative_result_refs", []), "result refs", allow_empty=True), self._strings(raw.get("authoritative_table_refs", []), "table refs", allow_empty=True), str(raw["weighting_status"]), str(raw["filter_definition"]), str(raw["base_definition"]), None if raw.get("direction") is None else str(raw["direction"]), claim_units)

    def _parse_claim_unit_v3(self, raw, findings, insights, finding_fingerprints, insight_fingerprints):
        if not isinstance(raw, Mapping) or set(raw) - {"claim_id", "text", "support_mode", "finding_refs", "insight_refs"}:
            raise QuantitativeAnalysisError("qk-3 claim unit contains unsupported fields")
        finding_ids = self._strings(raw.get("finding_refs", []), "claim finding_refs", allow_empty=True)
        insight_ids = self._strings(raw.get("insight_refs", []), "claim insight_refs", allow_empty=True)
        mode = QuantitativeReportClaimSupportMode(str(raw["support_mode"]))
        resolved_findings = tuple(
            findings[self._ref(item, findings, "finding", finding_fingerprints).authority_id]
            for item in finding_ids
        )
        resolved_insights = tuple(
            insights[self._ref(item, insights, "insight", insight_fingerprints).authority_id]
            for item in insight_ids
        )
        if mode is QuantitativeReportClaimSupportMode.DIRECT_FINDING:
            if len(resolved_findings) != 1 or resolved_insights:
                raise QuantitativeAnalysisError("qk-3 direct claims require exactly one Finding and no Insight")
            canonical_findings = resolved_findings
            canonical_finding_ids = finding_ids
            expected_displays = tuple(
                value for value in (resolved_findings[0].claim.display_value,) if value
            )
        else:
            if len(resolved_insights) != 1:
                raise QuantitativeAnalysisError("qk-3 relational claims require exactly one Insight")
            required_finding_ids = tuple(
                reference.finding_id
                for reference in resolved_insights[0].supporting_finding_refs
            )
            if len(finding_ids) != len(required_finding_ids) or set(finding_ids) != set(required_finding_ids):
                raise QuantitativeAnalysisError(
                    "qk-3 relational claims require the complete persisted Insight support set"
                )
            canonical_finding_ids = required_finding_ids
            canonical_findings = tuple(findings[item] for item in canonical_finding_ids)
            expected_displays = tuple(resolved_insights[0].referenced_display_values)
        expected_results = self._ordered_strings(
            tuple(ref.result_id for ref in item.statistical_result_refs) for item in canonical_findings
        )
        return QuantitativeReportClaimUnit(
            self._text(raw["claim_id"], "claim_id"),
            self._claim_text(raw["text"]),
            mode,
            tuple(self._ref(item, findings, "finding", finding_fingerprints) for item in canonical_finding_ids),
            tuple(self._ref(item, insights, "insight", insight_fingerprints) for item in insight_ids),
            expected_displays,
            expected_results,
        )
    def _parse_claim_unit(self, raw, findings, insights, finding_fingerprints, insight_fingerprints):
        if not isinstance(raw, Mapping): raise QuantitativeAnalysisError("Report claim unit must be an object")
        finding_ids = self._strings(raw.get("finding_refs", []), "claim finding_refs", allow_empty=True)
        insight_ids = self._strings(raw.get("insight_refs", []), "claim insight_refs", allow_empty=True)
        return QuantitativeReportClaimUnit(self._text(raw["claim_id"], "claim_id"), self._claim_text(raw["text"]), QuantitativeReportClaimSupportMode(str(raw["support_mode"])), tuple(self._ref(item, findings, "finding", finding_fingerprints) for item in finding_ids), tuple(self._ref(item, insights, "insight", insight_fingerprints) for item in insight_ids), self._strings(raw.get("referenced_display_values", []), "claim display values", allow_empty=True), self._strings(raw.get("authoritative_result_refs", []), "claim result refs", allow_empty=True))

    @staticmethod
    def _ref(item, available, kind, expected):
        authority = available.get(item)
        if authority is None: return QuantitativeReportSupportReference(item, "UNAVAILABLE")
        fingerprint = authority.support_validation_fingerprint if kind == "finding" else authority.validation_fingerprint
        return QuantitativeReportSupportReference(item, expected.get(item, fingerprint))

    @staticmethod
    def _fingerprints(value, name):
        if not isinstance(value, Mapping) or any(not isinstance(key, str) or not key or not isinstance(item, str) or not item for key, item in value.items()):
            raise QuantitativeAnalysisError(f"{name} must be a string fingerprint map")
        return dict(value)

    @staticmethod
    def _strings(value, name, *, allow_empty=False):
        if not isinstance(value, list) or (not value and not allow_empty) or any(not isinstance(item, str) or not item for item in value) or len(value) != len(set(value)): raise QuantitativeAnalysisError(f"{name} must be a unique string array")
        return tuple(value)

    @staticmethod
    def _claim_text(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 4000: raise QuantitativeAnalysisError("claim text must be bounded non-empty text")
        return value

    @staticmethod
    def _text(value, name):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 4000: raise QuantitativeAnalysisError(f"{name} must be bounded non-empty text")
        return value.strip()
