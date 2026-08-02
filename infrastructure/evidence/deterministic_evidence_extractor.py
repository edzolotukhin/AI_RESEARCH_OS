from __future__ import annotations

from domain.evidence.evidence_type import EvidenceType
from domain.planning.research_design import ResearchDesign
from domain.sources.source import Source

from application.evidence.run_scoped_provenance import RunScopedSourceContext
from application.ports.evidence_ports import EvidenceCandidate, EvidenceExtractor


class DeterministicEvidenceExtractor(EvidenceExtractor):
    """
    Explicit test/smoke evidence extractor.

    Extracts grounded excerpts from deterministic Source.content_text using
    run-scoped information needs only.
    """

    method_name = "deterministic"

    _KNOWN_EXCERPT = "Acquired market report body text."

    def extract(
        self,
        *,
        source: Source,
        design: ResearchDesign,
        run_context: RunScopedSourceContext,
    ) -> list[EvidenceCandidate]:
        if self._KNOWN_EXCERPT not in source.content_text:
            return []

        need_by_id = {need.id: need for need in design.information_needs}
        question_by_id = {question.id: question for question in design.research_questions}
        candidates: list[EvidenceCandidate] = []

        for need_id in run_context.information_need_ids:
            need = need_by_id.get(need_id)
            if need is None:
                continue
            question = question_by_id.get(need.research_question_id)
            question_text = question.question if question is not None else need.description
            candidates.append(
                EvidenceCandidate(
                    statement=(
                        f"The source documents market report content relevant to: "
                        f"{question_text}"
                    ),
                    source_excerpt=self._KNOWN_EXCERPT,
                    evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                    research_question_refs=(need.research_question_id,),
                    information_need_refs=(need.id,),
                    confidence=0.9,
                    direct=True,
                    metadata={"deterministic": "true"},
                ),
            )
        return candidates
