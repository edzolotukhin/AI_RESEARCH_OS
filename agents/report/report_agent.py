from agents.base_agent import BaseAgent

from runtime.workflow_context import WorkflowContext


class ReportAgent(BaseAgent):
    """
    Agent for report generation tasks.
    """

    def __init__(self) -> None:
        super().__init__("report")

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.write_shared("report_completed", True)
        return context
