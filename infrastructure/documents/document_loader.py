from pathlib import Path

from domain.knowledge_context import KnowledgeContext


class DocumentLoader:

    def __init__(self):

        self.knowledge_path = Path("knowledge")

    def load(
        self,
        *documents: str
    ) -> KnowledgeContext:

        content = []

        for document in documents:

            path = self.knowledge_path / document

            with open(path, "r", encoding="utf-8") as file:

                content.append(file.read())

        return KnowledgeContext(
            documents=list(documents),
            content="\n\n".join(content)
        )