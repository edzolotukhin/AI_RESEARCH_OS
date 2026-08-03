from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerBounds:
    """Product-level cardinality limits for v1 ResearchDesign planner output."""

    max_research_questions: int = 6
    max_information_needs: int = 12
    max_source_strategies: int = 5
    max_analysis_plan_items: int = 6
    max_deliverable_plan_items: int = 6
    max_assumptions: int = 4
    max_limitations: int = 4

    @classmethod
    def from_env(cls) -> PlannerBounds:
        return cls(
            max_research_questions=int(
                os.environ.get("PLANNER_MAX_RESEARCH_QUESTIONS", "6"),
            ),
            max_information_needs=int(
                os.environ.get("PLANNER_MAX_INFORMATION_NEEDS", "12"),
            ),
            max_source_strategies=int(
                os.environ.get("PLANNER_MAX_SOURCE_STRATEGIES", "5"),
            ),
            max_analysis_plan_items=int(
                os.environ.get("PLANNER_MAX_ANALYSIS_PLAN_ITEMS", "6"),
            ),
            max_deliverable_plan_items=int(
                os.environ.get("PLANNER_MAX_DELIVERABLE_PLAN_ITEMS", "6"),
            ),
            max_assumptions=int(os.environ.get("PLANNER_MAX_ASSUMPTIONS", "4")),
            max_limitations=int(os.environ.get("PLANNER_MAX_LIMITATIONS", "4")),
        )

    def format_for_prompt(self) -> str:
        return "\n".join(
            [
                f"- research_questions: at most {self.max_research_questions}",
                f"- information_needs: at most {self.max_information_needs}",
                f"- source_strategy items: at most {self.max_source_strategies}",
                f"- analysis_plan items: at most {self.max_analysis_plan_items}",
                f"- deliverable_plan items: at most {self.max_deliverable_plan_items}",
                f"- assumptions items: at most {self.max_assumptions}",
                f"- limitations items: at most {self.max_limitations}",
            ]
        )

    def format_compact_instruction(self) -> str:
        return (
            "Keep question, need description, and rationale fields concise "
            "(typically one sentence each). Do not repeat the full brief text "
            "inside every object. Consolidate overlapping objectives into shared "
            "research questions with multiple objective_refs."
        )
