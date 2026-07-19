from domain.ai_task import AITask
from domain.project import Project

from infrastructure.documents.document_loader import DocumentLoader
from infrastructure.prompts.prompt_repository import PromptRepository


class PromptBuilder:
    """
    Отвечает за построение полного prompt для AI-задачи.
    """

    def __init__(self):

        self.prompt_repository = PromptRepository()
        self.document_loader = DocumentLoader()

    def build(
        self,
        task: AITask,
        project: Project,
        *knowledge_documents,
    ) -> tuple[str, str]:

        system_prompt = self.prompt_repository.load(
            task.prompt_name
        )

        knowledge = self.document_loader.load(
            *knowledge_documents
        )

        user_prompt = task.build_user_prompt(
            project,
            knowledge,
        )

        return (
            system_prompt,
            user_prompt,
        )