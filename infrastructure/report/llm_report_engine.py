from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from application.exceptions.structured_output_error import StructuredOutputError
from application.ports.report_ports import (
    ReportCandidate,
    ReportInput,
    ReportSectionCandidate,
)
from application.report.diagnostics import (
    REJECTION_CATEGORY_EMPTY_SUPPORT,
    REJECTION_CATEGORY_INVALID_FINDING_REF,
    REJECTION_CATEGORY_INVALID_INSIGHT_REF,
    REJECTION_CATEGORY_MISSING_CONTENT,
    REJECTION_CATEGORY_MISSING_TITLE,
)
from application.report.exceptions import ReportConfigurationError
from application.research_scope.authoritative_scope import scope_for_finding
from application.execution.exceptions import BudgetExhaustedError
from application.report.report_structured_output import (
    REPORT_SECTIONS_PAYLOAD_SCHEMA,
    REPORT_SUMMARY_PAYLOAD_SCHEMA,
    ReportStructuredOutputGenerator,
)
from domain.ai.prompt import Prompt
from infrastructure.llm.llm_client import LLMClient


@dataclass
class ReportSectionEngineBatchStats:
    candidate_section_count: int = 0
    engine_dropped_count: int = 0
    raw_items: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    visible_output_length: int | None = None
    finish_reason: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    parse_failure_category: str | None = None


class LlmReportEngine:
    """Production report writer using structured LLM output."""

    method_name = "llm"

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        max_sections: int = 10,
        max_findings_per_section: int = 15,
        max_insights_per_section: int = 8,
        structured_output_max_attempts: int = 3,
    ) -> None:
        self._structured_output = ReportStructuredOutputGenerator(
            llm_client=llm_client,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            max_attempts=structured_output_max_attempts,
        )
        self._claim_structured_output = ReportStructuredOutputGenerator(
            llm_client=llm_client,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            max_attempts=1,
        )
        self._max_sections = max_sections
        self._max_findings_per_section = max_findings_per_section
        self._max_insights_per_section = max_insights_per_section
        self._last_section_batch_stats: ReportSectionEngineBatchStats | None = None

    def generate_claim_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._generate_claim_payload(request, repair=False)

    def repair_claim_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._generate_claim_payload(request, repair=True)

    def _generate_claim_payload(
        self,
        request: dict[str, Any],
        *,
        repair: bool,
    ) -> dict[str, Any]:
        operation = "repair" if repair else "initial generation"
        system = (
            "You generate structured ReportClaims from supplied authoritative envelopes. "
            "Return JSON only. Preserve every identifier and lineage field exactly. "
            "Each claim may use only its own authority envelope; never borrow authority "
            "from another claim. Do not derive, convert, round, broaden, or invent facts. "
            "Omit unsupported factual wording. "
            f"This is a bounded {operation} call."
        )
        if repair:
            system += (
                " Correct only the supplied invalid claims. Preserve supported claims "
                "outside this request unchanged. Return only a repair delta: claim_id "
                "for claim matching, one complete assertion object, and only the "
                "provenance/support/scope selections you intend to replace. Omitted or "
                "null selectable fields preserve canonical authority. Never return or "
                "modify validation metadata, digests, version, or immutable lineage."
            )
        repair_item = '{"claim_id":"string","assertion":{"kind":"string","proposition":"string","certainty":"string","direction":"string"},"research_question_ids":["string"],"information_need_ids":["string"],"finding_ids":["string"],"insight_ids":["string"],"evidence_ids":["string"],"support":{"evidence_ids":["string"],"source_ids":["string"],"citation_ids":["string"]},"scope":{"geography":{"country":["string"],"subnational":["string"]},"periods":["string"],"metrics":["string"],"population_dimensions":["string"],"numeric_facts":["complete authoritative NumericFact objects"]}}'
        schema = (
            ('{"claims":[' + repair_item + ']}') if repair and "claims" in request
            else repair_item if repair
            else '{"claims":[{"claim_id":"string", "...":"same ReportClaim fields as authority"}]}' if "claims" in request
            else '{"claim_id":"string", "...":"same ReportClaim fields as authority"}'
        )
        return self._claim_structured_output.generate(
            Prompt(
                system=system,
                user=(
                    "REQUIRED JSON SHAPE\n"
                    f"{schema}\n"
                    "BOUNDED CLAIM REQUEST\n"
                    f"{json.dumps(request, ensure_ascii=False, sort_keys=True)}"
                ),
            ),
            payload_schema=schema,
        )

    @property
    def last_section_batch_stats(self) -> ReportSectionEngineBatchStats | None:
        return self._last_section_batch_stats

    def generate_sections(
        self,
        report_input: ReportInput,
    ) -> tuple[ReportSectionCandidate, ...]:
        prompt = Prompt(
            system=self._section_system_prompt(report_input),
            user=self._build_section_payload(report_input),
        )
        try:
            payload = self._structured_output.generate(
                prompt,
                payload_schema=REPORT_SECTIONS_PAYLOAD_SCHEMA,
            )
        except StructuredOutputError as exc:
            raise ReportConfigurationError(
                "LLM report section generation failed structured output validation",
            ) from exc
        except BudgetExhaustedError:
            raise
        except Exception as exc:
            raise ReportConfigurationError("LLM report section generation failed") from exc

        sections, stats = self._build_section_candidates(report_input, payload)
        telemetry = self._structured_output.last_telemetry
        if telemetry is not None:
            stats.output_tokens = telemetry.output_tokens
            stats.reasoning_tokens = telemetry.reasoning_tokens
            stats.visible_output_length = telemetry.visible_output_length
            stats.finish_reason = telemetry.finish_reason
            stats.max_output_tokens = telemetry.max_output_tokens
            stats.reasoning_effort = telemetry.reasoning_effort
            stats.parse_failure_category = telemetry.parse_failure_category
        self._last_section_batch_stats = stats
        return sections

    def generate_executive_summary(
        self,
        report_input: ReportInput,
        *,
        sections: tuple[ReportSectionCandidate, ...],
    ) -> ReportCandidate:
        prompt = Prompt(
            system=(
                "You are a desk research report writer. Produce a report title, executive "
                "summary, and limitations list from validated section summaries. Do NOT "
                "invent new facts or external information. Return JSON only with shape "
                '{"title":"...","executive_summary":"...","limitations":["..."]}. '
                f"Write in language '{report_input.brief.language}'."
            ),
            user=self._build_summary_payload(report_input, sections=sections),
        )
        try:
            payload = self._structured_output.generate(
                prompt,
                payload_schema=REPORT_SUMMARY_PAYLOAD_SCHEMA,
            )
        except StructuredOutputError as exc:
            raise ReportConfigurationError(
                "LLM executive summary generation failed structured output validation",
            ) from exc
        except BudgetExhaustedError:
            raise
        except Exception as exc:
            raise ReportConfigurationError("LLM executive summary generation failed") from exc

        title = str(payload.get("title", report_input.brief.title)).strip()
        executive_summary = str(payload.get("executive_summary", "")).strip()
        limitations = tuple(
            str(item).strip()
            for item in payload.get("limitations", [])
            if str(item).strip()
        )
        if not title or not executive_summary:
            raise ReportConfigurationError("LLM report summary missing title or content")
        return ReportCandidate(
            title=title,
            executive_summary=executive_summary,
            sections=sections,
            limitations=limitations,
        )

    def _section_system_prompt(self, report_input: ReportInput) -> str:
        return (
            "You are a desk research report writer. Synthesize validated Findings and "
            "Insights into compact, decision-oriented report sections. You MUST NOT invent "
            "new facts, expand an observation period beyond the supplied Finding/Evidence, "
            "or introduce substantive causal claims not entailed by the supplied support. "
            "The structured authoritative_scope_contract is the exclusive allowlist for "
            "factual scope. Both section content and claim_scope MUST use only exact anchors "
            "or complete numeric facts present for the cited Findings. Omission or less "
            "precision is preferable to unsupported precision. A year does not authorize a "
            "month, quarter, exact date, or narrower subperiod. An empty geography, metric, "
            "population_dimensions, numeric_facts, or unit set authorizes no anchor in that "
            "dimension; never fill it from Finding/Evidence prose or general knowledge. "
            "Do not calculate, round, derive, convert, or combine numeric facts. Preserve each "
            "allowed value together with its exact unit, geography, period, metric, and "
            "population/dimension bindings. Use the authoritative support block only as prose "
            "support within those structured limits and to keep citations exact. "
            "When deterministic_repair_diagnostics are supplied, correct only the listed "
            "claim-scope violations by removing unsupported anchors or facts. Do not replace "
            "them with inferred values, periods, units, metrics, geographies, or populations. "
            "Every substantive section must retain all referenced finding/evidence IDs. "
            "For every mandatory substantive RQ in the contract, emit that exact RQ ID "
            "in research_question_refs and at least one authoritative Finding ID listed "
            "for that RQ in finding_refs; do not omit or infer these bindings. "
            "Do not use citation labels unless their mapping is present in the support block. "
            "Do not perform web research or reference IDs not provided. Consolidate "
            "related findings into major sections rather than repeating every finding. "
            f"Return at most {self._max_sections} sections. Each section may reference up "
            f"to {self._max_findings_per_section} finding_refs and "
            f"{self._max_insights_per_section} insight_refs. Return JSON only with shape "
            '{"sections":[{"title":"...","content":"...",'
            '"finding_refs":["finding-id"],"insight_refs":["insight-id"],'
            '"research_question_refs":["rq-id"],"evidence_refs":["evidence-id"],'
            '"claim_scope":{"version":"desk_authoritative_scope_v1",'
            '"geography":[],"geography_anchors":[],"periods":[],"metrics":[],'
            '"population_dimensions":[],"numeric_facts":[]}}]}. '
            "Each section must reference at least one finding_ref or insight_ref. "
            f"Write in language '{report_input.brief.language}'."
        )

    def _build_section_candidates(
        self,
        report_input: ReportInput,
        payload: dict[str, Any],
    ) -> tuple[tuple[ReportSectionCandidate, ...], ReportSectionEngineBatchStats]:
        allowed_findings = {item.id for item in report_input.findings}
        allowed_insights = {item.id for item in report_input.insights}
        allowed_evidence = set(report_input.evidence_by_id)
        allowed_questions = {
            question.id for question in report_input.design.research_questions
        }
        sections: list[ReportSectionCandidate] = []
        rejection_counts: dict[str, int] = {}
        raw_items = 0
        engine_dropped = 0
        seen_titles: set[str] = set()

        for item in payload.get("sections", []):
            raw_items += 1
            if not isinstance(item, dict):
                engine_dropped += 1
                continue

            raw_finding_refs = [
                str(ref).strip() for ref in item.get("finding_refs", []) if str(ref).strip()
            ]
            raw_insight_refs = [
                str(ref).strip() for ref in item.get("insight_refs", []) if str(ref).strip()
            ]
            invalid_finding_refs = [
                ref for ref in raw_finding_refs if ref not in allowed_findings
            ]
            invalid_insight_refs = [
                ref for ref in raw_insight_refs if ref not in allowed_insights
            ]
            if invalid_finding_refs:
                rejection_counts[REJECTION_CATEGORY_INVALID_FINDING_REF] = (
                    rejection_counts.get(REJECTION_CATEGORY_INVALID_FINDING_REF, 0)
                    + len(invalid_finding_refs)
                )
            if invalid_insight_refs:
                rejection_counts[REJECTION_CATEGORY_INVALID_INSIGHT_REF] = (
                    rejection_counts.get(REJECTION_CATEGORY_INVALID_INSIGHT_REF, 0)
                    + len(invalid_insight_refs)
                )

            finding_refs = tuple(
                ref for ref in raw_finding_refs if ref in allowed_findings
            )[: self._max_findings_per_section]
            insight_refs = tuple(
                ref for ref in raw_insight_refs if ref in allowed_insights
            )[: self._max_insights_per_section]
            if not finding_refs and not insight_refs:
                engine_dropped += 1
                rejection_counts[REJECTION_CATEGORY_EMPTY_SUPPORT] = (
                    rejection_counts.get(REJECTION_CATEGORY_EMPTY_SUPPORT, 0) + 1
                )
                continue

            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            if not title:
                engine_dropped += 1
                rejection_counts[REJECTION_CATEGORY_MISSING_TITLE] = (
                    rejection_counts.get(REJECTION_CATEGORY_MISSING_TITLE, 0) + 1
                )
                continue
            if not content:
                engine_dropped += 1
                rejection_counts[REJECTION_CATEGORY_MISSING_CONTENT] = (
                    rejection_counts.get(REJECTION_CATEGORY_MISSING_CONTENT, 0) + 1
                )
                continue
            normalized_title = title.lower()
            if normalized_title in seen_titles:
                engine_dropped += 1
                rejection_counts["duplicate_section"] = (
                    rejection_counts.get("duplicate_section", 0) + 1
                )
                continue
            seen_titles.add(normalized_title)

            evidence_refs = tuple(
                str(ref).strip()
                for ref in item.get("evidence_refs", [])
                if str(ref).strip() in allowed_evidence
            )
            question_refs = tuple(
                str(ref).strip()
                for ref in item.get("research_question_refs", [])
                if str(ref).strip() in allowed_questions
            )
            if (
                not question_refs
                and report_input.batch_question_id
                and report_input.batch_question_id in allowed_questions
                and not report_input.mandatory_substantive_rq_findings
            ):
                question_refs = (report_input.batch_question_id,)
            sections.append(
                ReportSectionCandidate(
                    title=title,
                    content=content,
                    research_question_refs=question_refs,
                    finding_refs=finding_refs,
                    insight_refs=insight_refs,
                    evidence_refs=evidence_refs,
                    metadata={"claim_scope": item["claim_scope"]}
                    if isinstance(item.get("claim_scope"), dict) else {},
                ),
            )
            if len(sections) >= self._max_sections:
                break

        stats = ReportSectionEngineBatchStats(
            candidate_section_count=len(sections),
            engine_dropped_count=engine_dropped,
            raw_items=raw_items,
            rejection_counts=rejection_counts,
        )
        return tuple(sections), stats

    def _build_section_payload(self, report_input: ReportInput) -> str:
        authoritative_scopes = {
            finding.id: scope_for_finding(finding, report_input.evidence_by_id)
            for finding in report_input.findings
        }
        scope_contract = {
            "version": 1,
            "policy": "exact_subset",
            "authority": "cited_finding_scopes",
            "rules": {
                "period": "exact_anchor_only_no_finer_subperiod",
                "geography": "exact_anchor_only",
                "metric": "exact_anchor_only_empty_means_none",
                "population_dimension": "exact_anchor_only_empty_means_none",
                "numeric_fact": "exact_value_and_all_bindings_only",
                "unit_scale": "exact_bound_numeric_fact_only",
                "missing_dimension": "omit_do_not_infer_from_prose",
            },
            "finding_scopes": authoritative_scopes,
        }
        lines = [
            f"business_question: {report_input.brief.business_question}",
            f"language: {report_input.brief.language}",
            "authoritative_scope_contract: "
            + json.dumps(scope_contract, sort_keys=True),
            "deliverable_plan:",
            *[f"- {item}" for item in report_input.section_titles],
            "findings:",
        ]
        if report_input.coverage_snapshot is not None:
            lines.append(
                "deterministic_report_coverage: "
                + json.dumps(report_input.coverage_snapshot, sort_keys=True)
            )
        if report_input.mandatory_substantive_rq_findings:
            lines.append(
                "mandatory_substantive_rq_findings: "
                + json.dumps(
                    report_input.mandatory_substantive_rq_findings,
                    sort_keys=True,
                )
            )
        if report_input.repair_diagnostics:
            lines.append(
                "deterministic_repair_diagnostics: "
                + json.dumps(list(report_input.repair_diagnostics), sort_keys=True)
            )
        for finding in report_input.findings:
            authoritative_scope = authoritative_scopes[finding.id]
            lines.append(
                f"- id={finding.id} statement={finding.statement} "
                f"evidence_refs={list(finding.evidence_refs)} "
                "authoritative_scope="
                + json.dumps(authoritative_scope, sort_keys=True),
            )
        lines.append("authoritative_support:")
        for finding in report_input.findings:
            for evidence_id in finding.evidence_refs:
                evidence = report_input.evidence_by_id.get(evidence_id)
                if evidence is None:
                    continue
                source = report_input.sources_by_id.get(evidence.source_id)
                source_period = (source.metadata or {}).get("observation_period") if source else None
                lines.append(
                    f"- evidence_id={evidence.id} finding_id={finding.id} "
                    f"statement={evidence.statement} excerpt={evidence.source_excerpt} "
                    f"source_id={evidence.source_id} "
                    f"source_title={source.title if source else ''} "
                    f"published_at={source.published_at if source else None} "
                    f"observation_period={evidence.metadata.get('observation_period') or source_period if source else evidence.metadata.get('observation_period')}"
                )
        lines.append("insights:")
        for insight in report_input.insights:
            lines.append(
                f"- id={insight.id} statement={insight.statement} "
                f"finding_refs={list(insight.finding_refs)}",
            )
        if report_input.batch_question_id:
            lines.append(f"batch_research_question_id: {report_input.batch_question_id}")
        return "\n".join(lines)

    def _build_summary_payload(
        self,
        report_input: ReportInput,
        *,
        sections: tuple[ReportSectionCandidate, ...],
    ) -> str:
        lines = [
            f"business_question: {report_input.brief.business_question}",
            f"language: {report_input.brief.language}",
            "section_summaries:",
        ]
        if report_input.coverage_snapshot is not None:
            lines.append(
                "deterministic_report_coverage: "
                + json.dumps(report_input.coverage_snapshot, sort_keys=True)
            )
        for section in sections:
            lines.append(f"- {section.title}: {section.content[:500]}")
        lines.append("design_limitations:")
        for limitation in report_input.design.limitations:
            lines.append(f"- {limitation}")
        return "\n".join(lines)
