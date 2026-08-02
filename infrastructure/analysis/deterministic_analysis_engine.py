from __future__ import annotations

from domain.evidence.evidence import Evidence
from domain.findings.finding import Finding
from domain.planning.research_design import ResearchDesign

from application.ports.analysis_ports import (
    AnalysisInput,
    FindingCandidate,
    InsightCandidate,
)


class DeterministicAnalysisEngine:
    """
    Explicit test/smoke analysis engine.

    Consumes persisted run-scoped Evidence and emits Finding/Insight candidates
    referencing actual durable IDs.
    """

    method_name = "deterministic"

    def analyze_findings(self, analysis_input: AnalysisInput) -> list[FindingCandidate]:
        design = analysis_input.design
        question_by_id = {question.id: question for question in design.research_questions}
        need_by_id = {need.id: need for need in design.information_needs}
        candidates: list[FindingCandidate] = []

        grouped: dict[str, list[Evidence]] = {}
        for evidence in analysis_input.evidence_batch:
            if not evidence.research_question_refs:
                continue
            question_ids = evidence.research_question_refs
            if analysis_input.batch_question_id is not None:
                if analysis_input.batch_question_id not in question_ids:
                    continue
                question_ids = (analysis_input.batch_question_id,)
            for question_id in question_ids:
                grouped.setdefault(question_id, []).append(evidence)

        for question_id, evidence_items in grouped.items():
            question = question_by_id.get(question_id)
            question_text = question.question if question is not None else question_id
            evidence_refs = tuple(sorted({item.id for item in evidence_items}))
            need_refs = tuple(
                sorted(
                    {
                        ref
                        for item in evidence_items
                        for ref in item.information_need_refs
                        if ref in need_by_id
                    },
                ),
            )
            candidates.append(
                FindingCandidate(
                    statement=(
                        f"Evidence supports a material conclusion for: {question_text}"
                    ),
                    rationale=(
                        "Deterministic synthesis across grounded evidence statements "
                        f"for research question {question_id}."
                    ),
                    evidence_refs=evidence_refs,
                    research_question_refs=(question_id,),
                    information_need_refs=need_refs,
                    finding_type="synthesis",
                    confidence=0.75,
                    metadata={"deterministic": "true"},
                ),
            )
        return candidates

    def analyze_insights(self, analysis_input: AnalysisInput) -> list[InsightCandidate]:
        design = analysis_input.design
        question_by_id = {question.id: question for question in design.research_questions}
        candidates: list[InsightCandidate] = []

        grouped: dict[str, list[Finding]] = {}
        for finding in analysis_input.persisted_findings:
            if not finding.research_question_refs:
                continue
            question_id = finding.research_question_refs[0]
            grouped.setdefault(question_id, []).append(finding)

        for question_id, findings in grouped.items():
            question = question_by_id.get(question_id)
            question_text = question.question if question is not None else question_id
            finding_refs = tuple(sorted({item.id for item in findings}))
            candidates.append(
                InsightCandidate(
                    statement=(
                        f"Research on '{question_text}' has actionable implications "
                        "for the desk research objective."
                    ),
                    implication=(
                        "Monitor this theme as a priority area based on synthesized findings."
                    ),
                    finding_refs=finding_refs,
                    research_question_refs=(question_id,),
                    confidence=0.7,
                    metadata={"deterministic": "true"},
                ),
            )
        return candidates
