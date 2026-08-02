from agents.base_agent import BaseAgent

from runtime.workflow_context import WorkflowContext


class AnalysisAgent(BaseAgent):
    """
    Legacy stub — not wired in production composition root (DR-02).

    Production uses UnimplementedCapabilityExecutor for the analysis stage until
    DR-05. DeterministicStageExecutor is used only when
    DETERMINISTIC_STAGE_EXECUTORS is explicitly enabled.
    """

    def __init__(self) -> None:
        super().__init__("analysis")

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        context.write_shared("analysis_completed", True)
        return context
