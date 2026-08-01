"""Shared ResearchBrief fixtures for tests."""

from __future__ import annotations

from domain.research_brief import ResearchBrief

CANONICAL_BRIEF_REQUEST: dict = {
    "title": "Brand Health 2026",
    "business_question": "Assess market position.",
    "objectives": ["Evaluate brand awareness."],
    "geography": ["Germany"],
    "market": "Pet food",
    "target_entities": ["Purina"],
    "timeframe": "2026",
    "constraints": [],
    "deliverables": ["Executive summary"],
    "language": "en",
    "context": "Client: Purina",
    "known_information": [],
    "exclusions": [],
}

LEGACY_BRIEF_REQUEST: dict = {
    "client": "Purina",
    "project_title": "Brand Health 2026",
    "business_problem": "Assess market position.",
    "research_goal": "Evaluate brand awareness.",
}


def sample_research_brief(**overrides) -> ResearchBrief:
    payload = {**CANONICAL_BRIEF_REQUEST, **overrides}
    return ResearchBrief.from_dict(payload)
