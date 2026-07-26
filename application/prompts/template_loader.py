from abc import ABC, abstractmethod
from pathlib import Path


class TemplateLoader(ABC):
    """
    Loads prompt templates from a source.
    """

    @abstractmethod
    def load(
        self,
        template_path: Path,
    ) -> str:
        """
        Load a template and return its content.
        """
        ...