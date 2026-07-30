from runtime.workflow_context import WorkflowContext

from application.contracts.base_executor import BaseExecutor


class HumanExecutor(BaseExecutor):
    """
    Minimal placeholder for human-in-the-loop tasks.
    """

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        return context
