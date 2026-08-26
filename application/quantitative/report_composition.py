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
from domain.quantitative.insight import QuantitativeInsight, QuantitativeInsightValidationStatus
from domain.quantitative.report import (
    QuantitativeReport,
    QuantitativeReportCompositionResult,
    QuantitativeReportRejection,
    QuantitativeReportSection,
    QuantitativeReportSectionType,
    QuantitativeReportSupportReference,
    QuantitativeReportValidationStatus,
)


PROMPT_VERSION = "QK_REPORT_COMPOSITION_V1"
DESIGN_AWARE_PROMPT_VERSION = "QK_REPORT_COMPOSITION_V2"
VALIDATION_VERSION = "qk-1"
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
            self._validate_section(section, chain_findings)
        support_fingerprint = canonical_digest(
            {
                "findings": tuple((item.finding_id, item.support_validation_fingerprint) for item in report_findings),
                "insights": tuple((item.insight_id, item.validation_fingerprint) for item in report_insights),
            },
            digest_provider=self._digest,
        )
        validation_fingerprint = canonical_digest(
            {
                "report_id": report.report_id,
                "title": report.title,
                "sections": tuple(self._section_payload(item) for item in report.sections),
                "support": support_fingerprint,
                "version": VALIDATION_VERSION,
            },
            digest_provider=self._digest,
        )
        return replace(
            report,
            analytical_support_fingerprint=support_fingerprint,
            validation_status=QuantitativeReportValidationStatus.SUPPORTED,
            validation_fingerprint=validation_fingerprint,
            generation_version=VALIDATION_VERSION,
        )

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

    def _validate_section(self, section, findings):
        if not section.title.strip() or not section.narrative.strip():
            raise QuantitativeAnalysisError("Report section title and narrative are required")
        contexts = {item.analytical_context_fingerprint for item in findings}
        if "" in contexts or len(contexts) != 1:
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
        prompt = self._prompt_v2(bundle)
        prompt_fp = canonical_digest({"version": DESIGN_AWARE_PROMPT_VERSION, "prompt": prompt}, digest_provider=self._digest)
        raw = self._generator.generate(prompt)
        proposed = None
        accepted = None
        rejected = []
        try:
            proposed = self._parse_v2(raw, bundle_fp, finding_map, insight_map)
            accepted = self._validator.validate(proposed, findings=finding_map, insights=insight_map)
            if post_validator is not None:
                accepted = post_validator(accepted)
        except (QuantitativeAnalysisError, ValueError, TypeError, KeyError) as exc:
            accepted = None
            payload = dict(raw) if isinstance(raw, Mapping) else {"raw_type": type(raw).__name__}
            reason = f"{type(exc).__name__}: {exc}"
            rejected.append(QuantitativeReportRejection(payload, reason, canonical_digest({"bundle": bundle_fp, "proposal": payload, "reason": reason, "version": DESIGN_AWARE_PROMPT_VERSION}, digest_provider=self._digest)))
        composition_fp = canonical_digest({"bundle": bundle_fp, "generator": self._generator.identity, "prompt": prompt_fp, "accepted": accepted.validation_fingerprint if accepted else None, "rejected": tuple(item.rejection_fingerprint for item in rejected), "version": DESIGN_AWARE_PROMPT_VERSION}, digest_provider=self._digest)
        return QuantitativeReportCompositionResult(str(uuid5(NAMESPACE_URL, f"qk-composition:{composition_fp}")), bundle_fp, self._generator.identity, DESIGN_AWARE_PROMPT_VERSION, prompt_fp, proposed, accepted, tuple(rejected), {"generation_passes": 1, "repair_attempts": 0}, composition_fp)
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
        schema = {"title": "string", "finding_refs": ["id"], "finding_fingerprints": {"id": "fingerprint"}, "insight_refs": ["id"], "insight_fingerprints": {"id": "fingerprint"}, "sections": [{"section_id": "id", "section_type": "EXECUTIVE_SUMMARY|KEY_FINDINGS|SEGMENT_RESULTS|KPI_RESULTS|LIMITATIONS", "title": "string", "narrative": "string", "finding_refs": ["id"], "finding_fingerprints": {"id": "fingerprint"}, "insight_refs": ["id"], "insight_fingerprints": {"id": "fingerprint"}, "referenced_display_values": ["value"], "authoritative_result_refs": ["id"], "authoritative_table_refs": [], "weighting_status": "UNWEIGHTED|WEIGHTED", "filter_definition": "string", "base_definition": "string", "direction": "HIGHER|LOWER|EQUAL|null"}]}
        prompt = instructions + "\nOUTPUT_SCHEMA=" + json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\nAPPROVED_SUPPORT=" + json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise QuantitativeAnalysisError("Quantitative Report prompt exceeds bounded size")
        return prompt

    @staticmethod
    def _prompt_v2(bundle):
        instructions = "Compose one structured Quantitative Report using only supplied accepted Finding and Insight IDs. Do not return fingerprints, design IDs, lineage IDs, coverage states, answered flags, or objective-completion fields. Do not calculate or invent numbers; every narrative number must exactly match an approved display value and be listed explicitly. Preserve significance, direction, weighting, filters, bases, and populations. Do not infer causality or cite unsupported authority. Return a title and ordered sections only."
        schema = {"title": "string", "finding_refs": ["id"], "insight_refs": ["id"], "sections": [{"section_id": "id", "section_type": "EXECUTIVE_SUMMARY|KEY_FINDINGS|SEGMENT_RESULTS|KPI_RESULTS|LIMITATIONS", "title": "string", "narrative": "string", "finding_refs": ["id"], "insight_refs": ["id"], "referenced_display_values": ["value"], "authoritative_result_refs": ["id"], "authoritative_table_refs": [], "weighting_status": "UNWEIGHTED|WEIGHTED", "filter_definition": "string", "base_definition": "string", "direction": "HIGHER|LOWER|EQUAL|null"}]}
        prompt = instructions + "\nOUTPUT_SCHEMA=" + json.dumps(schema, sort_keys=True, separators=(",", ":")) + "\nAPPROVED_SUPPORT=" + json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise QuantitativeAnalysisError("Quantitative Report prompt exceeds bounded size")
        return prompt

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
        return QuantitativeReportSection(self._text(raw["section_id"], "section_id"), QuantitativeReportSectionType(str(raw["section_type"])), self._text(raw["title"], "section title"), self._text(raw["narrative"], "section narrative"), tuple(self._ref(item, findings, "finding", finding_fingerprints) for item in finding_ids), tuple(self._ref(item, insights, "insight", insight_fingerprints) for item in insight_ids), self._strings(raw.get("referenced_display_values", []), "display values", allow_empty=True), self._strings(raw.get("authoritative_result_refs", []), "result refs", allow_empty=True), self._strings(raw.get("authoritative_table_refs", []), "table refs", allow_empty=True), str(raw["weighting_status"]), str(raw["filter_definition"]), str(raw["base_definition"]), None if raw.get("direction") is None else str(raw["direction"]))

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
    def _text(value, name):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 4000: raise QuantitativeAnalysisError(f"{name} must be bounded non-empty text")
        return value.strip()
