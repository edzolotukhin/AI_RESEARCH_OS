"""Deterministic sufficiency assessment identity (P1-07.11)."""

from __future__ import annotations

import hashlib
import json
from typing import Sequence

from domain.evidence.evidence import Evidence
from domain.planning.research_design import InformationNeed, ResearchQuestion

from application.research_quality.allowed_aspect_ids import resolve_allowed_aspect_ids

SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION = "p1-07-11.1"


def canonical_json_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_sufficiency_assessment_fingerprint(
    *,
    information_need: InformationNeed,
    research_question: ResearchQuestion,
    evidence_ids: Sequence[str],
    evidence_by_id: dict[str, Evidence],
    max_evidence_items: int,
) -> str:
    """Identity of one semantic sufficiency assessment input set.

    Order-independent for evidence: IDs are sorted. Does not use hash().
    """
    allowed_aspects = resolve_allowed_aspect_ids(information_need)
    expectation = (
        information_need.evidence_expectation.to_dict()
        if information_need.evidence_expectation is not None
        else None
    )
    evidence_payload = []
    for evidence_id in sorted(str(item_id) for item_id in evidence_ids):
        item = evidence_by_id.get(evidence_id)
        if item is None:
            evidence_payload.append({"id": evidence_id, "missing": True})
            continue
        evidence_payload.append(
            {
                "id": item.id,
                "statement": item.statement,
                "source_excerpt": item.source_excerpt,
                "source_id": item.source_id,
                "source_content_checksum": item.source_content_checksum,
                "deduplication_key": item.deduplication_key,
                "evidence_type": item.evidence_type.value,
                "confidence": item.confidence,
                "information_need_refs": sorted(item.information_need_refs),
                "research_question_refs": sorted(item.research_question_refs),
            }
        )
    payload = {
        "contract_version": SUFFICIENCY_ASSESSMENT_CONTRACT_VERSION,
        "information_need_id": information_need.id,
        "research_question_id": information_need.research_question_id,
        "description": information_need.description,
        "research_question": research_question.question,
        "priority": information_need.priority,
        "preferred_source_types": list(information_need.preferred_source_types),
        "timeframe": information_need.timeframe,
        "geography": information_need.geography,
        "evidence_expectation": expectation,
        "allowed_aspect_ids": list(allowed_aspects),
        "max_evidence_items": max_evidence_items,
        "evidence": evidence_payload,
    }
    return canonical_json_digest(payload)
