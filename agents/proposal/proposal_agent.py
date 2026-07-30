from agents.base_agent import BaseAgent

from runtime.workflow_context import WorkflowContext


class ProposalAgent(BaseAgent):
    """
    Agent for proposal and recommendation tasks.
    """

    def __init__(self) -> None:
        super().__init__("proposal")

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.write_shared("proposal_completed", True)
        return context
