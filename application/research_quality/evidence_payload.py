from __future__ import annotations

from typing import Any, Sequence

from domain.evidence.evidence import Evidence

DEFAULT_MAX_EVIDENCE_ITEMS = 10


def select_bounded_evidence(
    evidence: Sequence[Evidence],
    *,
    max_items: int = DEFAULT_MAX_EVIDENCE_ITEMS,
) -> tuple[Evidence, ...]:
    """Deterministically select a bounded evidence subset for semantic assessment."""
    if max_items < 1:
        raise ValueError("max_items must be at least 1.")
    sorted_items = sorted(
        evidence,
        key=lambda item: (
            -(item.confidence if item.confidence is not None else -1.0),
            item.id,
        ),
    )
    return tuple(sorted_items[:max_items])


def build_evidence_payload(
    evidence: Sequence[Evidence],
) -> list[dict[str, Any]]:
    """Compact evidence representation for semantic sufficiency prompts."""
    payload: list[dict[str, Any]] = []
    for item in evidence:
        entry: dict[str, Any] = {
            "id": item.id,
            "source_id": item.source_id,
            "evidence_type": item.evidence_type.value,
            "statement": item.statement,
            "source_excerpt": item.source_excerpt,
        }
        if item.confidence is not None:
            entry["confidence"] = item.confidence
        quality: dict[str, Any] = {}
        for key in (
            "source_quality_score",
            "source_quality",
            "freshness_score",
            "freshness",
            "source_diversity_score",
            "source_diversity",
        ):
            for container in (item.quality_signals, item.metadata):
                if key in container:
                    quality[key] = container[key]
                    break
        if quality:
            entry["quality_signals"] = quality
        if item.metadata.get("contradictions"):
            entry["contradictions"] = item.metadata["contradictions"]
        payload.append(entry)
    return payload
