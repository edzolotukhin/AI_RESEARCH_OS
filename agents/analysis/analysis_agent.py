from agents.base_agent import BaseAgent

from runtime.workflow_context import WorkflowContext


class AnalysisAgent(BaseAgent):
    """
    Agent for data analysis tasks.
    """

    def __init__(self) -> None:
        super().__init__("analysis")

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.write_shared("analysis_completed", True)
        return context
