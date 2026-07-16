from domain.project_brief import ProjectBrief


class PromptBuilder:

    @staticmethod
    def build_project_brief(brief: ProjectBrief) -> str:

        objectives = "\n".join(
            f"- {objective}"
            for objective in brief.research_objectives
        )

        constraints = "\n".join(
            f"- {constraint}"
            for constraint in brief.constraints
        )

        attachments = "\n".join(
            f"- {attachment}"
            for attachment in brief.attachments
        )

        return f"""
Client:
{brief.client}

Project:
{brief.project_title}

Business problem:
{brief.business_problem}

Research goal:
{brief.research_goal}

Research objectives:
{objectives}

Research object:
{brief.research_object}

Target audience:
{brief.target_audience}

Geography:
{brief.geography}

Timeline:
{brief.timeline}

Constraints:
{constraints}

Comments:
{brief.comments}

Attachments:
{attachments}
""".strip()