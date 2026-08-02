from domain.project import Project
from domain.legacy.methodology_proposal import (
    MethodologyProposal,
    BusinessProblem,
    ResearchObjectives,
    ResearchStrategy,
    Methodology,
    SamplingPlan,
    Risk,
    RiskAssessment,
)

from agents.base_agent import BaseAgent
from constants.prompts import Prompts


class ResearchDesigner(BaseAgent):
    """
    Deprecated legacy agent for MethodologyProposal generation.

    Not wired into the desk-research production path (PlannerAgent owns
    semantic ResearchDesign). Removal condition: delete when Client Manager
    vertical is retired or migrated.
    """

    def __init__(self):
        super().__init__()

    def prompt_name(self) -> str:
        return Prompts.RESEARCH_DESIGN

    def build_user_prompt(
        self,
        project: Project
    ) -> str:

        return self.create_user_prompt(
            f"""Project Brief

{project.research_brief}"""
        )

    def parse_response(
        self,
        project: Project,
        data: dict
    ) -> Project:

        project.methodology_proposal = MethodologyProposal(

            business_problem=BusinessProblem(
                description=data["business_problem"]["description"],
                business_decision=data["business_problem"]["business_decision"]
            ),

            objectives=ResearchObjectives(
                primary=data["objectives"]["primary"],
                secondary=data["objectives"]["secondary"]
            ),

            strategy=ResearchStrategy(
                recommendation=data["strategy"]["recommendation"],
                rationale=data["strategy"]["rationale"],
                alternatives=data["strategy"]["alternatives"]
            ),

            methodology=Methodology(
                methods=data["methodology"]["methods"],
                target_audience=data["methodology"]["target_audience"],
                geography=data["methodology"]["geography"],
                timeline=data["methodology"]["timeline"]
            ),

            sampling=SamplingPlan(
                sample_size=data["sampling"]["sample_size"],
                sampling_method=data["sampling"]["sampling_method"],
                quotas=data["sampling"]["quotas"]
            ),

            risks=RiskAssessment(
                risks=[
                    Risk(
                        description=risk["description"],
                        mitigation=risk["mitigation"]
                    )
                    for risk in data["risks"]
                ]
            )
        )

        return project
