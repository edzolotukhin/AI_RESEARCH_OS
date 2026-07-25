from registry.agent_registry import AgentRegistry
from registry.workflow_registry import WorkflowRegistry
from registry.tool_registry import ToolRegistry
from registry.knowledge_registry import KnowledgeRegistry


class Registry:
    """
    Центральный контейнер Registry платформы.
    """

    def __init__(self):
        self.agents = AgentRegistry()
        self.workflows = WorkflowRegistry()
        self.tools = ToolRegistry()
        self.knowledge = KnowledgeRegistry()

    def get(self, executor_id: str):
        return self.agents.get(executor_id)