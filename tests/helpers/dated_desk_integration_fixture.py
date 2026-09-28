"""Grounded, in-period synthetic sources for positive Desk integration flows.

The default deterministic smoke source intentionally has no observation date.
It must not be used to assert downstream completion for a dated brief.
"""

from dataclasses import replace

from application.config import ApplicationOverrides
from application.ports.evidence_ports import EvidenceCandidate
from domain.evidence.evidence_type import EvidenceType
from domain.sources.retrieval_status import RetrievalStatus
from infrastructure.search.deterministic_search_adapter import DeterministicSourceRetriever
from infrastructure.evidence.deterministic_evidence_extractor import DeterministicEvidenceExtractor


_OBSERVATIONS = (
    ("example.com/market-report", 41),
    ("research.example.org/brand-health", 43),
    ("research.example.org/industry-trends", 39),
)


class DatedDeskSourceRetriever(DeterministicSourceRetriever):
    def retrieve(self, candidate):
        source = super().retrieve(candidate)
        if source.retrieval_status != RetrievalStatus.ACQUIRED:
            return source
        for marker, percentage in _OBSERVATIONS:
            if marker in source.canonical_url:
                return replace(
                    source,
                    content_text=(
                        "As of 2026-06-30, measured Purina brand awareness in "
                        f"the Germany pet food market was {percentage} percent."
                    ),
                )
        return source


class DatedDeskEvidenceExtractor(DeterministicEvidenceExtractor):
    def extract(self, *, source, design, run_context):
        if not source.content_text.startswith("As of 2026-06-30, measured Purina"):
            return super().extract(source=source, design=design, run_context=run_context)
        needs = {need.id: need for need in design.information_needs}
        results = []
        for need_id in run_context.information_need_ids:
            need = needs.get(need_id)
            if need is None:
                continue
            results.append(EvidenceCandidate(
                statement=source.content_text,
                source_excerpt=source.content_text,
                evidence_type=EvidenceType.DIRECT_EXCERPT.value,
                research_question_refs=(need.research_question_id,),
                information_need_refs=(need.id,),
                confidence=0.9,
                direct=True,
                metadata={"observation_period": "2026-06-30", "synthetic_fixture": True},
            ))
        return results


def dated_desk_overrides(**kwargs) -> ApplicationOverrides:
    return ApplicationOverrides(
        source_retriever=DatedDeskSourceRetriever(),
        evidence_extractor=DatedDeskEvidenceExtractor(),
        **kwargs,
    )
