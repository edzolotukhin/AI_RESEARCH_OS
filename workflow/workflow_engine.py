from runtime.research_context import ResearchContext


class WorkflowEngine:
    """
    Оркестратор выполнения пайплайна агентов.
    """

    def __init__(self, pipeline):
        self.pipeline = pipeline

    def run(
        self,
        context: ResearchContext,
    ) -> ResearchContext:

        if context is None:
            raise ValueError("ResearchContext is required")

        for agent in self.pipeline:
            context = agent.run(context)

        return context