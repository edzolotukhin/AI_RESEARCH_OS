from agents.base_agent import BaseAgent

from runtime.workflow_context import WorkflowContext


class SearchAgent(BaseAgent):
    """
    Legacy stub — not wired in production composition root (DR-02).

    Production uses UnimplementedCapabilityExecutor for the search stage until
    DR-03. DeterministicStageExecutor is used only when
    DETERMINISTIC_STAGE_EXECUTORS is explicitly enabled.
    """

    def __init__(self) -> None:
        super().__init__("search")

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.write_shared("search_completed", True)
        return context
