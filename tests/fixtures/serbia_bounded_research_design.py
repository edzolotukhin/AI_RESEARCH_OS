"""Bounded ResearchDesign JSON for Serbia Microgreens acceptance regression."""

from __future__ import annotations

import json

from tests.fixtures.planner_responses import planner_evidence_expectation
from tests.fixtures.serbia_microgreens_brief import SERBIA_MICROGREENS_BRIEF

_OBJECTIVES = SERBIA_MICROGREENS_BRIEF["objectives"]

SERBIA_BOUNDED_RESEARCH_DESIGN: dict = {
    "research_questions": [
        {
            "id": "rq-market",
            "question": "What is the size and maturity of Serbia's microgreens market?",
            "objective_refs": [_OBJECTIVES[0]],
            "priority": 1,
            "rationale": "Establish baseline market context.",
        },
        {
            "id": "rq-horeca",
            "question": "What HoReCa demand and chef usage patterns exist for microgreens?",
            "objective_refs": [_OBJECTIVES[1], _OBJECTIVES[2]],
            "priority": 1,
            "rationale": "Quantify buyer-side opportunity.",
        },
        {
            "id": "rq-competition",
            "question": "Who are the main competitors, suppliers, assortment, and price bands?",
            "objective_refs": [_OBJECTIVES[3], _OBJECTIVES[4], _OBJECTIVES[5]],
            "priority": 2,
            "rationale": "Map competitive and pricing landscape.",
        },
        {
            "id": "rq-distribution",
            "question": "Which geographies and distribution channels reach HoReCa buyers?",
            "objective_refs": [_OBJECTIVES[6]],
            "priority": 2,
            "rationale": "Identify route-to-market options.",
        },
        {
            "id": "rq-buyers",
            "question": "What buyer requirements, procurement criteria, and regulations apply?",
            "objective_refs": [_OBJECTIVES[7], _OBJECTIVES[8]],
            "priority": 3,
            "rationale": "Define compliance and sales constraints.",
        },
        {
            "id": "rq-entry",
            "question": "What initial market-entry strategy is recommended?",
            "objective_refs": [_OBJECTIVES[9]],
            "priority": 1,
            "rationale": "Synthesize findings into actionable entry plan.",
        },
    ],
    "information_needs": [
        {
            "id": "in-market-size",
            "research_question_id": "rq-market",
            "description": "Serbia microgreens market size and growth signals.",
            "priority": 1,
            "preferred_source_types": ["industry reports", "reputable media"],
            "timeframe": "2025-2026",
            "geography": "Serbia",
            "evidence_expectation": planner_evidence_expectation(
                "market_size_signals",
                "market_growth_signals",
                nature="mixed",
            ),
        },
        {
            "id": "in-horeca-demand",
            "research_question_id": "rq-horeca",
            "description": "HoReCa demand trends and chef usage examples.",
            "priority": 1,
            "preferred_source_types": ["reputable media", "industry associations"],
            "timeframe": "2025-2026",
            "geography": "Serbia",
            "evidence_expectation": planner_evidence_expectation(
                "horeca_demand_trends",
                "chef_usage_examples",
                nature="qualitative",
            ),
        },
        {
            "id": "in-competitors",
            "research_question_id": "rq-competition",
            "description": "Competitor and supplier profiles with assortment and pricing.",
            "priority": 1,
            "preferred_source_types": ["company reports", "reputable media"],
            "timeframe": "2025-2026",
            "geography": "Serbia",
            "evidence_expectation": planner_evidence_expectation(
                "competitor_profiles",
                "assortment_and_pricing",
                nature="mixed",
            ),
        },
        {
            "id": "in-distribution",
            "research_question_id": "rq-distribution",
            "description": "Distribution channels serving HoReCa in Serbia.",
            "priority": 2,
            "preferred_source_types": ["industry reports", "reputable media"],
            "timeframe": "2025-2026",
            "geography": "Serbia",
            "evidence_expectation": planner_evidence_expectation(
                "distribution_channels",
                nature="qualitative",
            ),
        },
        {
            "id": "in-buyers",
            "research_question_id": "rq-buyers",
            "description": "Buyer requirements and food-service procurement norms.",
            "priority": 2,
            "preferred_source_types": ["regulator/government", "industry associations"],
            "timeframe": "2025-2026",
            "geography": "Serbia",
            "evidence_expectation": planner_evidence_expectation(
                "buyer_procurement_requirements",
                nature="qualitative",
            ),
        },
        {
            "id": "in-regulation",
            "research_question_id": "rq-buyers",
            "description": "Relevant food safety and labeling regulations.",
            "priority": 3,
            "preferred_source_types": ["regulator/government"],
            "timeframe": "2025-2026",
            "geography": "Serbia",
            "evidence_expectation": planner_evidence_expectation(
                "food_safety_labeling_rules",
                nature="qualitative",
            ),
        },
    ],
    "source_strategy": [
        "industry reports",
        "reputable media",
        "regulator/government",
        "company reports",
    ],
    "analysis_plan": [
        "market sizing synthesis",
        "HoReCa demand assessment",
        "competitive benchmarking",
        "distribution fit analysis",
        "entry option comparison",
    ],
    "deliverable_plan": [
        "executive summary",
        "market overview",
        "competitive landscape",
        "entry recommendations",
    ],
    "assumptions": ["Public desk sources are sufficient for initial screening."],
    "limitations": ["No primary interviews in this phase."],
    "language": "en",
}

SERBIA_BOUNDED_RESEARCH_DESIGN_JSON = json.dumps(
    SERBIA_BOUNDED_RESEARCH_DESIGN,
    ensure_ascii=True,
)
