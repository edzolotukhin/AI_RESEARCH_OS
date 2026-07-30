from agents.base_agent import BaseAgent

from application.contracts.base_executor import BaseExecutor

from runtime.workflow_context import WorkflowContext


class AgentExecutor(BaseExecutor):
    """
    Infrastructure adapter for AI agents.

    Delegates execution to Agent.run(WorkflowContext) and persists the
    returned context as the task result. Contains no business logic.
    """

    def __init__(
        self,
        agent: BaseAgent,
    ) -> None:
        self._agent = agent

    @property
    def agent(self) -> BaseAgent:
        return self._agent

    def run(
        self,
        context: WorkflowContext,
    ) -> WorkflowContext:
        result_context = self._agent.run(context)

        task = context.current_task
        if task is not None:
            result_context.intermediate_results[task.id] = result_context

        return result_context
