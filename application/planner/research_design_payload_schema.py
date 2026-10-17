"""Canonical Planner ResearchDesign payload contract shown to the model."""

from __future__ import annotations


RESEARCH_DESIGN_PAYLOAD_SCHEMA = """
{
  "research_questions": [
    {
      "id": "string",
      "question": "string",
      "objective_refs": ["string"],
      "priority": 1,
      "rationale": "string"
    }
  ],
  "information_needs": [
    {
      "id": "string",
      "research_question_id": "string",
      "description": "string",
      "priority": 1,
      "preferred_source_types": ["string"],
      "timeframe": "string",
      "geography": "string",
      "evidence_expectation": {
        "nature": "quantitative|qualitative|mixed",
        "required_aspects": ["stable_snake_case_identifier"],
        "geography": "string",
        "timeframe": "string",
        "minimum_independent_sources": 1,
        "requires_quantitative_evidence": false
      }
    }
  ],
  "research_subject": {
    "version": "RESEARCH_SUBJECT/1",
    "canonical_label": "string",
    "canonical_language": "string",
    "lexical_representations": [
      {"language": "string", "label": "string"}
    ],
    "supporting_relations": [
      {
        "relation_id": "stable-string",
        "relation_type": "population_context|regulatory_context|trade_import_context|channel_context|economic_context|clinical_technical_context",
        "information_need_refs": ["exact-current-information-need-id"],
        "research_question_refs": ["exact-current-research-question-id"],
        "required_aspect_refs": ["exact-current-required-aspect-id"],
        "concepts": ["stable-concept-id"],
        "lexical_representations": [
          {
            "representation_id": "stable-string",
            "language": "string",
            "label": "string",
            "normalized_phrases": ["string"],
            "concept_refs": ["stable-concept-id"]
          }
        ],
        "explanation": "short scoped explanation"
      }
    ],
    "exclusions": ["string"]
  },
  "source_strategy": ["string"],
  "analysis_plan": ["string"],
  "deliverable_plan": ["string"],
  "assumptions": ["string"],
  "limitations": ["string"],
  "language": "string"
}
""".strip()


PLANNER_PAYLOAD_SCHEMA = RESEARCH_DESIGN_PAYLOAD_SCHEMA
