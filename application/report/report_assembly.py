from __future__ import annotations

import re
from uuid import uuid4

from domain.findings.finding import Finding
from domain.findings.finding_type import FindingType
from domain.findings.insight import Insight
from domain.planning.research_design import ResearchDesign
from domain.reports.report_section import ReportSection

from application.report.citation_registry import CitationRegistry
from application.report.substantive_coverage import primary_research_question_for_section

DEFAULT_REPORT_MAX_SECTIONS = 12

CONTRADICTION_SECTION_TITLE = "Contradictions / Uncertainty"
LIMITATIONS_SECTION_TITLE = "Limitations"
RECOMMENDATIONS_SECTION_TITLE = "Recommendations / Entry Implications"

_NUMERIC_CLAIM = re.compile(
    r"(?:>=|<=|≥|≤|>|<)\s*\d+(?:\.\d+)?%?"
    r"|(?:\b\d+(?:\.\d+)?%)\b"
    r"|(?:\bOTIF\b|\bSLA\b|\bKPI\b)",
    re.IGNORECASE,
)
_CITATION_MARKER = re.compile(r"\[(S\d+)\]")


def contradiction_findings(findings: list[Finding] | tuple[Finding, ...]) -> tuple[Finding, ...]:
    return tuple(
        item for item in findings if item.finding_type == FindingType.CONTRADICTION
    )


def build_contradiction_section(
    findings: list[Finding] | tuple[Finding, ...],
    *,
    citation_registry: CitationRegistry | None = None,
) -> ReportSection | None:
    items = contradiction_findings(findings)
    if not items:
        return None
    paragraphs: list[str] = [
        "The analysis identified material disagreement across sources or findings. "
        "The report preserves conflicting evidence rather than forcing consensus.",
    ]
    finding_refs: list[str] = []
    rq_refs: set[str] = set()
    for finding in items:
        finding_refs.append(finding.id)
        rq_refs.update(finding.research_question_refs)
        paragraphs.append(
            f"- Conflict: {finding.statement.strip()} "
            f"(uncertainty remains; may reflect temporal, segment, geography, "
            f"or methodology differences)."
        )
    paragraphs.append(
        "Impact on confidence: conclusions tied to these topics should be treated "
        "with lower certainty until additional corroboration is available."
    )
    return ReportSection(
        id=str(uuid4()),
        title=CONTRADICTION_SECTION_TITLE,
        content="\n\n".join(paragraphs),
        research_question_refs=tuple(sorted(rq_refs)),
        finding_refs=tuple(sorted(set(finding_refs))),
        insight_refs=(),
        evidence_refs=tuple(
            sorted({ref for f in items for ref in f.evidence_refs}),
        ),
        citation_ids=(),
        metadata={"section_kind": "contradictions", "synthesized": True},
    )


def synthesize_contextual_limitations(
    *,
    design: ResearchDesign,
    global_limitations: tuple[str, ...],
    findings: list[Finding] | tuple[Finding, ...],
) -> tuple[str, ...]:
    """Merge design + global limitations; add bounded contextual caveats."""
    merged: list[str] = list(dict.fromkeys([*global_limitations, *design.limitations]))
    low_confidence = [f for f in findings if (f.confidence or 1.0) < 0.5]
    if low_confidence:
        merged.append(
            "Some recommendations rely on lower-confidence findings; "
            "validate with primary research before major commitments."
        )
    if any("regulatory" in (f.statement + f.rationale).lower() for f in findings):
        merged.append(
            "Regulatory requirements may vary by segment and geography; "
            "confirm compliance obligations independently."
        )
    return tuple(dict.fromkeys(merged))


def build_limitations_section(
    limitations: tuple[str, ...],
    *,
    design: ResearchDesign,
) -> ReportSection:
    rq_refs = tuple(q.id for q in design.research_questions)
    content = "\n".join(f"- {item}" for item in limitations) if limitations else "- None stated."
    return ReportSection(
        id=str(uuid4()),
        title=LIMITATIONS_SECTION_TITLE,
        content=content,
        research_question_refs=rq_refs,
        finding_refs=(),
        insight_refs=(),
        evidence_refs=(),
        citation_ids=(),
        metadata={"section_kind": "limitations", "synthesized": True},
    )


def detect_unsupported_numeric_claims(
    content: str,
    *,
    finding_refs: tuple[str, ...],
    findings_by_id: dict[str, Finding],
) -> tuple[str, ...]:
    """Return claim snippets that look numeric/prescriptive but lack finding support."""
    if not _NUMERIC_CLAIM.search(content):
        return ()
    supported_text = " ".join(
        findings_by_id[ref].statement + " " + findings_by_id[ref].rationale
        for ref in finding_refs
        if ref in findings_by_id
    ).lower()
    unsupported: list[str] = []
    for match in _NUMERIC_CLAIM.finditer(content):
        snippet = match.group(0)
        if snippet.lower() not in supported_text:
            unsupported.append(snippet)
    return tuple(unsupported)


def inject_citation_markers(
    content: str,
    citation_ids: tuple[str, ...],
) -> str:
    """Append deterministic citation markers when prose lacks inline refs."""
    if not citation_ids:
        return content
    existing = set(_CITATION_MARKER.findall(content))
    missing = [cid for cid in citation_ids if cid not in existing]
    if not missing:
        return content
    suffix = " ".join(f"[{cid}]" for cid in missing)
    return f"{content.rstrip()} {suffix}".strip()


def align_section_provenance(
    section: ReportSection,
    *,
    findings_by_id: dict[str, Finding],
    registry: dict[str, dict],
) -> ReportSection:
    content = inject_citation_markers(section.content, section.citation_ids)
    unsupported = detect_unsupported_numeric_claims(
        content,
        finding_refs=section.finding_refs,
        findings_by_id=findings_by_id,
    )
    if unsupported:
        for snippet in unsupported:
            content = content.replace(snippet, f"[unsupported:{snippet}]")
    for cid in section.citation_ids:
        if cid not in registry:
            raise ValueError(f"Citation marker {cid} missing from registry")
    return ReportSection(
        id=section.id,
        title=section.title,
        content=content,
        research_question_refs=section.research_question_refs,
        finding_refs=section.finding_refs,
        insight_refs=section.insight_refs,
        evidence_refs=section.evidence_refs,
        citation_ids=section.citation_ids,
        metadata=dict(section.metadata),
    )


def _merge_sections(
    title: str,
    sections: list[ReportSection],
    *,
    section_kind: str,
    primary_rq: str | None = None,
) -> ReportSection:
    contents = [s.content.strip() for s in sections if s.content.strip()]
    finding_refs: set[str] = set()
    insight_refs: set[str] = set()
    evidence_refs: set[str] = set()
    citation_ids: set[str] = set()
    rq_refs: set[str] = set()
    for section in sections:
        finding_refs.update(section.finding_refs)
        insight_refs.update(section.insight_refs)
        evidence_refs.update(section.evidence_refs)
        citation_ids.update(section.citation_ids)
        rq_refs.update(section.research_question_refs)
    metadata = {"section_kind": section_kind, "merged_from": len(sections)}
    if primary_rq:
        metadata["primary_research_question_id"] = primary_rq
        rq_refs = {primary_rq}
    return ReportSection(
        id=str(uuid4()),
        title=title,
        content="\n\n".join(contents),
        research_question_refs=tuple(sorted(rq_refs)),
        finding_refs=tuple(sorted(finding_refs)),
        insight_refs=tuple(sorted(insight_refs)),
        evidence_refs=tuple(sorted(evidence_refs)),
        citation_ids=tuple(sorted(citation_ids)),
        metadata=metadata,
    )


def assemble_bounded_report(
    raw_sections: list[ReportSection],
    *,
    design: ResearchDesign,
    findings: list[Finding],
    limitations: tuple[str, ...],
    max_sections: int = DEFAULT_REPORT_MAX_SECTIONS,
    section_batch_map: dict[str, str | None] | None = None,
) -> tuple[ReportSection, ...]:
    """Collapse section explosion into bounded RQ-centric architecture."""
    section_batch_map = section_batch_map or {}
    by_rq: dict[str, list[ReportSection]] = {q.id: [] for q in design.research_questions}
    unscoped: list[ReportSection] = []
    special: list[ReportSection] = []

    for section in raw_sections:
        kind = (section.metadata or {}).get("section_kind")
        if kind in {"contradictions", "limitations", "recommendations"}:
            special.append(section)
            continue
        primary = primary_research_question_for_section(
            section,
            batch_question_id=section_batch_map.get(section.id),
        )
        if primary and primary in by_rq:
            by_rq[primary].append(section)
        else:
            unscoped.append(section)

    assembled: list[ReportSection] = []
    for question in design.research_questions:
        group = by_rq.get(question.id, [])
        if not group:
            continue
        title = f"{question.id}: {question.question[:80]}"
        assembled.append(
            _merge_sections(
                title,
                group,
                section_kind="rq_answer",
                primary_rq=question.id,
            ),
        )

    if unscoped:
        assembled.append(
            _merge_sections(
                "Cross-cutting analysis",
                unscoped,
                section_kind="cross_cutting",
            ),
        )

    contradiction = build_contradiction_section(findings)
    if contradiction is not None:
        assembled.append(contradiction)

    contextual_limits = synthesize_contextual_limitations(
        design=design,
        global_limitations=limitations,
        findings=findings,
    )
    assembled.append(build_limitations_section(contextual_limits, design=design))

    rec_sections = [s for s in special if (s.metadata or {}).get("section_kind") == "recommendations"]
    if rec_sections:
        assembled.append(
            _merge_sections(
                RECOMMENDATIONS_SECTION_TITLE,
                rec_sections,
                section_kind="recommendations",
            ),
        )

    if len(assembled) > max_sections:
        assembled = assembled[:max_sections]
    return tuple(assembled)
