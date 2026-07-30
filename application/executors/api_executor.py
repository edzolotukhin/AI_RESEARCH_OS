from runtime.workflow_context import WorkflowContext

from application.contracts.base_executor import BaseExecutor


class APIExecutor(BaseExecutor):
    """
    Minimal placeholder for API-backed tasks.
    """

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        return context
