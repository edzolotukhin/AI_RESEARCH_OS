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
      "kind": "ACQUIRED",
      "depends_on_information_need_ids": [],
      "evidence_coverage": {
        "required_metric": "explicit metric",
        "required_unit": "explicit unit",
        "required_periods": ["explicit observation period"],
        "geography": "explicit observation geography"
      },
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

RESEARCH_DESIGN_PAYLOAD_SCHEMA += """

Choose kind from ACQUIRED, DERIVED, OUTPUT for each Information Need.
ACQUIRED requires evidence_expectation. For quantitative ACQUIRED or when
requires_quantitative_evidence is true, declare authoritative evidence_coverage
with required_metric, required_unit, required_periods and geography from the Brief.
Do not infer missing units from future Evidence. Mark unresolved requirements in
limitations so approval can request clarification.
DERIVED requires depends_on_information_need_ids and a derivation object using
version "derivation-v1", operation_type, metric, input_unit, geography,
required_periods, decimal_places, max_inputs, max_provider_attempts and method.
In a derivation, max_inputs is the maximum number of input Evidence/Findings;
it is independent of required_periods. required_periods is the bounded ordered
set of mandatory annual observation years and may contain more years than the
number of input Evidence/Findings when one source covers multiple years.
Allowed operations are YEAR_OVER_YEAR_ABSOLUTE_CHANGE, YEAR_OVER_YEAR_PERCENT_CHANGE,
CUMULATIVE_ABSOLUTE_CHANGE, CUMULATIVE_PERCENT_CHANGE, TREND_CHARACTERIZATION,
CROSS_SOURCE_COMPARISON and LIMITATION_SYNTHESIS.
Semantic operations require an explicit method. Calculation periods are ordered years.
OUTPUT declares dependencies and may declare output_format "table" or "chart".
DERIVED and OUTPUT can omit evidence_expectation and evidence_coverage.
Dependencies must reference current Information Need IDs and form an acyclic graph.
"""


PLANNER_PAYLOAD_SCHEMA = RESEARCH_DESIGN_PAYLOAD_SCHEMA
