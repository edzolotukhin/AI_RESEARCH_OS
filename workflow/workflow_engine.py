from runtime.research_context import ResearchContext


class WorkflowEngine:

    def __init__(self, pipeline):
        self.pipeline = pipeline

    def run(
        self,
        context: ResearchContext,
    ) -> ResearchContext:

        for agent in self.pipeline:
            context = agent.run(context)

        return context