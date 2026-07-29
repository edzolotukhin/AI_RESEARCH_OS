from registry.agent_registry import AgentRegistry
from registry.workflow_registry import WorkflowRegistry
from registry.tool_registry import ToolRegistry
from registry.knowledge_registry import KnowledgeRegistry
from registry.human_executor_registry import HumanExecutorRegistry
from registry.api_executor_registry import APIExecutorRegistry


class Registry:
    """
    Центральный контейнер Registry платформы.
    """

    def __init__(self):
        self.agents = AgentRegistry()
        self.tools = ToolRegistry()
        self.human_executors = HumanExecutorRegistry()
        self.api_executors = APIExecutorRegistry()
        self.workflows = WorkflowRegistry()
        self.knowledge = KnowledgeRegistry()

    def get(self, executor_id: str):
        return self.agents.get(executor_id)
