from abc import ABC, abstractmethod


class PromptRenderer(ABC):
    """
    Renders a template using the provided variables.
    """

    @abstractmethod
    def render(
        self,
        template: str,
        variables: dict[str, object],
    ) -> str:
        """
        Render a template with the provided variables.
        """
        ...