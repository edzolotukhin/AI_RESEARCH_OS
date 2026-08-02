VALID_RESEARCH_DESIGN_RESPONSE = {
    "research_questions": [
        {
            "id": "rq-awareness",
            "question": "What is the current brand awareness level among target buyers?",
            "objective_refs": ["Evaluate brand awareness."],
            "priority": 1,
            "rationale": "Core metric for assessing market position.",
        },
        {
            "id": "rq-position",
            "question": "How does brand perception compare to key competitors?",
            "objective_refs": ["Evaluate brand awareness."],
            "priority": 2,
            "rationale": "Competitive context for positioning assessment.",
        },
    ],
    "information_needs": [
        {
            "id": "in-awareness-data",
            "research_question_id": "rq-awareness",
            "description": "Published brand tracking or awareness statistics for the category.",
            "priority": 1,
            "preferred_source_types": ["official statistics", "reputable media"],
            "timeframe": "2024-2026",
            "geography": "Germany",
        },
        {
            "id": "in-competitor-position",
            "research_question_id": "rq-position",
            "description": "Competitor brand share and positioning reports.",
            "priority": 2,
            "preferred_source_types": ["company reports", "industry associations"],
            "timeframe": "2024-2026",
            "geography": "Germany",
        },
    ],
    "source_strategy": [
        "official statistics",
        "company reports",
        "industry associations",
        "reputable media",
    ],
    "analysis_plan": [
        "brand awareness benchmarking",
        "competitor comparison",
        "trend synthesis",
    ],
    "deliverable_plan": [
        "executive summary",
        "market overview",
        "competitor landscape",
        "key insights",
    ],
    "assumptions": ["Publicly available data is sufficient for desk research scope."],
    "limitations": ["No primary survey fieldwork in this phase."],
    "language": "en",
}

VALID_RESEARCH_DESIGN_JSON = """
{
  "research_questions": [
    {
      "id": "rq-awareness",
      "question": "What is the current brand awareness level among target buyers?",
      "objective_refs": ["Evaluate brand awareness."],
      "priority": 1,
      "rationale": "Core metric for assessing market position."
    },
    {
      "id": "rq-position",
      "question": "How does brand perception compare to key competitors?",
      "objective_refs": ["Evaluate brand awareness."],
      "priority": 2,
      "rationale": "Competitive context for positioning assessment."
    }
  ],
  "information_needs": [
    {
      "id": "in-awareness-data",
      "research_question_id": "rq-awareness",
      "description": "Published brand tracking or awareness statistics for the category.",
      "priority": 1,
      "preferred_source_types": ["official statistics", "reputable media"],
      "timeframe": "2024-2026",
      "geography": "Germany"
    },
    {
      "id": "in-competitor-position",
      "research_question_id": "rq-position",
      "description": "Competitor brand share and positioning reports.",
      "priority": 2,
      "preferred_source_types": ["company reports", "industry associations"],
      "timeframe": "2024-2026",
      "geography": "Germany"
    }
  ],
  "source_strategy": [
    "official statistics",
    "company reports",
    "industry associations",
    "reputable media"
  ],
  "analysis_plan": [
    "brand awareness benchmarking",
    "competitor comparison",
    "trend synthesis"
  ],
  "deliverable_plan": [
    "executive summary",
    "market overview",
    "competitor landscape",
    "key insights"
  ],
  "assumptions": ["Publicly available data is sufficient for desk research scope."],
  "limitations": ["No primary survey fieldwork in this phase."],
  "language": "en"
}
"""

# Backward-compatible aliases for tests migrating from DR-01 planner fixtures.
VALID_PLANNER_RESPONSE = VALID_RESEARCH_DESIGN_RESPONSE
VALID_PLANNER_JSON = VALID_RESEARCH_DESIGN_JSON

LEGACY_PLANNER_RESPONSE = {
    "name": "Brand Health Workflow",
    "goal": "Evaluate brand awareness, usage and loyalty.",
    "methodology": "Quantitative brand tracking survey",
    "stages": [
        {
            "id": "stage-design",
            "name": "Research Design",
            "description": "Define methodology and sample design.",
            "tasks": [
                {
                    "id": "task-methodology",
                    "title": "Define methodology",
                    "description": "Select research methods and metrics.",
                    "executor_id": "planner",
                    "dependencies": [],
                },
                {
                    "id": "task-sample",
                    "title": "Design sample plan",
                    "description": "Define target audience and sample size.",
                    "executor_id": "search",
                    "dependencies": ["task-methodology"],
                },
            ],
        }
    ],
    "metadata": {},
}

LEGACY_PLANNER_JSON = """
{
  "name": "Brand Health Workflow",
  "goal": "Evaluate brand awareness, usage and loyalty.",
  "methodology": "Quantitative brand tracking survey",
  "stages": [
    {
      "id": "stage-design",
      "name": "Research Design",
      "description": "Define methodology and sample design.",
      "tasks": [
        {
          "id": "task-methodology",
          "title": "Define methodology",
          "description": "Select research methods and metrics.",
          "executor_id": "planner",
          "dependencies": []
        },
        {
          "id": "task-sample",
          "title": "Design sample plan",
          "description": "Define target audience and sample size.",
          "executor_id": "search",
          "dependencies": ["task-methodology"]
        }
      ]
    }
  ],
  "metadata": {}
}
"""

LEGACY_UNKNOWN_EXECUTOR_PLANNER_JSON = """
{
  "name": "Brand Health Workflow",
  "goal": "Evaluate brand awareness, usage and loyalty.",
  "methodology": "Quantitative brand tracking survey",
  "stages": [
    {
      "id": "stage-design",
      "name": "Research Design",
      "description": "Define methodology and sample design.",
      "tasks": [
        {
          "id": "task-methodology",
          "title": "Define methodology",
          "description": "Select research methods and metrics.",
          "executor_id": "ResearchLead",
          "dependencies": []
        }
      ]
    }
  ],
  "metadata": {}
}
"""

UNKNOWN_EXECUTOR_PLANNER_JSON = """
{
  "research_questions": [],
  "information_needs": [],
  "source_strategy": [],
  "analysis_plan": [],
  "deliverable_plan": [],
  "language": "en"
}
"""

INVALID_DUPLICATE_QUESTION_JSON = """
{
  "research_questions": [
    {
      "id": "rq-1",
      "question": "What is market size?",
      "objective_refs": ["Evaluate brand awareness."],
      "priority": 1,
      "rationale": ""
    },
    {
      "id": "rq-1",
      "question": "Who are competitors?",
      "objective_refs": ["Evaluate brand awareness."],
      "priority": 2,
      "rationale": ""
    }
  ],
  "information_needs": [],
  "source_strategy": ["official statistics"],
  "analysis_plan": ["competitor comparison"],
  "deliverable_plan": ["executive summary"],
  "language": "en"
}
"""

MARKDOWN_PLANNER_JSON = f"""Here is the requested research design:

```json
{VALID_RESEARCH_DESIGN_JSON.strip()}
```

Let me know if you need changes.
"""

EXPLANATORY_PLANNER_JSON = f"""Sure! Based on your brief, I prepared this design:

{VALID_RESEARCH_DESIGN_JSON.strip()}

This design covers the core research questions.
"""

TRAILING_COMMA_PLANNER_JSON = """
{
  "research_questions": [
    {
      "id": "rq-1",
      "question": "What is market size?",
      "objective_refs": ["Evaluate brand awareness."],
      "priority": 1,
      "rationale": "",
    }
  ],
  "information_needs": [],
  "source_strategy": ["official statistics"],
  "analysis_plan": ["market sizing"],
  "deliverable_plan": ["executive summary"],
  "language": "en",
}
"""

TRUNCATED_PLANNER_JSON = """
{
  "research_questions": [
    {
      "id": "rq-1",
      "question": "What is market size?",
      "objective_refs": ["Evaluate brand awareness."],
      "priority": 1,
      "rationale": ""
    }
  ],
  "information_needs": [],
  "source_strategy": ["official statistics"],
  "analysis_plan": ["market sizing"],
  "deliverable_plan": ["executive summary"],
  "language": "en"
"""
