VALID_PLANNER_RESPONSE = {
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

VALID_PLANNER_JSON = """
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

UNKNOWN_EXECUTOR_PLANNER_JSON = """
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

MARKDOWN_PLANNER_JSON = f"""Here is the requested research plan:

```json
{VALID_PLANNER_JSON.strip()}
```

Let me know if you need changes.
"""

EXPLANATORY_PLANNER_JSON = f"""Sure! Based on your brief, I prepared this workflow:

{VALID_PLANNER_JSON.strip()}

This plan covers the core research stages.
"""

TRAILING_COMMA_PLANNER_JSON = """
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
          "dependencies": [],
        }
      ],
    }
  ],
  "metadata": {},
}
"""

TRUNCATED_PLANNER_JSON = """
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
        }
      ]
    }
  ],
  "metadata": {}
"""
