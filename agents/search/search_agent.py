from agents.base_agent import BaseAgent

from runtime.workflow_context import WorkflowContext


class SearchAgent(BaseAgent):
    """
    Agent for information gathering and search tasks.
    """

    def __init__(self) -> None:
        super().__init__("search")

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.write_shared("search_completed", True)
        return context
