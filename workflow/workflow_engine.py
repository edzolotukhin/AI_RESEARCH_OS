from domain.project import Project


class WorkflowEngine:

    def __init__(
        self,
        pipeline,
    ):

        self.pipeline = pipeline

    def run(
        self,
        project: Project,
    ) -> Project:

        for agent in self.pipeline:
            project = agent.execute(project)

        return project