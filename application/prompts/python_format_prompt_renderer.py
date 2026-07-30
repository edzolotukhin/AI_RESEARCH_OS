from application.prompts.prompt_renderer import PromptRenderer


class PythonFormatPromptRenderer(PromptRenderer):
    """
    Renders templates using Python's built-in str.format().
    """

    def render(
        self,
        template: str,
        variables: dict[str, object],
    ) -> str:
        """
        Render a template using Python string formatting.
        """
        return template.format(**variables)