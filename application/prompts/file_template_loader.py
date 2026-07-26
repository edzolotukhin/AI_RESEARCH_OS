from pathlib import Path

from application.prompts.template_loader import TemplateLoader


class FileTemplateLoader(TemplateLoader):
    """
    Loads prompt templates from the local filesystem.
    """

    def load(
        self,
        template_path: Path,
    ) -> str:
        """
        Load a template file and return its content.
        """
        return template_path.read_text(encoding="utf-8")