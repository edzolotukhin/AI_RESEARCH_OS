from dataclasses import dataclass


@dataclass
class KnowledgeContext:

    documents: list[str]

    content: str